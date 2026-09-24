/** 复刻 reconnect test3 的完整流程，定位回显渲染断点 */
import { chromium } from 'playwright'

const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:5000'
const marker = 'diag2-' + Date.now()
const frames = []
const sockets = []
const browser = await chromium.launch()
const page = await browser.newPage()

page.on('websocket', (ws) => {
  sockets.push({ t: Date.now(), ev: 'open', url: ws.url().slice(-20) })
  ws.on('close', () => sockets.push({ t: Date.now(), ev: 'close' }))
  ws.on('framereceived', (f) => {
    try {
      const j = JSON.parse(String(f.payload))
      frames.push({ t: Date.now(), type: j.type, project: j.project, action: j.event?.action, seq: j.event?.seq })
    } catch { /* 忽略 */ }
  })
})

await page.goto(BASE + '/chat')
const lockVisible = await page.locator('input[placeholder*="项目名"]').isVisible().catch(() => false)
if (lockVisible) {
  await page.locator('input[placeholder*="项目名"]').fill('AideanFleet')
  await page.getByRole('button', { name: '解锁控制台' }).click()
}
if (!new URL(page.url()).pathname.startsWith('/chat')) await page.goto(BASE + '/chat')
await page.getByTestId('conn-state').waitFor({ state: 'visible', timeout: 25000 })
await page.waitForTimeout(1500)

const connBefore = await page.getByTestId('conn-state').innerText()
await page.locator('textarea').first().fill(marker)
await page.getByRole('button', { name: '发送' }).click()
await page.waitForTimeout(5000)

const connAfter = await page.getByTestId('conn-state').innerText()
const domText = await page.locator('main, body').first().innerText()
const chatFrames = frames.filter((f) => f.type === 'chat_message')
console.log(JSON.stringify({
  marker,
  connBefore: connBefore.trim(),
  connAfter: connAfter.trim(),
  socketEvents: sockets,
  chatEchoFrames: chatFrames.filter((f) => JSON.stringify(f).includes(marker) || f.seq > 1900).slice(-6),
  markerInDom: domText.includes(marker),
  toastError: domText.includes('发送失败'),
}, null, 2))
await browser.close()
