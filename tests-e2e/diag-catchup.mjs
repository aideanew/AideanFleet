/** 复刻 reconnect test2：断网→降级→恢复，抓 events 请求 URL 序列 */
import { chromium } from 'playwright'

const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:5000'
const eventCalls = []
const netEvents = []
const browser = await chromium.launch()
const page = await browser.newPage()

page.on('request', (req) => {
  const url = req.url()
  if (url.includes('/api/events')) eventCalls.push(url.replace(BASE, ''))
})
page.on('websocket', (ws) => {
  netEvents.push({ t: Date.now(), ev: 'ws-open' })
  ws.on('close', () => netEvents.push({ t: Date.now(), ev: 'ws-close' }))
})

await page.goto(BASE + '/')
await page.locator('input[placeholder*="项目名"]').fill('AideanFleet')
await page.getByRole('button', { name: '解锁控制台' }).click()
const conn = page.getByTestId('conn-state')
await conn.waitFor({ state: 'visible', timeout: 15000 })
for (let i = 0; i < 30; i++) {
  if ((await conn.innerText()).includes('已连接')) break
  await page.waitForTimeout(500)
}
const before = await conn.innerText()

await page.context().setOffline(true)
netEvents.push({ t: Date.now(), ev: 'offline-set' })
for (let i = 0; i < 40; i++) {
  const s = await conn.innerText()
  if (/重连|降级为轮询|未连接/.test(s)) { netEvents.push({ t: Date.now(), ev: 'left-online', state: s.trim() }); break }
  await page.waitForTimeout(1000)
}
eventCalls.length = 0
await page.context().setOffline(false)
netEvents.push({ t: Date.now(), ev: 'online-set' })
await page.waitForTimeout(8000)
const after = await conn.innerText()

console.log(JSON.stringify({
  connBefore: before.trim(),
  connAfter: after.trim(),
  netEvents,
  eventsAfterRecovery: eventCalls,
  hasSinceNonzero: eventCalls.some((u) => /\/api\/events\?.*since=([1-9]\d*)/.test(u)),
}, null, 2))
await browser.close()
