/**
 * Setup API（TASK-205）。类型全部来自 types.ts（契约生成物）。
 */

import { request } from './client'
import type {
  SetupJobResponse,
  SetupStatusResponse,
} from './types'

export function setupStatus(): Promise<SetupStatusResponse> {
  return request<SetupStatusResponse>('/api/setup/status')
}

export function setupInstall(components: string[], mirror: 'auto' | 'official' | 'cn' = 'auto'): Promise<{ ok: boolean; job_id: string }> {
  return request<{ ok: boolean; job_id: string }>('/api/setup/install', {
    method: 'POST',
    body: JSON.stringify({ components, mirror }),
  })
}

export function setupJob(jobId: string): Promise<SetupJobResponse> {
  return request<SetupJobResponse>(`/api/setup/jobs/${encodeURIComponent(jobId)}`)
}

/** 错误码 → 中文（ux-states setup_wizard.error 口径） */
export const INSTALL_ERROR_TEXT: Record<string, string> = {
  DOWNLOAD_FAILED: '下载失败：检查网络后重试',
  CHECKSUM_MISMATCH: '下载文件校验不一致：点『切换国内镜像重试』',
  NETWORK_BLOCKED: '网络被拦截：检查防火墙或代理',
  DISK_FULL: '磁盘空间不足：清理后重试',
  PERMISSION_DENIED: '权限不足：以普通用户重新运行安装器',
  NPM_INSTALL_FAILED: 'CLI 安装失败：查看日志，或切换国内镜像重试',
  VERSION_TOO_OLD: '版本低于下限：卸载旧版后重试',
  POST_INSTALL_NOT_ON_PATH: '安装完成但未检测到命令：新开终端后点重试',
  UNSUPPORTED_ARCH: '当前 CPU 架构不受支持（需要 x64）',
}
