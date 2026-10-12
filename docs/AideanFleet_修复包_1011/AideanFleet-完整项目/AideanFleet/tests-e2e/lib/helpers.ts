import fs from 'node:fs'
import path from 'node:path'
import { expect, type Page } from '@playwright/test'

/** 控制台默认项目名（可用 E2E_PROJECT 覆盖） */
export const PROJECT = process.env.E2E_PROJECT || 'AideanFleet'

/**
 * 证据截图落盘目录（稳定、少量）。
 * 因为 config 里关闭了自动截图（避免触发本机批量删除护栏），
 * 需要留证的用例一律显式调用 saveShot。
 * 注：specs 以 ESM 运行，不能用 __dirname；Playwright 的工作目录即 tests-e2e。
 */
export const SHOT_DIR =
  process.env.E2E_SHOT_DIR || path.resolve(process.cwd(), '..', 'reports', 'ui03r', 'shots')

export async function saveShot(page: Page, name: string): Promise<string> {
  fs.mkdirSync(SHOT_DIR, { recursive: true })
  const file = path.join(SHOT_DIR, `${name}.png`)
  await page.screenshot({ path: file, fullPage: true })
  return file
}

/**
 * 七个一级页面的路由与标题（顺序即 UI-02 冻结顺序，永不重排）。
 * UI-03R 新增的治理页一律**追加**在 `EXTRA_PAGES`，不得插入本数组。
 */
export const CORE_PAGES = [
  { path: '/overview', title: '总览' },
  { path: '/chat', title: '对话' },
  { path: '/models', title: '模型' },
  { path: '/roles', title: '角色' },
  { path: '/executors', title: '执行体' },
  { path: '/extensions', title: '拓展' },
  { path: '/notifications', title: '消息' },
] as const

/** UI-03R 追加的治理页（审批中心 / 成本面板，带数据源标注） */
export const EXTRA_PAGES = [
  { path: '/approvals', title: '审批中心' },
  { path: '/cost', title: '成本面板' },
] as const

/** 历史页：独立一级页（无治理数据源标注，走历史任务 API），仅参与侧栏顺序 */
export const HISTORY_PAGE = { path: '/history', title: '历史' } as const

/** 七页回归使用的冻结清单（保持兼容旧断言） */
export const PAGES = CORE_PAGES

/** 侧栏完整顺序 = 冻结 7 项 + 追加项 */
export const ALL_PAGES = [...CORE_PAGES, ...EXTRA_PAGES, HISTORY_PAGE]

/** 解锁控制台（锁屏 → 外壳），返回后停留在 /overview */
export async function unlock(page: Page): Promise<void> {
  await page.goto('/')
  const input = page.locator('input[placeholder*="项目名"]')
  await input.waitFor({ state: 'visible', timeout: 20_000 })
  await input.fill(PROJECT)
  await page.getByRole('button', { name: '解锁控制台' }).click()
  await expect(page.getByTestId('conn-state')).toBeVisible({ timeout: 25_000 })
}

/**
 * 深链到某页；若因会话失效回落到锁屏，则自动解锁后再次导航。
 * 会话存 sessionStorage（同 tab 刷新保持），故同 context 内后续导航无需重复解锁。
 */
export async function gotoPage(page: Page, path: string): Promise<void> {
  await page.goto(path)
  const lockInput = page.locator('input[placeholder*="项目名"]')
  if (await lockInput.isVisible().catch(() => false)) {
    await unlock(page)
  }
  if (!new URL(page.url()).pathname.startsWith(path)) {
    await page.goto(path)
  }
  await expect(page.getByTestId('conn-state')).toBeVisible({ timeout: 25_000 })
}

/** 读取顶栏连接状态文案 */
export async function connState(page: Page): Promise<string> {
  return (await page.getByTestId('conn-state').innerText()).trim()
}

/* ------------------------------------------------------------------ *
 * 服务端状态直读/直写（绕过 UI，用于「核对真实落位」与「用例后复原」）
 *
 * 为什么要有这组工具：
 *   调度模式 / 提醒开关都是**服务端状态**。用例改了服务端就得负责改回去，
 *   否则一次失败会把配置留在脏状态，污染后续所有轮次（实测踩过）。
 *   用 finally 里直写接口复原，比「再点一次 UI」可靠得多。
 * ------------------------------------------------------------------ */

export async function readNotifyConfig(page: Page): Promise<Record<string, boolean>> {
  return page.evaluate(async () => {
    const res = await fetch('/api/config/notify', { credentials: 'include' })
    const json = await res.json()
    return (json?.data ?? {}) as Record<string, boolean>
  })
}

export async function writeNotifyConfig(page: Page, data: Record<string, boolean>): Promise<number> {
  return page.evaluate(async (payload) => {
    const res = await fetch('/api/config/notify', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: payload }),
    })
    return res.status
  }, data)
}

export async function readMode(page: Page): Promise<string> {
  return page.evaluate(async () => {
    const res = await fetch('/api/mode', { credentials: 'include' })
    const json = await res.json()
    return String(json?.mode ?? '')
  })
}

export async function writeMode(page: Page, mode: string): Promise<number> {
  return page.evaluate(async (value) => {
    const res = await fetch('/api/mode', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: value, actor: 'e2e-restore' }),
    })
    return res.status
  }, mode)
}

/** 某个 testid 开关当前的 aria-checked（布尔） */
export async function switchState(page: Page, testId: string): Promise<boolean> {
  return (await page.getByTestId(testId).getAttribute('aria-checked')) === 'true'
}
