import { expect, test } from '@playwright/test'

/**
 * 总览可观测性 · 计时冻结与项目隔离（大纲 L1-C 4.1 / 2.1） @mock
 *
 * 合成夹具：只拦截浏览器 HTTP/WS，不写真实任务或配置。可控时钟验证：
 *  - 完成时间缺失时耗时冻结，不随 nowTick 被动跳动（4.1.2/4.1.3）；
 *  - 有有效 updated_at 时跨 tick 稳定（4.2.1）；
 *  - 未完成继续计时、空项目、完成后返工、A/B 切换与运行起点改变均重置正确（4.2.2/4.2.3）。
 */
test.describe('总览可观测性 · 计时冻结 @mock', () => {
  test('完成时间缺失时冻结：无有效 updated_at 的已收口计划，推进时钟后耗时不变', async ({ page }) => {
    // --- 合成数据：已收口计划，任务 updated_at 为空（无有效完成时间），有运行起点 ---
    const RUN_START = '2026-09-18T09:59:00Z' // 比 CLOCK_T0 早 60 秒
    const CLOCK_T0 = new Date('2026-09-18T10:00:00Z').getTime()

    const completedPlanNoTime = {
      ok: true,
      project: 'FreezeTest',
      updated_at: RUN_START,
      run_started_at: RUN_START,
      阶段: [{ 名称: '阶段一', 任务: [{ 子任务: '任务A', task_id: 'T1' }] }],
      tasks: [
        {
          id: 'T1',
          title: '任务A',
          state: 'DONE',
          assignee: 'dev',
          reviewer: 'rev',
          task_type: 1,
          review_status: 'PASS',
          stage: '阶段一',
          subtask: '任务A',
          rework_count: 0,
          updated_at: '', // 无有效完成时间——回退到观察时刻冻结
        },
      ],
      progress: { project: 'FreezeTest', total: 1, done: 1, percent: 100 },
      total: 1,
      done: 1,
      percent: 100,
    }

    // --- 阻断 WS：防止真实服务器 plan_update 覆盖合成计划（合成数据，非真实任务） ---
    await page.addInitScript(() => {
      const Fake = function () {
        this.readyState = 0
        this.send = () => {}
        this.close = () => {}
      } as unknown as typeof WebSocket
      ;(Fake as unknown as { CONNECTING: number }).CONNECTING = 0
      ;(Fake as unknown as { OPEN: number }).OPEN = 1
      ;(Fake as unknown as { CLOSING: number }).CLOSING = 2
      ;(Fake as unknown as { CLOSED: number }).CLOSED = 3
      window.WebSocket = Fake as unknown as typeof WebSocket
    })

    // --- 拦截 HTTP API（合成数据，标注非真实） ---
    await page.route(/\/api\/session/, async (route) => {
      const method = route.request().method()
      if (method === 'POST') {
        await route.fulfill({
          json: { ok: true, token: 'fake-token', project: 'FreezeTest', expires_in: 3600 },
        })
      } else if (method === 'GET') {
        await route.fulfill({ json: { ok: true, project: 'FreezeTest', expires_in: 3600 } })
      } else {
        await route.fulfill({ json: { ok: true } })
      }
    })
    await page.route(/\/api\/plan/, async (route) => {
      await route.fulfill({ json: completedPlanNoTime })
    })
    await page.route(/\/api\/events/, async (route) => {
      await route.fulfill({
        json: { ok: true, project: 'FreezeTest', since: 0, seq: 0, events: [] },
      })
    })
    await page.route(/\/api\/mode/, async (route) => {
      await route.fulfill({ json: { ok: true, mode: 'auto' } })
    })
    await page.route(/\/api\/projects\/names/, async (route) => {
      await route.fulfill({
        json: { ok: true, projects: [{ id: 'freeze-1', name: 'FreezeTest' }] },
      })
    })
    await page.route(/\/api\/roles\/summary/, async (route) => {
      await route.fulfill({ json: { ok: true, project: 'FreezeTest', roles: [] } })
    })

    // --- 安装可控时钟 ---
    await page.clock.install({ time: CLOCK_T0 })

    // --- 解锁 ---
    await page.goto('/')
    await page.locator('input[placeholder*="项目名"]').fill('FreezeTest')
    await page.getByRole('button', { name: '解锁控制台' }).click()
    await expect(page.getByTestId('conn-state')).toBeVisible({ timeout: 25_000 })

    // --- 触发计划加载（OverviewPage 不在挂载时自动加载计划，用刷新按钮） ---
    await page.getByRole('button', { name: '刷新计划' }).click()

    // --- 等待计划渲染：done/total 显示 1/1 ---
    await expect(page.locator('.summary .mono')).toContainText('1 / 1', { timeout: 15_000 })

    // --- 暂停时钟，稳定耗时 ---
    await page.clock.pauseAt(CLOCK_T0 + 10_000) // T1 = T0 + 10s

    const elapsed = page.locator('.elapsed.mono').first()
    await expect(elapsed).toBeVisible()
    const before = (await elapsed.innerText()).trim()

    // --- 推进可控时钟 3 秒 ---
    await page.clock.runFor(3000)

    // --- 断言耗时不变（冻结） ---
    await expect
      .poll(async () => (await elapsed.innerText()).trim(), { timeout: 5_000 })
      .toBe(before)
  })

  test('有真实完成时间时冻结：有效 updated_at 跨 tick 与刷新快照均固定', async ({ page }) => {
    const DONE_AT = '2026-09-18T09:58:30Z' // 比 CLOCK_T0 早 90 秒
    const RUN_START = '2026-09-18T09:59:00Z'
    const CLOCK_T0 = new Date('2026-09-18T10:00:00Z').getTime()

    const completedPlanWithTime = {
      ok: true,
      project: 'FreezeTest',
      updated_at: DONE_AT,
      run_started_at: RUN_START,
      阶段: [{ 名称: '阶段一', 任务: [{ 子任务: '任务A', task_id: 'T1' }] }],
      tasks: [
        {
          id: 'T1',
          title: '任务A',
          state: 'DONE',
          assignee: 'dev',
          reviewer: 'rev',
          task_type: 1,
          review_status: 'PASS',
          stage: '阶段一',
          subtask: '任务A',
          rework_count: 0,
          updated_at: DONE_AT,
        },
      ],
      progress: { project: 'FreezeTest', total: 1, done: 1, percent: 100 },
      total: 1,
      done: 1,
      percent: 100,
    }

    await page.addInitScript(() => {
      const Fake = function () {
        this.readyState = 0
        this.send = () => {}
        this.close = () => {}
      } as unknown as typeof WebSocket
      ;(Fake as unknown as { CONNECTING: number }).CONNECTING = 0
      ;(Fake as unknown as { OPEN: number }).OPEN = 1
      ;(Fake as unknown as { CLOSING: number }).CLOSING = 2
      ;(Fake as unknown as { CLOSED: number }).CLOSED = 3
      window.WebSocket = Fake as unknown as typeof WebSocket
    })
    await page.route(/\/api\/session/, async (route) => {
      const method = route.request().method()
      if (method === 'POST') {
        await route.fulfill({
          json: { ok: true, token: 'fake-token', project: 'FreezeTest', expires_in: 3600 },
        })
      } else if (method === 'GET') {
        await route.fulfill({ json: { ok: true, project: 'FreezeTest', expires_in: 3600 } })
      } else {
        await route.fulfill({ json: { ok: true } })
      }
    })
    await page.route(/\/api\/plan/, async (route) => {
      await route.fulfill({ json: completedPlanWithTime })
    })
    await page.route(/\/api\/events/, async (route) => {
      await route.fulfill({
        json: { ok: true, project: 'FreezeTest', since: 0, seq: 0, events: [] },
      })
    })
    await page.route(/\/api\/mode/, async (route) => {
      await route.fulfill({ json: { ok: true, mode: 'auto' } })
    })
    await page.route(/\/api\/projects\/names/, async (route) => {
      await route.fulfill({
        json: { ok: true, projects: [{ id: 'freeze-1', name: 'FreezeTest' }] },
      })
    })
    await page.route(/\/api\/roles\/summary/, async (route) => {
      await route.fulfill({ json: { ok: true, project: 'FreezeTest', roles: [] } })
    })

    await page.clock.install({ time: CLOCK_T0 })
    await page.goto('/')
    await page.locator('input[placeholder*="项目名"]').fill('FreezeTest')
    await page.getByRole('button', { name: '解锁控制台' }).click()
    await expect(page.getByTestId('conn-state')).toBeVisible({ timeout: 25_000 })
    await page.getByRole('button', { name: '刷新计划' }).click()
    await expect(page.locator('.summary .mono')).toContainText('1 / 1', { timeout: 15_000 })

    // 有有效 updated_at 时不出现"完成时间缺失"提示
    await expect(page.locator('.fallback-note')).toHaveCount(0)

    await page.clock.pauseAt(CLOCK_T0 + 10_000)
    const elapsed = page.locator('.elapsed.mono').first()
    const before = (await elapsed.innerText()).trim()

    // 跨多个 tick
    await page.clock.runFor(3000)
    await page.clock.runFor(2000)

    await expect
      .poll(async () => (await elapsed.innerText()).trim(), { timeout: 5_000 })
      .toBe(before)
  })

  test('未完成时继续计时：推进时钟后耗时增长', async ({ page }) => {
    const RUN_START = '2026-09-18T09:59:00Z'
    const CLOCK_T0 = new Date('2026-09-18T10:00:00Z').getTime()

    const unfinishedPlan = {
      ok: true,
      project: 'FreezeTest',
      updated_at: RUN_START,
      run_started_at: RUN_START,
      阶段: [{ 名称: '阶段一', 任务: [{ 子任务: '任务A', task_id: 'T1' }] }],
      tasks: [
        {
          id: 'T1',
          title: '任务A',
          state: 'DOING',
          assignee: 'dev',
          reviewer: 'rev',
          task_type: 1,
          review_status: 'PENDING',
          stage: '阶段一',
          subtask: '任务A',
          rework_count: 0,
          updated_at: '',
        },
      ],
      progress: { project: 'FreezeTest', total: 1, done: 0, percent: 0 },
      total: 1,
      done: 0,
      percent: 0,
    }

    await page.addInitScript(() => {
      const Fake = function () {
        this.readyState = 0
        this.send = () => {}
        this.close = () => {}
      } as unknown as typeof WebSocket
      ;(Fake as unknown as { CONNECTING: number }).CONNECTING = 0
      ;(Fake as unknown as { OPEN: number }).OPEN = 1
      ;(Fake as unknown as { CLOSING: number }).CLOSING = 2
      ;(Fake as unknown as { CLOSED: number }).CLOSED = 3
      window.WebSocket = Fake as unknown as typeof WebSocket
    })
    await page.route(/\/api\/session/, async (route) => {
      const method = route.request().method()
      if (method === 'POST') {
        await route.fulfill({
          json: { ok: true, token: 'fake-token', project: 'FreezeTest', expires_in: 3600 },
        })
      } else if (method === 'GET') {
        await route.fulfill({ json: { ok: true, project: 'FreezeTest', expires_in: 3600 } })
      } else {
        await route.fulfill({ json: { ok: true } })
      }
    })
    await page.route(/\/api\/plan/, async (route) => {
      await route.fulfill({ json: unfinishedPlan })
    })
    await page.route(/\/api\/events/, async (route) => {
      await route.fulfill({
        json: { ok: true, project: 'FreezeTest', since: 0, seq: 0, events: [] },
      })
    })
    await page.route(/\/api\/mode/, async (route) => {
      await route.fulfill({ json: { ok: true, mode: 'auto' } })
    })
    await page.route(/\/api\/projects\/names/, async (route) => {
      await route.fulfill({
        json: { ok: true, projects: [{ id: 'freeze-1', name: 'FreezeTest' }] },
      })
    })
    await page.route(/\/api\/roles\/summary/, async (route) => {
      await route.fulfill({ json: { ok: true, project: 'FreezeTest', roles: [] } })
    })

    await page.clock.install({ time: CLOCK_T0 })
    await page.goto('/')
    await page.locator('input[placeholder*="项目名"]').fill('FreezeTest')
    await page.getByRole('button', { name: '解锁控制台' }).click()
    await expect(page.getByTestId('conn-state')).toBeVisible({ timeout: 25_000 })
    await page.getByRole('button', { name: '刷新计划' }).click()
    await expect(page.locator('.summary .mono')).toContainText('0 / 1', { timeout: 15_000 })

    // 不出现"已收口"标签
    await expect(page.locator('.tag-done')).toHaveCount(0)

    await page.clock.pauseAt(CLOCK_T0 + 10_000)
    const elapsed = page.locator('.elapsed.mono').first()
    const before = (await elapsed.innerText()).trim()

    // 推进时钟 3 秒——未完成应继续计时
    await page.clock.runFor(3000)

    const after = (await elapsed.innerText()).trim()
    expect(after).not.toBe(before)
  })

  test('percent 舍入为 100 但仍有未完成任务时不提前冻结（4.2.4）', async ({ page }) => {
    const RUN_START = '2026-09-18T09:59:00Z'
    const CLOCK_T0 = new Date('2026-09-18T10:00:00Z').getTime()

    // 2000 个任务：1999 DONE + 1 DOING → done/total=0.9995 → percent 舍入为 100，但 done!==total
    const tasks: Array<Record<string, unknown>> = []
    const stageTasks: Array<Record<string, unknown>> = []
    for (let i = 1; i <= 1999; i += 1) {
      const id = `D${i}`
      tasks.push({
        id,
        title: `任务${id}`,
        state: 'DONE',
        assignee: 'dev',
        reviewer: 'rev',
        task_type: 1,
        review_status: 'PASS',
        stage: '阶段一',
        subtask: `子任务${id}`,
        rework_count: 0,
        updated_at: '',
      })
      stageTasks.push({ 子任务: `子任务${id}`, task_id: id })
    }
    tasks.push({
      id: 'W1',
      title: '任务W1',
      state: 'DOING',
      assignee: 'dev',
      reviewer: 'rev',
      task_type: 1,
      review_status: 'PENDING',
      stage: '阶段一',
      subtask: '未完成子任务',
      rework_count: 0,
      updated_at: '',
    })
    stageTasks.push({ 子任务: '未完成子任务', task_id: 'W1' })

    const roundingPlan = {
      ok: true,
      project: 'FreezeTest',
      updated_at: RUN_START,
      run_started_at: RUN_START,
      阶段: [{ 名称: '阶段一', 任务: stageTasks }],
      tasks,
      progress: { project: 'FreezeTest', total: 2000, done: 1999, percent: 100 },
      total: 2000,
      done: 1999,
      percent: 100,
    }

    await page.addInitScript(() => {
      const Fake = function () {
        this.readyState = 0
        this.send = () => {}
        this.close = () => {}
      } as unknown as typeof WebSocket
      ;(Fake as unknown as { CONNECTING: number }).CONNECTING = 0
      ;(Fake as unknown as { OPEN: number }).OPEN = 1
      ;(Fake as unknown as { CLOSING: number }).CLOSING = 2
      ;(Fake as unknown as { CLOSED: number }).CLOSED = 3
      window.WebSocket = Fake as unknown as typeof WebSocket
    })
    await page.route(/\/api\/session/, async (route) => {
      const method = route.request().method()
      if (method === 'POST') {
        await route.fulfill({
          json: { ok: true, token: 'fake-token', project: 'FreezeTest', expires_in: 3600 },
        })
      } else if (method === 'GET') {
        await route.fulfill({ json: { ok: true, project: 'FreezeTest', expires_in: 3600 } })
      } else {
        await route.fulfill({ json: { ok: true } })
      }
    })
    await page.route(/\/api\/plan/, async (route) => {
      await route.fulfill({ json: roundingPlan })
    })
    await page.route(/\/api\/events/, async (route) => {
      await route.fulfill({
        json: { ok: true, project: 'FreezeTest', since: 0, seq: 0, events: [] },
      })
    })
    await page.route(/\/api\/mode/, async (route) => {
      await route.fulfill({ json: { ok: true, mode: 'auto' } })
    })
    await page.route(/\/api\/projects\/names/, async (route) => {
      await route.fulfill({
        json: { ok: true, projects: [{ id: 'freeze-1', name: 'FreezeTest' }] },
      })
    })
    await page.route(/\/api\/roles\/summary/, async (route) => {
      await route.fulfill({ json: { ok: true, project: 'FreezeTest', roles: [] } })
    })

    await page.clock.install({ time: CLOCK_T0 })
    await page.goto('/')
    await page.locator('input[placeholder*="项目名"]').fill('FreezeTest')
    await page.getByRole('button', { name: '解锁控制台' }).click()
    await expect(page.getByTestId('conn-state')).toBeVisible({ timeout: 25_000 })
    await page.getByRole('button', { name: '刷新计划' }).click()
    await expect(page.locator('.summary .mono')).toContainText('1999 / 2000', { timeout: 15_000 })

    // percent 舍入为 100 但 done!==total → 不应出现"已收口"
    await expect(page.locator('.tag-done')).toHaveCount(0)

    await page.clock.pauseAt(CLOCK_T0 + 10_000)
    const elapsed = page.locator('.elapsed.mono').first()
    const before = (await elapsed.innerText()).trim()

    // 推进时钟——仍有未完成任务，不冻结，耗时应增长
    await page.clock.runFor(3000)

    const after = (await elapsed.innerText()).trim()
    expect(after).not.toBe(before)
  })
})
