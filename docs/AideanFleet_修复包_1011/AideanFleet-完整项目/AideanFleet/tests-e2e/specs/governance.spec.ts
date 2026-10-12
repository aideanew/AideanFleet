import { expect, test } from '@playwright/test'
import { gotoPage } from '../lib/helpers'

/**
 * 主题 9.5 · 治理可视化（审批中心 + 成本面板）
 *
 * 前提事实演进：
 *   · 2026-09-15 UI-03R 初版实测 GET /api/approvals、/api/usage/total、/api/usage/by_date、/api/budget
 *     全部 404，本套件验证「契约兜底数据源 + 真实交互链路」；
 *   · 角色A 挂载治理 HTTP 面后（server.py /api/approvals*、/api/usage/*、/api/budget），
 *     同一套断言在真实数据上运行：source 变为 api，页面不再显示「后端未就绪」。
 * 不变语义：审批操作必须真实改变状态并联动统计；成本面板派生数值与限值数学自洽。
 */

async function parseBudgetCard(text: string): Promise<{ used: number; limit: number; pct: number }> {
  const numbers = text.match(/([\d,]+)\s*\/\s*([\d,]+)/)
  const pctMatch = text.match(/(\d+(?:\.\d+)?)%/)
  return {
    used: Number((numbers?.[1] ?? '0').replace(/,/g, '')),
    limit: Number((numbers?.[2] ?? '0').replace(/,/g, '')),
    pct: Number(pctMatch?.[1] ?? '0'),
  }
}

test.describe('9.5 审批中心', () => {
  test('数据源如实标注：404 时必须显示「后端未就绪」而非伪装已对接', async ({ page }) => {
    const probes: Record<string, number> = {}
    page.on('response', (res) => {
      const url = res.url()
      for (const path of ['/api/approvals', '/api/usage/total', '/api/budget']) {
        if (url.includes(path)) probes[path] = res.status()
      }
    })

    await gotoPage(page, '/approvals')
    const badge = page.getByTestId('gov-source-badge')
    await expect(badge).toBeVisible({ timeout: 15_000 })

    const anyProbed = Object.keys(probes).length > 0
    if (anyProbed && probes['/api/approvals'] === 404) {
      await expect(badge).toContainText('后端未就绪')
      await expect(page.locator('.page')).toContainText('404')
    } else {
      await expect(badge).toContainText(/真实 API|后端未就绪/)
    }
  })

  test('审批通过：状态由待审批变为已通过，统计联动', async ({ page }) => {
    await gotoPage(page, '/approvals')

    const allRows = page.getByTestId('approval-row')
    await expect(page.getByTestId('approvals-table').or(page.getByTestId('approvals-empty'))).toBeVisible({
      timeout: 15_000,
    })

    const pendingRows = allRows.filter({ has: page.getByTestId('approve-btn') })
    const pendingBefore = await pendingRows.count()
    test.skip(pendingBefore === 0, '当前无待审批记录（governance.db pending 列表为空则跳过本用例）')

    const statSel = page.locator('.stat', { hasText: '待审批' }).first().locator('b')
    const statBefore = Number((await statSel.innerText()).trim())

    // 先记下目标行的 approval_id —— 批准后它不再含「通过」按钮，
    // 若继续用 filter({has: approve-btn}) 定位，会漂到下一行，断言就假失败。
    const firstRow = pendingRows.first()
    const approvalId = (await firstRow.locator('.cell-mono').first().innerText()).trim()
    expect(approvalId).toMatch(/^appr-/)

    await firstRow.getByTestId('approve-btn').click()

    // 统计必须真实 -1
    await expect
      .poll(async () => Number((await statSel.innerText()).trim()), { timeout: 15_000 })
      .toBe(statBefore - 1)

    // 按 approval_id 精确定位该行，断言状态已落为「已通过」
    const targetRow = page.getByTestId('approval-row').filter({ hasText: approvalId })
    await expect(targetRow).toHaveCount(1)
    await expect(targetRow.locator('.badge').first()).toContainText('已通过')
  })

  test('状态筛选可用：待审批筛选下每一行都是待审批', async ({ page }) => {
    await gotoPage(page, '/approvals')
    await expect(page.getByTestId('approvals-table').or(page.getByTestId('approvals-empty'))).toBeVisible({
      timeout: 15_000,
    })

    const pendingFilter = page.locator('.seg button', { hasText: '待审批' })
    await pendingFilter.click()
    await expect(pendingFilter).toHaveClass(/on/)

    const rows = page.getByTestId('approval-row')
    const count = await rows.count()
    // 逐行断言：必须按行取 badge，不能先 .first() 再 .nth(i)（那会把集合塌缩成单元素导致越界）
    for (let i = 0; i < count; i += 1) {
      await expect(rows.nth(i).locator('.badge').first()).toContainText('待审批')
    }
  })
})

test.describe('9.5 成本面板', () => {
  test('三级预算卡片：剩余 = 限值 - 已用，百分比数学自洽', async ({ page }) => {
    await gotoPage(page, '/cost')
    const cards = page.getByTestId('budget-card')
    await expect(cards.first()).toBeVisible({ timeout: 15_000 })

    const count = await cards.count()
    expect(count).toBeGreaterThanOrEqual(1)

    for (let i = 0; i < count; i += 1) {
      const text = await cards.nth(i).innerText()
      const { used, limit, pct } = await parseBudgetCard(text)
      expect(limit).toBeGreaterThan(0)

      // 百分比自洽（允许 0.2 的四舍五入误差）
      const expected = Math.round((used / limit) * 1000) / 10
      expect(Math.abs(pct - expected)).toBeLessThanOrEqual(0.2)

      // 剩余与我方算法一致（超限时为 0，不出现负数）
      const remaining = Math.max(0, limit - used)
      expect(text).toContain(new Intl.NumberFormat('en-US').format(remaining))
    }
  })

  test('用量总览等于按日用量之和（同口径聚合）', async ({ page }) => {
    await gotoPage(page, '/cost')
    await expect(page.getByTestId('usage-totals')).toBeVisible({ timeout: 15_000 })

    const totals = await page.getByTestId('usage-totals').innerText()
    const totalTokens = Number((totals.match(/([\d,]+)\s*总 tokens/) ?? ['', '0'])[1].replace(/,/g, ''))
    const callCount = Number((totals.match(/([\d,]+)\s*调用次数/) ?? ['', '0'])[1].replace(/,/g, ''))

    const table = page.getByTestId('usage-by-date')
    if ((await table.count()) === 0) {
      expect(totalTokens).toBe(0)
      return
    }

    const rows = await table.locator('tbody tr').all()
    let sumTokens = 0
    let sumCalls = 0
    for (const row of rows) {
      const cells = await row.locator('td').allInnerTexts()
      // 列序：日期 | prompt | completion | 合计 | 调用次数 | 缓存命中 | 未知用量
      sumTokens += Number((cells[3] ?? '0').replace(/,/g, ''))
      sumCalls += Number((cells[4] ?? '0').replace(/,/g, ''))
    }

    expect(sumTokens).toBe(totalTokens)
    expect(sumCalls).toBe(callCount)
  })

  test('超限/预警级别有明确视觉标注，且不出现 undefined', async ({ page }) => {
    await gotoPage(page, '/cost')
    const cards = page.getByTestId('budget-card')
    await expect(cards.first()).toBeVisible({ timeout: 15_000 })

    const count = await cards.count()
    for (let i = 0; i < count; i += 1) {
      await expect(cards.nth(i).locator('.badge')).toContainText(/正常|接近上限|已超限/)
    }
    expect(await page.locator('.page').innerText()).not.toContain('undefined')
  })
})
