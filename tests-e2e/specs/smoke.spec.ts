import { expect, test } from '@playwright/test'
import { ALL_PAGES, CORE_PAGES, EXTRA_PAGES, PAGES, gotoPage, unlock } from '../lib/helpers'

/**
 * 主套件 · 门禁 / 七页回归 / UI-02 四项缺陷回归
 * （不含 @mock 用例；mock 专属用例由 --grep-invert @mock 排除，另轮单独跑）
 */

test.describe('门禁与外壳', () => {
  test('未解锁时显示锁屏，解锁后进入控制台外壳', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('.lock-title, h1')).toContainText('AideanFleet')
    await expect(page.locator('input[placeholder*="项目名"]')).toBeVisible()
    // 锁屏下不渲染外壳
    await expect(page.locator('.topbar')).toHaveCount(0)

    await unlock(page)
    await expect(page.locator('.topbar')).toBeVisible()
    await expect(page.getByTestId('conn-state')).toContainText('已连接')
  })

  test('侧栏前 7 项冻结顺序不变，治理页仅追加在末尾', async ({ page }) => {
    await unlock(page)
    await expect(page.locator('.nav .item')).toHaveCount(ALL_PAGES.length)
    for (let i = 0; i < CORE_PAGES.length; i += 1) {
      await expect(page.locator('.nav .item').nth(i).locator('.text b')).toHaveText(CORE_PAGES[i].title)
    }
    // 追加项必须出现在冻结 7 项之后，且顺序固定
    for (let i = 0; i < EXTRA_PAGES.length; i += 1) {
      await expect(page.locator('.nav .item').nth(CORE_PAGES.length + i).locator('.text b')).toHaveText(
        EXTRA_PAGES[i].title,
      )
    }
  })
})

test.describe('七页回归', () => {
  for (const item of PAGES) {
    test(`${item.title} 页可深链直达且标题正确`, async ({ page }) => {
      await gotoPage(page, item.path)
      await expect(page.locator('.page-title h2')).toHaveText(item.title)
      // 无渲染异常：页面主体存在且非空
      expect((await page.locator('.page').innerText()).length).toBeGreaterThan(10)
    })
  }
})

test.describe('治理页回归（UI-03R 追加页）', () => {
  for (const item of EXTRA_PAGES) {
    test(`${item.title} 页可深链直达且标题正确`, async ({ page }) => {
      await gotoPage(page, item.path)
      await expect(page.locator('.page-title h2')).toHaveText(item.title)
      // 数据源标注必须显式可见（api 或 contract-mock，二者之一）
      await expect(page.getByTestId('gov-source-badge')).toBeVisible({ timeout: 15_000 })
      await expect(page.getByTestId('gov-source-badge')).toContainText(/真实 API|后端未就绪/)
    })
  }

  test('审批中心：表格或空态二选一渲染，且不出现未定义字样', async ({ page }) => {
    await gotoPage(page, '/approvals')
    const table = page.getByTestId('approvals-table')
    const empty = page.getByTestId('approvals-empty')
    await expect(table.or(empty)).toBeVisible({ timeout: 15_000 })
    expect(await page.locator('.page').innerText()).not.toContain('undefined')
  })

  test('成本面板：三级预算与用量总览渲染，进度百分比在 0–100 区间', async ({ page }) => {
    await gotoPage(page, '/cost')
    await expect(page.getByTestId('usage-totals')).toBeVisible()
    const cards = page.getByTestId('budget-card')
    await expect(cards.first()).toBeVisible()
    const count = await cards.count()
    expect(count).toBeGreaterThanOrEqual(1)
    for (let i = 0; i < count; i += 1) {
      const text = await cards.nth(i).innerText()
      const match = text.match(/(\d+(?:\.\d+)?)%/)
      expect(match, `预算卡片缺少百分比：${text}`).toBeTruthy()
      const pct = Number(match![1])
      expect(pct).toBeGreaterThanOrEqual(0)
      expect(pct).toBeLessThanOrEqual(100)
    }
  })
})

test.describe('UI-02 四项缺陷回归', () => {
  test('#1 顶栏右侧顺序为 锁定 → 设置，且无底部信息栏', async ({ page }) => {
    await unlock(page)
    const buttons = page.locator('.topbar .right button')
    await expect(buttons).toHaveCount(2)
    await expect(buttons.nth(0)).toContainText('锁定')
    await expect(buttons.nth(1)).toContainText('设置')

    // 外壳的直接子级只有 顶栏 + 主体（没有 footer 底栏节点）
    await expect(page.locator('.shell > footer, .shell > .footer, .app-footer')).toHaveCount(0)

    // 设置以独立抽屉打开
    await page.getByRole('button', { name: '设置' }).click()
    await expect(page.locator('.drawer')).toBeVisible()
  })

  test('#2 进度环在未执行时显示空态「项目尚未开始执行」', async ({ page }) => {
    await gotoPage(page, '/overview')
    // 真实后端当前 plan 为空 → 未开始
    const started = await page.evaluate(async () => {
      const r = await fetch('/api/plan?project=AideanFleet', { credentials: 'include' })
      const j = await r.json()
      return (j.tasks || []).some((t: { state?: string }) => t.state && t.state !== 'DRAFT')
    })
    if (!started) {
      await expect(page.getByTestId('rail-empty')).toContainText('项目尚未开始执行')
      await expect(page.getByTestId('prep-list').locator('li')).toHaveCount(10)
    }
  })

  test('#4 侧栏与右轨均可折叠（三态解耦：折叠不改写用户拖拽宽度）', async ({ page }) => {
    await unlock(page)
    const nav = page.locator('.panel.side-left')
    const rail = page.locator('.panel.side-right')

    await expect(nav).not.toHaveClass(/collapsed/)
    await page.locator('.collapse').click()
    await expect(nav).toHaveClass(/collapsed/)

    await page.locator('.handle-right').dblclick()
    await expect(rail).toHaveClass(/collapsed/)

    // 展开恢复：nav 展开后宽度应回到持久化/默认值（而非 0 或折叠宽度）
    await page.locator('.collapse').click()
    await expect(nav).not.toHaveClass(/collapsed/)
    await expect
      .poll(async () => page.evaluate(() => {
        const el = document.querySelector('.panel.side-left') as HTMLElement | null
        return el ? Math.round(el.getBoundingClientRect().width) : 0
      }), { timeout: 10_000, intervals: [300] })
      .toBeGreaterThan(100)
  })
})
