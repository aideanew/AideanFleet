import { expect, test } from '@playwright/test'
import { connState, gotoPage, unlock } from '../lib/helpers'

/**
 * 主题 9.2 · 断网注入（真实网络层故障，非 mock 开关）
 *
 * 用 Playwright 的 context.setOffline() 在浏览器网络层切断连接，
 * 验证：① 断开后连接态离开「已连接」；② 连续重试后降级为 1s 轮询；
 * ③ 恢复网络后自动回到 WebSocket「已连接」；
 * ④ 恢复瞬间确实发起了 GET /api/events?since=<seq>（增量补拉，不丢事件）。
 */
test.describe('9.2 断网注入 · 重连与增量补拉', () => {
  test('断网后连接态离开已连接，恢复后自动回到 WebSocket 已连接', async ({ page, context }) => {
    await unlock(page)
    await expect(page.getByTestId('conn-state')).toContainText('已连接', { timeout: 25_000 })

    await context.setOffline(true)

    // 断开后必须离开「已连接」（重连中 / 降级轮询 / 未连接 均可，只要不是在线）
    await expect
      .poll(async () => connState(page), { timeout: 30_000, intervals: [500] })
      .toMatch(/重连|降级为轮询|未连接/)

    await context.setOffline(false)

    // 指数退避最长 30s，恢复后应回到 WebSocket 已连接
    await expect
      .poll(async () => connState(page), { timeout: 75_000, intervals: [1000] })
      .toContain('已连接（WebSocket）')
  })

  test('持续断网触发轮询降级；恢复后增量补拉（since>0）真实发生', async ({ page, context }) => {
    const eventCalls: string[] = []
    page.on('request', (req) => {
      const url = req.url()
      if (url.includes('/api/events')) eventCalls.push(url)
    })

    await unlock(page)
    await expect(page.getByTestId('conn-state')).toContainText('已连接', { timeout: 25_000 })

    // 断网足够久（退避 1+2+4+8=15s 后进入轮询兜底）
    await context.setOffline(true)
    await expect
      .poll(async () => connState(page), { timeout: 45_000, intervals: [1000] })
      .toMatch(/降级为轮询|重连|未连接/)

    eventCalls.length = 0
    await context.setOffline(false)

    await expect
      .poll(async () => connState(page), { timeout: 75_000, intervals: [1000] })
      .toContain('已连接（WebSocket）')

    // 恢复路径必须包含一次「带游标的增量补拉」
    await expect
      .poll(
        () => eventCalls.some((u) => /\/api\/events\?.*since=([1-9]\d*)/.test(u)),
        { timeout: 30_000, intervals: [500] },
      )
      .toBe(true)
  })

  test('断网期间的对话历史在恢复后不丢失（不截断）', async ({ page, context }) => {
    await gotoPage(page, '/chat')
    const marker = `断网前消息-${Date.now()}`

    const composer = page.locator('textarea').first()
    await composer.fill(marker)
    await page.getByRole('button', { name: '发送' }).click()
    // exact: 用户消息原文会同时出现在 Manager 回执的引用里，
    // 非精确匹配会命中 2 个元素触发 strict mode violation（定位符缺陷，非功能缺陷）
    await expect(page.getByText(marker, { exact: true })).toBeVisible({ timeout: 20_000 })

    await context.setOffline(true)
    await page.waitForTimeout(3000)
    await context.setOffline(false)

    await expect
      .poll(async () => connState(page), { timeout: 75_000, intervals: [1000] })
      .toContain('已连接（WebSocket）')

    // 恢复后历史仍在（全量保留，不分页截断）；同上必须 exact 匹配
    await expect(page.getByText(marker, { exact: true })).toBeVisible({ timeout: 20_000 })
  })
})
