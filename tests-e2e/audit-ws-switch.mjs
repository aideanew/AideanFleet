/**
 * 缺陷④ 实测脚本：真实浏览器 + 真实 WS + 真实项目切换
 *
 * 步骤：解锁 P-008(Test09181120) → 记录 conn-state 与 WS 生命周期
 *      → 下拉切换到 P-007(Test09171500) → 等 4 秒 → 再记录
 * 判定：切换后 conn-state 若为「未连接」且无新 WS 建立，则断链回归成立。
 */
import { chromium } from 'playwright'

const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:5000'
const FROM = 'Test09181120' // P-008
const TO_ID = 'P-007'       // Test09171500

const wsLog = []
const browser = await chromium.launch()
const page = await browser.newPage()

page.on('websocket', (ws) => {
  wsLog.push({ t: Date.now(), event: 'open', url: ws.url() })
  ws.on('close', () => wsLog.push({ t: Date.now(), event: 'close' }))
})

await page.goto(BASE + '/')
await page.locator('input[placeholder*="项目名"]').fill(FROM)
await page.getByRole('button', { name: '解锁控制台' }).click()

const conn = page.getByTestId('conn-state')
await conn.waitFor({ state: 'visible', timeout: 10000 })

// 等待首连就绪（最多 10 秒）
let state1 = ''
for (let i = 0; i < 20; i++) {
  state1 = (await conn.textContent()) ?? ''
  if (state1.includes('已连接')) break
  await page.waitForTimeout(500)
}

// 触发真实项目切换
const optionValues = await page.locator('.project-select option').evaluateAll(
  (els) => els.map((el) => ({ value: el.value, label: el.textContent.trim() })),
)
const selectBefore = await page.locator('.project-select').inputValue()
console.log('切换前 select 值:', selectBefore, '| 选项数:', optionValues.length)
await page.locator('.project-select').selectOption({ value: TO_ID })
await page.waitForTimeout(4000)
const state2 = (await conn.textContent()) ?? ''
const topbarProject = await page.locator('.project-select').inputValue()

console.log(JSON.stringify({
  from: FROM, to: TO_ID,
  selectBefore,
  connBefore: state1.trim(),
  connAfter: state2.trim(),
  selectValueAfter: topbarProject,
  wsEvents: wsLog,
  verdict: state2.includes('已连接') && selectBefore === 'P-008' && topbarProject === 'P-007'
    ? 'PASS: 切换后实时通道存活且回显正确'
    : 'FAIL: ' + JSON.stringify({ conn: state2.trim(), selectBefore, selectValueAfter: topbarProject }),
}, null, 2))

await page.screenshot({ path: '../reports/ui03r/shots/audit-switch-conn.png' })
await browser.close()
