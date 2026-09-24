# CLI 安装决策单

> **日期**: 2026-09-15
> **编制**: INT-04R 返工交付
> **用途**: 供用户拍板是否安装真实 CLI，以及安装哪些
> **版本说明**: 本单为 Phase-2 时点（4 个 CLI）的决策记录；执行体已扩至 7 个
> （新增 cline / gemini / grok），新机器装机请直接使用 `scripts/install_fleet_clis.ps1`
> 或见 `docs/CLI安装与自动化部署指南.md`。

---

## 本机实测现状（Phase-2 时点）

| CLI | 本机 PATH | 版本 | 安装位置 |
|-----|-----------|------|----------|
| Claude Code | ✅ 可用 | 2.1.272 | `C:\Users\EDY\AppData\Roaming\npm\claude.cmd` |
| Codex CLI | ✅ 可用 | 0.153.4 | `C:\Users\EDY\AppData\Roaming\npm\codex.cmd` |
| OpenCode | ✅ 可用 | 1.18.31 | `C:\Users\EDY\AppData\Roaming\npm\opencode.cmd` |
| Hermes | ✅ 可用 | v0.21.1 | `C:\Users\EDY\AppData\Local\hermes\bin\hermes.exe` |

**检测方式**: `shutil.which()` + `{cmd} --version`，PowerShell 环境。

**注意**: Hermes 官方声明仅支持 macOS/Linux/WSL2，原生 Windows 不在官方支持范围。
本机 Hermes 通过 git clone + venv 方式安装（非官方渠道），功能可能不完整。

---

## 决策选项

### 选项 A：保持现状（推荐）

**内容**: 不安装/不更改任何 CLI，系统以 FakeAdapter 验收。

| 项目 | 说明 |
|------|------|
| CLI 烟雾测试 | 本机 4 个 CLI 均可用，烟雾测试通过 |
| 真实执行 | 以 FakeAdapter 为主，不走真实 CLI 执行链路 |
| 剩余风险 | CLI 升级后行为可能变化；Hermes 原生 Windows 无官方支持 |
| 改动量 | 零 |

### 选项 B：仅安装 claude + codex + opencode（npm）

**内容**: 通过 npm 全局安装三个 CLI，Hermes 暂不接入。

| 项目 | 说明 |
|------|------|
| 安装命令 | `npm install -g @anthropic-ai/claude-code @openai/codex opencode` |
| CLI 烟雾测试 | 通过 |
| 真实执行 | 可走 Claude Code / Codex / OpenCode 真实执行链路 |
| 剩余风险 | 需要各 CLI 的 API Key；Hermes 不在范围内 |
| 改动量 | 零代码改动，仅环境配置 |

### 选项 C：全装含 Hermes（需 WSL2）

**内容**: 安装全部 4 个 CLI，Hermes 走 WSL2。

| 项目 | 说明 |
|------|------|
| 安装命令 | npm 安装 3 个 + WSL2 内安装 Hermes |
| CLI 烟雾测试 | 通过 |
| 真实执行 | 全部 4 个 CLI 可走真实执行链路 |
| 剩余风险 | WSL2 跨子系统调用需改动 launch_core（eval 子进程路径）；Hermes 官方仅支持 Linux |
| 改动量 | 需评估 launch_core 跨子系统调用改动量（不在本包范围） |

---

## 各 CLI 详细信息

### Claude Code

- **来源**: Anthropic 官方
- **安装**: `npm install -g @anthropic-ai/claude-code`
- **依赖**: Node.js 18+，Anthropic API Key
- **Windows 支持**: ✅ 官方支持
- **本机状态**: 已安装 (2.1.272)

### Codex CLI

- **来源**: OpenAI 官方
- **安装**: `npm install -g @openai/codex`
- **依赖**: Node.js 18+，OpenAI API Key
- **Windows 支持**: ✅ 官方支持
- **本机状态**: 已安装 (0.153.4)

### OpenCode

- **来源**: 社区
- **安装**: `npm install -g opencode`
- **依赖**: Node.js
- **Windows 支持**: ✅ 社区验证
- **本机状态**: 已安装 (1.18.31)

### Hermes

- **来源**: hermes-agent
- **安装**: git clone + venv（非 npm）
- **依赖**: Python 3.11+，OpenAI SDK
- **Windows 支持**: ⚠️ 官方仅支持 macOS/Linux/WSL2
- **本机状态**: 已安装 (v0.21.1)，通过 git clone 方式，非官方渠道

---

## 建议

本机 4 个 CLI 均已可用且版本探测通过。当前系统以 FakeAdapter 验收已满足 Phase 2 要求。
若需接入真实执行链路，建议选 **选项 A（保持现状）**，待有实际需求时再按需安装。
