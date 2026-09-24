/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  export default component
}

interface ImportMetaEnv {
  /** 'true' 时启用 src/mock 的 REST + WS mock，不等后端联调 */
  readonly VITE_USE_MOCK?: string
  /** 显式指定 API 基址；默认同源（server.py 已托管 dist） */
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
