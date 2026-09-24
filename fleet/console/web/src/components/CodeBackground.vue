<script setup lang="ts">
/**
 * CodeBackground · 锁屏动态背景（代码块运行效果）
 *
 * 实现要点（融合业界最佳实践，零依赖 Canvas 2D）：
 * - requestAnimationFrame 唯一渲染入口（弃 setInterval，避免时间漂移与假流畅）
 * - 每列独立字符流对象：速度/长度/字符刷新间隔各异 → 电影级层次感
 * - 亮头辉光（shadowBlur + 三层亮度）+ 半透明覆盖拖尾
 * - 帧率自适应（60/120Hz 运行时采样）
 * - devicePixelRatio 适配高分屏；resize 防抖重排
 * - 性能守卫：页面不可见自动暂停；prefers-reduced-motion 降级为静态低密度帧
 * - 配色：项目主题青碧色系（与控制台深色科技风一致）
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

const canvasRef = ref<HTMLCanvasElement | null>(null)

/** 代码感字符集：代码符号为主 + 数字 + 少量片假名点缀 */
const GLYPHS = '{}();=<>/+*[]#$_-|&%!?:01' + 'アイウエオカキクケコサシスセソ' + '01{};</>=fnifelenew+*'

const HEAD_COLOR = '#9beaff'
const HEAD_GLOW = '#00d4ff'
const MID_COLOR = '#17a8cc'
const TAIL_COLOR = '#0b4a5e'
const FADE_FILL = 'rgba(10, 14, 26, 0.08)'

interface Column {
  x: number
  y: number
  speed: number
  len: number
  glyphs: string[]
  tick: number
  interval: number
}

let rafId = 0
let columns: Column[] = []
let width = 0
let height = 0
let fontSize = 15
let disposed = false
let lastTime = 0
let frameInterval = 1000 / 60
const fpsSamples: number[] = []

function randomGlyph(): string {
  return GLYPHS[Math.floor(Math.random() * GLYPHS.length)]!
}

function makeColumn(x: number, heightValue: number): Column {
  return {
    x,
    y: Math.random() * heightValue * 1.5 - heightValue * 0.5,
    speed: 0.6 + Math.random() * 1.6,
    len: 6 + Math.floor(Math.random() * 18),
    glyphs: Array.from({ length: 24 }, randomGlyph),
    tick: 0,
    interval: 2 + Math.floor(Math.random() * 6),
  }
}

function initColumns(ctx: CanvasRenderingContext2D): void {
  const count = Math.max(8, Math.floor(width / (fontSize * 1.4)))
  columns = []
  for (let i = 0; i < count; i++) {
    columns.push(makeColumn(i * fontSize * 1.4 + fontSize * 0.4, height))
  }
  void ctx
}

function resize(canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D): void {
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  width = window.innerWidth
  height = window.innerHeight
  canvas.width = Math.floor(width * dpr)
  canvas.height = Math.floor(height * dpr)
  canvas.style.width = `${width}px`
  canvas.style.height = `${height}px`
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.fillStyle = '#0a0e1a'
  ctx.fillRect(0, 0, width, height)
  initColumns(ctx)
}

function adaptFPS(delta: number): void {
  fpsSamples.push(1000 / Math.max(delta, 1))
  if (fpsSamples.length >= 30) {
    const avg = fpsSamples.reduce((a, b) => a + b, 0) / fpsSamples.length
    frameInterval = 1000 / (avg > 90 ? 120 : 60)
    fpsSamples.length = 0
  }
}

function drawFrame(ctx: CanvasRenderingContext2D): void {
  // 半透明覆盖 → 拖尾
  ctx.fillStyle = FADE_FILL
  ctx.fillRect(0, 0, width, height)
  ctx.font = `${fontSize}px monospace`

  for (const col of columns) {
    col.y += col.speed
    col.tick += 1
    if (col.tick % col.interval === 0) {
      col.glyphs[Math.floor(Math.random() * col.glyphs.length)] = randomGlyph()
    }

    for (let i = 0; i < col.len; i++) {
      const y = col.y - i * fontSize
      if (y < 0 || y > height) continue
      const glyph = col.glyphs[i % col.glyphs.length]!
      if (i === 0) {
        // 亮头 + 辉光
        ctx.fillStyle = HEAD_COLOR
        ctx.shadowColor = HEAD_GLOW
        ctx.shadowBlur = 12
      } else if (i < 3) {
        ctx.fillStyle = MID_COLOR
        ctx.shadowBlur = 0
      } else {
        // 尾部渐暗
        ctx.fillStyle = TAIL_COLOR
        ctx.shadowBlur = 0
      }
      ctx.fillText(glyph, col.x, y)
    }
    ctx.shadowBlur = 0

    if (col.y - col.len * fontSize > height) {
      const fresh = makeColumn(col.x, height)
      col.y = fresh.y
      col.speed = fresh.speed
      col.len = fresh.len
      col.glyphs = fresh.glyphs
      col.tick = 0
      col.interval = fresh.interval
    }
  }
}

let reducedMotion = false
let ctxRef: CanvasRenderingContext2D | null = null

function handleResize(): void {
  if (ctxRef) onResize(canvasRef.value!, ctxRef)
}

function loop(now: number): void {
  if (disposed) return
  const delta = now - lastTime
  if (delta >= frameInterval) {
    adaptFPS(delta)
    lastTime = now
    const canvas = canvasRef.value
    const ctx = canvas?.getContext('2d')
    if (ctx) drawFrame(ctx)
  }
  rafId = requestAnimationFrame(loop)
}

/** 静态降级：prefers-reduced-motion 时只绘制一帧低密度字符，不启动动画循环 */
function drawStatic(ctx: CanvasRenderingContext2D): void {
  ctx.fillStyle = '#0a0e1a'
  ctx.fillRect(0, 0, width, height)
  ctx.font = `${fontSize}px monospace`
  for (let i = 0; i < 60; i++) {
    ctx.fillStyle = i % 3 === 0 ? MID_COLOR : TAIL_COLOR
    ctx.fillText(randomGlyph(), Math.random() * width, Math.random() * height)
  }
}

let resizeTimer = 0
function onResize(canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D): void {
  window.clearTimeout(resizeTimer)
  resizeTimer = window.setTimeout(() => resize(canvas, ctx), 150)
}

function onVisibility(): void {
  // 页面不可见时 rAF 本身会节流；此处只重置 lastTime 防止恢复瞬间的巨大 delta
  if (!document.hidden) lastTime = performance.now()
}

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  ctxRef = ctx

  resize(canvas, ctx)
  window.addEventListener('resize', handleResize)
  document.addEventListener('visibilitychange', onVisibility)

  if (reducedMotion) {
    drawStatic(ctx)
    return
  }
  lastTime = performance.now()
  rafId = requestAnimationFrame(loop)
})

onBeforeUnmount(() => {
  disposed = true
  cancelAnimationFrame(rafId)
})
</script>

<template>
  <canvas ref="canvasRef" class="code-bg" aria-hidden="true" />
</template>

<style scoped>
.code-bg {
  position: absolute;
  inset: 0;
  display: block;
  z-index: 0;
}
</style>
