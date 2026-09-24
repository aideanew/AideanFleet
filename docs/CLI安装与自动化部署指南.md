# CLI 安装与自动化部署指南（cline / gemini / grok / claude / codex / opencode）

> 用途：供其他电脑自动化安装 Fleet 执行体 CLI。
> 版本基线：2026-09-18 于 Win10 x64 实测（`--version` 实测值见各节）。
> 事实来源：官方文档核验 + 本机实装，未经证实的参数一律不收录。

---

## 0. 通用前置

- Node.js ≥ 20（推荐 22+）：`node --version` 验证
- npm ≥ 10：`npm --version` 验证

**一键安装脚本（新电脑推荐路径）**：拉取 AideanFleet 后直接运行

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_fleet_clis.ps1
```

脚本幂等安装 cline / gemini / grok / claude / codex / opencode 六个执行体 CLI
（grok 走官方安装器，其余走 npm），已装且在工作路径的自动跳过；加 `-Force` 可重装。

PowerShell 一键自检脚本（安装后验证）：

```powershell
foreach ($c in "node","npm","cline","gemini","grok","claude","codex","opencode") {
  $cmd = Get-Command $c -ErrorAction SilentlyContinue
  if ($cmd) { "{0,-10} OK  {1}" -f $c, $cmd.Source }
  else      { "{0,-10} MISSING" -f $c }
}
```

## 1. cline（实测 3.0.61）

```powershell
# 安装（平台二进制，Windows arm64/x64 无需 Node 运行时）
npm install -g cline

# 验证
cline --version

# 认证（一次性，交互式；自动化环境用 flags 注入）
cline auth
cline auth --provider anthropic --apikey sk-... --modelid claude-sonnet-4-6
```

Fleet 无人值守口径（headless + 全自动批准）：

```powershell
# 单任务，NDJSON 事件流输出
cline --yolo --json "完成任务描述"
# 管道输入自动进 headless；-c 指定工作目录；-t 超时秒
git diff | cline --yolo -c "E:\Demo\MyProject" -t 600 "审查这些改动"
```

注意：
- 官方默认 human-in-the-loop（每步工具调用需审批）；headless 非 TTY 下需审批的调用会**直接拒绝**而非挂起 → 无人值守必须显式 `--yolo`。
- `--yolo` 默认禁用 spawn/team 工具（执行体不得自行开子团队，fleet 场景这是特性）。
- 会话历史：`cline history`；交互模式内 `/history`。

## 2. gemini（实测 0.58.0）

```powershell
npm install -g @google/gemini-cli
gemini --version

# 认证三选一：环境变量 / ~/.gemini/.env / 浏览器 OAuth
$env:GEMINI_API_KEY = "..."   # 或持久化到用户环境变量
```

Fleet 无人值守口径：

```powershell
gemini -p "任务描述" --approval-mode=yolo --output-format json
# 会话管理
gemini --resume <session-id>     # 恢复
gemini --list-sessions           # 列出
```

注意：旧别名 `--yolo` 仍可用但推荐 `--approval-mode=yolo`。

## 3. grok（实测 1.0.34）

```powershell
# Windows（官方安装器；会自动追加 %USERPROFILE%\.grok\bin 到用户 PATH）
irm https://x.ai/cli/install.ps1 | iex

# macOS / Linux / WSL
curl -fsSL https://x.ai/cli/install.sh | bash

# 验证（新开终端，PATH 需重新加载）
grok --version
```

**平台限制（实测）**：npm 包 `@xai-official/grok` 仅声明 `darwin/arm64`，win32/x64 安装报 `EBADPLATFORM` → Windows 只用官方安装器。

```powershell
# 认证三选一
grok login                    # 浏览器 OAuth（SuperGrok / X Premium+）
grok login --device-auth      # 无浏览器环境设备码
$env:XAI_API_KEY = "xai-..."  # API Key 按量计费
```

Fleet 无人值守口径：

```powershell
grok --no-auto-update --always-approve -p "任务描述" --output-format json
# --output-format 三选一：plain | json（末尾单对象，含 sessionId）| streaming-json（NDJSON 实时事件）
# 会话：-r <id> 恢复；-c 继续最近会话；-s <uuid> 仅新建（不恢复）；--fork-session 恢复时分叉
```

注意：自动化环境必须加 `--no-auto-update`（跳过后台更新检查）；也可在 `~/.grok/config.toml` 的 `[cli]` 段设 `auto_update = false` 持久关闭。

## 4. claude（Fleet 现役执行体）

```powershell
npm install -g @anthropic-ai/claude-code
claude --version

# Fleet 无人值守口径（.env executors 段现行 COMMAND）
claude -p "任务描述" --output-format json
```

## 5. codex（Fleet 现役执行体）

```powershell
npm install -g @openai/codex
codex --version

# Fleet 无人值守口径（适配器现行命令：workspace-write 沙箱 + JSON 事件流）
codex exec --json --skip-git-repo-check -s workspace-write -m <model-id>
# prompt 经 stdin 传入（多行任务包不能走 argv）
```

## 6. opencode（Fleet 现役执行体）

```powershell
npm install -g opencode-ai
opencode --version
```

---

## 7. PATH 注意事项（多 prefix 并存）

本机实测三类安装目录并存，均需在**新进程**中才可见：

| CLI | 实测位置 |
|---|---|
| cline / gemini | `%APPDATA%\npm\`（用户 npm prefix） |
| grok | `%USERPROFILE%\.grok\bin\`（安装器写入用户 PATH） |
| claude / codex / opencode（box-agent 托管） | box-agent skill-tools prefix |

自动化脚本安装后验证必须用**新开进程**（PowerShell/cmd 重启），当前会话不会感知刚追加的 PATH。

## 8. Fleet .env executors 段登记示例

```ini
# ===== [SECTION: executors] 执行体 =====
# command 为"最高权限启动"口径：所有 CLI 以跳过权限确认方式启动，避免无人值守卡住。
FLEET_EXECUTOR_1_NAME=claudecode
FLEET_EXECUTOR_1_COMMAND=claude -p --output-format json
FLEET_EXECUTOR_1_TIMEOUT=600

FLEET_EXECUTOR_2_NAME=codex
FLEET_EXECUTOR_2_COMMAND=codex exec --full-auto
FLEET_EXECUTOR_2_TIMEOUT=600

FLEET_EXECUTOR_3_NAME=opencode
FLEET_EXECUTOR_3_COMMAND=opencode run
FLEET_EXECUTOR_3_TIMEOUT=600

FLEET_EXECUTOR_4_NAME=hermes
FLEET_EXECUTOR_4_COMMAND=hermes
FLEET_EXECUTOR_4_TIMEOUT=600

FLEET_EXECUTOR_5_NAME=cline
FLEET_EXECUTOR_5_COMMAND=cline --yolo --json
FLEET_EXECUTOR_5_TIMEOUT=600

FLEET_EXECUTOR_6_NAME=gemini
FLEET_EXECUTOR_6_COMMAND=gemini -p --approval-mode=yolo --output-format json
FLEET_EXECUTOR_6_TIMEOUT=600

FLEET_EXECUTOR_7_NAME=grok
FLEET_EXECUTOR_7_COMMAND=grok --no-auto-update --always-approve -p --output-format json
FLEET_EXECUTOR_7_TIMEOUT=600
```

现有六个执行体 CLI 均有对应适配器（`fleet/executors/<name>.py`，注册名见下表）：

| 注册名 | CLI | 适配器文件 |
|---|---|---|
| claudecode | claude | claudecode.py |
| codex | codex | codex.py |
| opencode | opencode | opencode.py |
| hermes | hermes | hermes.py |
| cline | cline | cline.py |
| gemini | gemini | gemini.py |
| grok | grok | grok.py |
