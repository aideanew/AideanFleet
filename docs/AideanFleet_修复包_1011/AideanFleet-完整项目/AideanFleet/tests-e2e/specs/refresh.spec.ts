import { expect, test } from '@playwright/test'
import {
  gotoPage,
  readMode,
  readNotifyConfig,
  switchState,
  unlock,
  writeMode,
  writeNotifyConfig,
} from '../lib/helpers'

/**
 * 主题 9.3 · 跨刷新断言
 *
 * 覆盖三类持久化语义：
 *  ① 会话（sessionStorage token）→ 刷新后不回落锁屏；
 *  ② 路由 → 刷新后停留在原页面；
 *  ③ 面板宽度（localStorage fleet.nav.width）→ 刷新后按持久值恢复；
 *  ④ 调度模式 / ⑤ 提醒开关 → **服务端**持久，刷新后仍为新值。
 *
 * ④⑤ 会真实改写服务端状态，因此每个用例都在 finally 里**直写接口复原**，
 * 避免一次失败把配置留在脏状态污染后续轮次（实测踩过这个坑）。
 * 断言一律用可重试断言（expect(...).toHaveAttribute/toBe），
 * 不裸读 getAttribute——点击后 DOM 更新在微任务里，裸读会读到旧值。
 */
test.describe('9.3 跨刷新持久化', () => {
  test('刷新后会话保持：不回落锁屏，且停留在原路由', async ({ page }) => {
    await gotoPage(page, '/models')
    await expect(page.locator('.page-title h2')).toHaveText('模型')

    await page.reload()

    // 不应出现锁屏输入框
    await expect(page.locator('input[placeholder*="项目名"]')).toHaveCount(0)
    await expect(page.getByTestId('conn-state')).toBeVisible({ timeout: 25_000 })
    // 路由保持
    expect(new URL(page.url()).pathname).toBe('/models')
    await expect(page.locator('.page-title h2')).toHaveText('模型')
  })

  test('面板宽度按 localStorage 持久值恢复', async ({ page }) => {
    await unlock(page)

    // 写入一个与默认值(208)不同的宽度，验证恢复路径
    await page.evaluate(() => window.localStorage.setItem('fleet.nav.width', '320'))
    await page.reload()
    await expect(page.getByTestId('conn-state')).toBeVisible({ timeout: 25_000 })

    await expect
      .poll(async () => page.evaluate(() => {
        const el = document.querySelector('.panel.side-left') as HTMLElement | null
        return el ? Math.round(el.getBoundingClientRect().width) : 0
      }), { timeout: 15_000, intervals: [300] })
      .toBe(320)

    await page.evaluate(() => window.localStorage.removeItem('fleet.nav.width'))
  })

  test('调度模式为服务端状态：刷新后由服务端值水合（用例结束复原）', async ({ page }) => {
    await gotoPage(page, '/overview')
    const original = await readMode(page)
    const target = original === 'step' ? 'auto' : 'step'
    const targetLabel = target === 'step' ? '每步确认' : '自动执行'

    try {
      await page.getByRole('button', { name: targetLabel }).click()
      await expect(page.getByRole('button', { name: targetLabel })).toHaveClass(/on/, { timeout: 20_000 })

      // 服务端必须真实落位（不只是本地乐观更新）
      await expect.poll(async () => readMode(page), { timeout: 20_000 }).toBe(target)

      await page.reload()
      await expect(page.getByTestId('conn-state')).toBeVisible({ timeout: 25_000 })

      // 刷新后必须由服务端值水合，而不是回落默认 auto
      await expect(page.getByRole('button', { name: targetLabel })).toHaveClass(/on/, { timeout: 20_000 })
    } finally {
      await writeMode(page, original)
    }
  })

  test('可写开关为服务端状态：保存后刷新仍生效（并绕过 UI 直查接口核对）', async ({ page }) => {
    await gotoPage(page, '/notifications')
    const original = await readNotifyConfig(page)
    const testId = 'switch-on_task_start'

    try {
      const before = await switchState(page, testId)
      const target = !before

      await page.getByTestId(testId).click()
      await expect(page.getByTestId(testId)).toHaveAttribute('aria-checked', String(target), { timeout: 15_000 })

      await page.getByRole('button', { name: '保存提醒开关' }).click()
      await expect(page.getByText(/提醒开关已保存|部分开关未生效/)).toBeVisible({ timeout: 20_000 })

      // 绕过 UI 直查后端：真实落盘值必须与界面一致
      await expect.poll(async () => (await readNotifyConfig(page)).on_task_start, { timeout: 20_000 }).toBe(target)

      await page.reload()
      await expect(page.getByTestId('conn-state')).toBeVisible({ timeout: 25_000 })
      await expect(page.getByTestId(testId)).toHaveAttribute('aria-checked', String(target), { timeout: 20_000 })
    } finally {
      await writeNotifyConfig(page, original)
    }
  })

  test('只读开关取后端真实值：与 /api/notify/triggers 一致且不可写', async ({ page }) => {
    await gotoPage(page, '/notifications')

    const truth = await page.evaluate(async () => {
      const res = await fetch('/api/notify/triggers', { credentials: 'include' })
      const json = await res.json()
      return {
        escalated: json?.data?.task_escalated?.enabled,
        daily: json?.data?.daily_summary?.enabled,
      }
    })

    const escalated = page.getByTestId('switch-on_task_escalated')
    const daily = page.getByTestId('switch-daily_summary')

    // 值来自后端，不是本地兜底
    await expect(escalated).toHaveAttribute('aria-checked', String(Boolean(truth.escalated)))
    await expect(daily).toHaveAttribute('aria-checked', String(Boolean(truth.daily)))

    // 后端无写入端点 → 置灰只读
    await expect(escalated).toBeDisabled()
    await expect(daily).toBeDisabled()
  })

  test('零本地存储中继：操作开关后不产生任何 notify 相关 localStorage 键', async ({ page }) => {
    await gotoPage(page, '/notifications')
    const original = await readNotifyConfig(page)
    const testId = 'switch-on_task_end'

    try {
      const target = !(await switchState(page, testId))
      await page.getByTestId(testId).click()
      await expect(page.getByTestId(testId)).toHaveAttribute('aria-checked', String(target), { timeout: 15_000 })

      await page.getByRole('button', { name: '保存提醒开关' }).click()
      await expect(page.getByText(/提醒开关已保存|部分开关未生效/)).toBeVisible({ timeout: 20_000 })

      const residue = await page.evaluate(() =>
        Object.keys(window.localStorage).filter((key) => /notify/i.test(key)),
      )
      expect(residue).toEqual([])
      expect(await page.evaluate(() => window.localStorage.getItem('fleet.notifyExtra'))).toBeNull()
    } finally {
      await writeNotifyConfig(page, original)
    }
  })
})
