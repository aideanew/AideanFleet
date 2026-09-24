import { expect, test } from '@playwright/test'

/**
 * 项目切换不串台（R7 重写：功能性 Fake WS）
 *
 * 旧版用永不 onopen 的 Fake WebSocket，掩盖了两个真实缺陷：
 *  - 切换项目后 WS 永不重建（断链回归无人察觉）；
 *  - 下拉 option value 用 name 而绑定值用 id（回显失效）。
 * 现在的 FakeWS 会自动 onopen、可注入下行消息，把上述场景固化为常驻回归。
 */

const planA = {
  ok: true,
  project: 'A',
  updated_at: '2026-09-18T10:00:00Z',
  run_started_at: '2026-09-18T09:00:00Z',
  阶段: [{ 名称: '阶段A', 任务: [{ 子任务: '任务A', task_id: 'TA' }] }],
  tasks: [{ id: 'TA', title: '任务A', state: 'DONE', updated_at: '2026-09-18T10:00:00Z', stage: '阶段A', subtask: '任务A' }],
  total: 1, done: 1, percent: 100,
}
const planA2 = { ...planA, updated_at: '2026-09-18T10:02:00Z' }
const planB = {
  ok: true,
  project: 'B',
  updated_at: '2026-09-18T10:05:00Z',
  run_started_at: '2026-09-18T09:10:00Z',
  阶段: [{ 名称: '阶段B', 任务: [{ 子任务: '任务B', task_id: 'TB' }] }],
  tasks: [{ id: 'TB', title: '任务B', state: 'DOING', updated_at: '', stage: '阶段B', subtask: '任务B' }],
  total: 2, done: 0, percent: 0,
}

/** 功能性 Fake WS：自动 onopen；window.__fakeSockets 暴露实例，__fakeSendToLast 注入下行帧 */
async function installFakeWs(page: import('@playwright/test').Page): Promise<void> {
  await page.addInitScript(() => {
    const sockets: unknown[] = []
    class FakeWS {
      static CONNECTING = 0
      static OPEN = 1
      static CLOSING = 2
      static CLOSED = 3
      url: string
      readyState = 0
      onopen: (() => void) | null = null
      onclose: (() => void) | null = null
      onmessage: ((ev: { data: string }) => void) | null = null
      onerror: (() => void) | null = null
      constructor(url: string) {
        this.url = url
        sockets.push(this)
        ;(window as unknown as Record<string, unknown>).__fakeSockets = sockets
        queueMicrotask(() => {
          this.readyState = 1
          this.onopen?.()
        })
      }
      send() { /* 上行无需处理 */ }
      close() {
        if (this.readyState !== 3) {
          this.readyState = 3
          this.onclose?.()
        }
      }
    }
    window.WebSocket = FakeWS as unknown as typeof WebSocket
    ;(window as unknown as Record<string, unknown>).__fakeSendToLast = (msg: unknown) => {
      const s = sockets[sockets.length - 1] as { onmessage: ((ev: { data: string }) => void) | null } | undefined
      s?.onmessage?.({ data: JSON.stringify(msg) })
    }
  })
}

function socketCount(page: import('@playwright/test').Page): Promise<number> {
  return page.evaluate(() => (window as unknown as { __fakeSockets?: unknown[] }).__fakeSockets?.length ?? 0)
}

test.describe('项目切换不串台', () => {
  test.beforeEach(async ({ page }) => {
    await installFakeWs(page)
    await page.route(/\/api\/plan/, async (route) => {
      const proj = new URL(route.request().url()).searchParams.get('project') || 'A'
      await route.fulfill({ json: proj === 'B' ? planB : planA })
    })
    await page.route(/\/api\/session/, async (route) => {
      const url = route.request().url()
      const method = route.request().method()
      if (method === 'POST' && url.includes('/switch')) {
        const body = route.request().postDataJSON() as { project: string }
        await route.fulfill({ json: { ok: true, project: body.project, expires_in: 3600 } })
        return
      }
      if (method === 'POST') {
        await route.fulfill({ json: { ok: true, token: 't', project: 'A', expires_in: 3600 } })
        return
      }
      await route.fulfill({ json: { ok: true, project: 'A', expires_in: 3600 } })
    })
    await page.route(/\/api\/projects\/names/, async (route) => {
      await route.fulfill({ json: { ok: true, projects: [{ id: 'A', name: '项目甲' }, { id: 'B', name: '项目乙' }] } })
    })
    await page.route(/\/api\/events/, async (route) => await route.fulfill({ json: { ok: true, project: 'A', since: 0, seq: 0, events: [] } }))
    await page.route(/\/api\/mode/, async (route) => await route.fulfill({ json: { ok: true, mode: 'auto' } }))
    await page.route(/\/api\/roles\/summary/, async (route) => await route.fulfill({ json: { ok: true, project: 'A', roles: [] } }))
  })

  test('解锁后下拉按 project_id 回显当前项目', async ({ page }) => {
    await page.goto('/')
    await page.locator('input[placeholder*="项目名"]').fill('A')
    await page.getByRole('button', { name: '解锁控制台' }).click()
    await expect(page.getByTestId('conn-state')).toContainText('已连接')
    // 缺陷⑤回归：option value 与绑定值必须同为 project_id（此处 name≠id 故意分裂以暴露回显失效）
    await expect(page.locator('.project-select')).toHaveValue('A')
  })

  test('A→B 切换后实时通道重建且下拉回显 B', async ({ page }) => {
    await page.goto('/')
    await page.locator('input[placeholder*="项目名"]').fill('A')
    await page.getByRole('button', { name: '解锁控制台' }).click()
    await expect(page.getByTestId('conn-state')).toContainText('已连接')
    expect(await socketCount(page)).toBe(1)

    await page.locator('.project-select').selectOption({ value: 'B' })
    // 缺陷④回归：disconnect 后必须建立新 WS，且连接状态不回落到「未连接」
    await expect.poll(async () => socketCount(page), { timeout: 10_000 }).toBeGreaterThanOrEqual(2)
    await expect(page.getByTestId('conn-state')).toContainText('已连接', { timeout: 10_000 })
    await expect(page.locator('.project-select')).toHaveValue('B')
  })

  test('跨项目 plan_update 注入后 UI 不变，同项目更新正常生效', async ({ page }) => {
    await page.goto('/')
    await page.locator('input[placeholder*="项目名"]').fill('A')
    await page.getByRole('button', { name: '解锁控制台' }).click()
    await expect(page.getByTestId('conn-state')).toContainText('已连接')
    await page.getByRole('button', { name: '刷新计划' }).click()
    await expect(page.locator('.summary .mono')).toContainText('1 / 1')

    // 注入 B 项目的 plan_update → 必须被项目守卫丢弃，UI 保持 A 的 1/1
    await page.evaluate(() => {
      ;(window as unknown as { __fakeSendToLast: (m: unknown) => void }).__fakeSendToLast({
        type: 'plan_update', project: 'B', plan: { ok: true, project: 'B', total: 2, done: 0, percent: 0, tasks: [], 阶段: [] },
      })
    })
    await page.waitForTimeout(800)
    await expect(page.locator('.summary .mono')).toContainText('1 / 1')

    // 注入 A 项目的合法更新 → 正常生效（守卫不误杀同项目消息）
    await page.evaluate((plan) => {
      ;(window as unknown as { __fakeSendToLast: (m: unknown) => void }).__fakeSendToLast({
        type: 'plan_update', project: 'A', plan,
      })
    }, planA2)
    await expect(page.locator('.summary .mono')).toContainText('1 / 1')
    await expect(page.locator('footer.foot')).toContainText('最近更新')
  })
})
