import { expect, test } from '@playwright/test'
import { gotoPage } from '../lib/helpers'

/**
 * 主题 9.6 · stream_chunk 增量流
 *
 * 生产方现状：`fleet/console/server.py` 未广播 `stream_chunk`（全部 broadcast 调用已 grep 确认），
 * 即 INT-04 的 stream_chunk 生产方仍缺位 → 按工作包要求 **mock 先行**：
 *   · 客户端按契约形状完整实现消费逻辑（useWebSocket.handleMessage → chat.appendChunk）；
 *   · 用 `window.__fleetInjectStream` / 页面按钮走**同一条 handleMessage 路径**注入验证；
 *   · 页面如实标注来源为「注入（后端尚未产出，INT-04 REWORK）」，不冒充服务端推送。
 * 角色A 补上生产方后，本套件无需改动即可继续通过。
 */

declare global {
  interface Window {
    __fleetInjectStream?: (deltas: string[], done?: boolean) => number
  }
}

test.describe('9.6 stream_chunk 增量渲染', () => {
  test('注入增量帧：实时气泡逐帧累积文本，并如实标注来源与帧数', async ({ page }) => {
    await gotoPage(page, '/chat')

    await page.getByTestId('inject-stream').click()

    const live = page.getByTestId('stream-live')
    await expect(live).toBeVisible({ timeout: 15_000 })

    // 5 帧必须按序拼接成完整文本
    await expect(page.getByTestId('stream-text')).toHaveText('【Manager·流式回执】增量帧已到达。')

    const meta = page.getByTestId('stream-meta')
    await expect(meta).toContainText('注入')
    await expect(meta).toContainText('已收 5 帧')
    await expect(meta).toContainText('INT-04 REWORK')
  })

  test('done=false 时持续累积且保持活动态；done=true 后停止活动态但保留文本', async ({ page }) => {
    await gotoPage(page, '/chat')
    await expect(page.getByTestId('conn-state')).toBeVisible({ timeout: 25_000 })

    const hook = await page.evaluate(() => typeof window.__fleetInjectStream)
    expect(hook).toBe('function')

    // 未结束：累积 + 活动态（光标闪烁）
    await page.evaluate(() => window.__fleetInjectStream?.(['第一段', '第二段'], false))
    await expect(page.getByTestId('stream-text')).toHaveText('第一段第二段')
    await expect(page.locator('.live .bubble')).toHaveClass(/streaming/)

    // 结束帧：文本继续累积，活动态结束
    await page.evaluate(() => window.__fleetInjectStream?.(['第三段'], true))
    await expect(page.getByTestId('stream-text')).toHaveText('第一段第二段第三段')
    await expect(page.locator('.live .bubble')).not.toHaveClass(/streaming/)

    // 累积帧数应为 3
    await expect(page.getByTestId('stream-meta')).toContainText('已收 3 帧')
  })

  test('chat_reply 落库后清空增量缓冲，避免与历史气泡重复', async ({ page }) => {
    await gotoPage(page, '/chat')

    // 先注入一帧，让实时气泡出现
    await page.getByTestId('inject-stream').click()
    await expect(page.getByTestId('stream-live')).toBeVisible({ timeout: 15_000 })

    /**
     * 为什么走 REST 而不是点「发送」：
     * 后端两条 chat 路径不对称（实测 fleet/console/server.py）——
     *   · WS  `{type:"chat"}` → _handle_ws_chat 只写用户 chat 行，**不产生 chat_reply**；
     *   · REST POST /api/chat  → 同时写用户行 + Manager chat_reply 行（L480-483），
     *     随后由 _event_pump（1s/拍）广播为 chat_message。
     * 因此要验证「chat_reply 到达即清缓冲」这条分支，必须走 REST 才能拿到真实回执。
     * 该不对称已作为后端缺口记入 UI-03R 报告 §8。
     */
    const marker = `stream-竞态校验-${Date.now()}`
    await page.evaluate(async (message: string) => {
      await fetch('/api/chat', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project: 'AideanFleet', message }),
      })
    }, marker)

    // 用户消息经事件泵回到页面
    await expect(page.getByText(marker, { exact: true })).toBeVisible({ timeout: 25_000 })

    // 真实 chat_reply 事件落库后，增量缓冲必须被清空
    await expect(page.getByTestId('stream-live')).toHaveCount(0, { timeout: 25_000 })
    await expect(page.getByText(/Manager·回执/).last()).toBeVisible({ timeout: 25_000 })
  })
})
