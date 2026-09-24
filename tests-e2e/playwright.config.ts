import { defineConfig, devices } from '@playwright/test'

/**
 * UI-03R e2e 配置
 *
 * baseURL 支持环境变量切换，便于 5000（正式）与 5050（当前验证端口）双向复用：
 *   E2E_BASE_URL=http://127.0.0.1:5000 npx playwright test     # 主题1 完成后
 *   npx playwright test                                        # 默认 5050
 *
 * 说明：控制台为 SPA（history 路由），server.py 已提供 /{path} → index.html 兜底，
 * 因此可对 /overview、/models 等深链直接 goto。
 */
const BASE_URL = process.env.E2E_BASE_URL || 'http://127.0.0.1:5050'
const PROJECT = process.env.E2E_PROJECT || 'AideanFleet'
/** 每轮独立产物目录：避免 Playwright 启动时清空旧目录而触发本机批量删除护栏 */
const RUN_ID = process.env.E2E_RUN_ID || new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14)

/**
 * 产物策略（重要，不要随手改回去）：
 * 本机对「同一轮内删除 >50 个文件」有安全护栏，而 Playwright 会在每次启动时清空 outputDir、
 * 并在每个用例结束后清理 .playwright-artifacts-N 临时目录。若开启 trace/screenshot/video，
 * 单次失败就会产生上百个资源文件，护栏会**在跑测中途抛错**，连带把不相关的用例判成失败
 * （已实测：6 个失败里有 3 个是护栏误伤）。
 *
 * 因此：三者一律关闭，产物目录保持近空；
 * 需要截图留证时，由用例内部显式调用 saveShot()，落到 reports/ui03r/shots/（稳定、少量）。
 */
export default defineConfig({
  testDir: './specs',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  outputDir: `e2e-out/${RUN_ID}`,
  use: {
    baseURL: BASE_URL,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
    viewport: { width: 1440, height: 900 },
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  metadata: { baseURL: BASE_URL, project: PROJECT },
})

export { BASE_URL, PROJECT }
