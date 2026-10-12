import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 工作包 UI-02 §9.1-2：
//  - dev 代理 /api 与 /tasks → http://127.0.0.1:3100
//  - dev 代理 /ws → ws://127.0.0.1:3100（WebSocket）
//  - 构建产物落 fleet/console/dist（server.py 采用 dist 优先、static 兜底托管）
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: false,
    proxy: {
      '/api': { target: 'http://127.0.0.1:3100', changeOrigin: true },
      '/tasks': { target: 'http://127.0.0.1:3100', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:3100', ws: true },
    },
  },
  build: {
    outDir: '../dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
  },
})
