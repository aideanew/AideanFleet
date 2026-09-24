import { expect, test } from '@playwright/test'
import { gotoPage, saveShot, unlock } from '../lib/helpers'

/**
 * 证据采集套件 · UI-03R
 *
 * 产出落到 reports/ui03r/shots/*.png，供 UI-03R-evidence.md 引用。
 * 之所以单独成 spec：config 关闭了 Playwright 的自动截图（会触发本机批量删除护栏），
 * 需要把「留证」与「断言」解耦，证人要可复现、路径要稳定。
 */
test.describe('证据采集', () => {
  test('总览页：进度环空态 + 10 步准备清单', async ({ page }) => {
    await unlock(page)
    await expect(page.getByTestId('prep-list').locator('li')).toHaveCount(10)
    await saveShot(page, '01-overview')
  })

  test('对话页：stream_chunk 增量气泡与来源标注', async ({ page }) => {
    await gotoPage(page, '/chat')
    await page.getByTestId('inject-stream').click()
    await expect(page.getByTestId('stream-live')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByTestId('stream-text')).not.toBeEmpty()
    await saveShot(page, '02-chat-stream')
  })

  test('消息页：6 个开关（4 可写 + 2 只读置灰）与触发条件表', async ({ page }) => {
    await gotoPage(page, '/notifications')
    const switches = page.getByTestId('switch-list').locator('.switch')
    await expect(switches).toHaveCount(6)
    // 后两个必须置灰（后端无写入端点）
    await expect(page.getByTestId('switch-on_task_escalated')).toBeDisabled()
    await expect(page.getByTestId('switch-daily_summary')).toBeDisabled()
    await expect(page.getByTestId('triggers-table')).toBeVisible()
    await saveShot(page, '03-notifications')
  })

  test('审批中心：数据源标注 + 审批表', async ({ page }) => {
    await gotoPage(page, '/approvals')
    await expect(page.getByTestId('gov-source-badge')).toBeVisible({ timeout: 15_000 })
    await saveShot(page, '04-approvals')
  })

  test('成本面板：三级预算 + 用量总览 + 按日表', async ({ page }) => {
    await gotoPage(page, '/cost')
    await expect(page.getByTestId('usage-totals')).toBeVisible({ timeout: 15_000 })
    await saveShot(page, '05-cost')
  })

  test('侧栏：冻结 7 项 + 追加治理入口与历史页', async ({ page }) => {
    await unlock(page)
    await expect(page.locator('.nav .item')).toHaveCount(10)
    await saveShot(page, '06-sidenav')
  })

  test('模型页：api_key 掩码回显（零明文）', async ({ page }) => {
    await gotoPage(page, '/models')
    await expect(page.locator('.page-title h2')).toHaveText('模型')
    await saveShot(page, '07-models-masked')
  })
})
