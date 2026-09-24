/** 聊天回显链路诊断：解锁 → 发消息 → 抓 WS 下行帧 + dump 聊天 DOM */
import { chromium } from 'playwright'

const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:5000'
const marker = 'diag-' + Date.now()
const frames = []
const browser = await chromium.launch()
const page = await browser.newPage()

page.on('websocket', (ws) => {
  ws.on('framereceived', (frame) => {
    try { frames.push(JSON.parse(String(frame.payload))) } catch { frames.push({ raw: String(frame.payload).slice(0, 120) }) }
  })
})

await page.goto(BASE + '/')
await page.locator('input[placeholder*="项目名"]').fill('AideanFleet')
await page.getByRole('button', { name: '解锁控制台' }).click()
await page.getByTestId('conn-state').waitFor({ state: 'visible', timeout: 15000 })
await page.waitForTimeout(2500)

await page.goto(BASE + '/chat')
await page.locator('textarea, input[placeholder*="指令"]').first().fill(marker)
const framesBefore = frames.length
await page.getByRole('button', { name: '发送' }).click()
await page.waitForTimeout(4000)

const sentOk = frames.some((f, i) => i >= framesBefore && JSON.stringify(f).includes(marker))
const echoFrames = frames.filter((f) => f.type === 'chat_message' && JSON.stringify(f).includes(marker))
const domText = await page.locator('.chat-page, main, body').first().innerText()
console.log(JSON.stringify({
  marker,
  sentSeenInFrames: sentOk,
  echoFrames: echoFrames.map((f) => ({ type: f.type, project: f.project, action: f.event?.action })),
  markerInDom: domText.includes(marker),
  domSample: domText.split('\n').filter((l) => l.includes(marker) || l.includes('Manager')).slice(0, 5),
}, null, 2))
await browser.close()
