# AideanFleet 执行体 CLI 一键安装脚本（Windows PowerShell）
# 用法：拉取 AideanFleet 后，在 PowerShell 运行：  powershell -ExecutionPolicy Bypass -File scripts\install_fleet_clis.ps1
# 说明：自动安装 cline / gemini / grok / claude / codex / opencode 六个执行体 CLI，
#       幂等（已装版本在 PATH 中即可跳过），成功信息实时打印；认证命令不在此脚本，见 docs/CLI安装与自动化部署指南.md。
# 平台：Windows（grok 仅支持官方安装器；npm 包 @xai-official/grok 仅 darwin/arm64）

[CmdletBinding()]
param(
    [switch]$Force   # 已有 CLI 也重新安装（跳过 PATH 检测）
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Write-Host "==> AideanFleet CLI 一键安装 @ $repo" -ForegroundColor Cyan

function Test-Cli([string]$name) {
    return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Install-NpmCli([string]$name, [string]$pkg, [string]$npmName) {
    if (-not $Force -and (Test-Cli $name)) {
        Write-Host "  [跳过] $name 已在 PATH: $((Get-Command $name).Source)" -ForegroundColor Green
        return
    }
    Write-Host "  [安装] npm install -g $pkg" -ForegroundColor Yellow
    & npm install -g $pkg
    if ($LASTEXITCODE -ne 0) { throw "npm 安装 $pkg 失败" }
    $src = (Get-Command $name -ErrorAction SilentlyContinue).Source
    Write-Host "  [完成] $name -> $src ($npmName)" -ForegroundColor Green
}

function Install-GrokOfficial {
    if (-not $Force -and (Test-Cli "grok")) {
        Write-Host "  [跳过] grok 已在 PATH: $((Get-Command grok).Source)" -ForegroundColor Green
        return
    }
    Write-Host "  [安装] 官方安装器 (irm https://x.ai/cli/install.ps1 | iex)" -ForegroundColor Yellow
    # 官方安装器自动追加 %USERPROFILE%\.grok\bin 到用户 PATH；本进程 PATH 需手动并入以便立即可用
    irm https://x.ai/cli/install.ps1 | iex
    if (-not (Test-Cli "grok")) {
        $grokBin = Join-Path $env:USERPROFILE ".grok\bin"
        if (Test-Path (Join-Path $grokBin "grok.exe")) {
            $env:PATH = "$grokBin;$env:PATH"
        }
    }
    if (-not (Test-Cli "grok")) { throw "grok 安装后仍不可见，请新开终端后再试" }
    Write-Host "  [完成] grok -> $((Get-Command grok).Source) (官方安装器)" -ForegroundColor Green
}

# 0. 前置依赖检测
Write-Host "`n==> 0. 前置依赖检测 (Node.js >= 20 / npm >= 10)" -ForegroundColor Cyan
if (-not (Test-Cli "node")) { throw "缺少 Node.js，请先安装 Node.js 20+" }
if (-not (Test-Cli "npm"))  { throw "缺少 npm，请先安装 npm" }
Write-Host "    node: $(node --version)" -ForegroundColor Green
Write-Host "    npm : $(npm --version)" -ForegroundColor Green

# 1. npm 系 CLI
Write-Host "`n==> 1. npm 全局 CLI" -ForegroundColor Cyan
Install-NpmCli "cline"    "cline"                    "cline"
Install-NpmCli "gemini"   "@google/gemini-cli"      "gemini"
Install-NpmCli "claude"   "@anthropic-ai/claude-code" "claude"
Install-NpmCli "codex"    "@openai/codex"           "codex"
Install-NpmCli "opencode" "opencode-ai"             "opencode"

# 2. grok（官方安装器）
Write-Host "`n==> 2. grok（官方安装器）" -ForegroundColor Cyan
Install-GrokOfficial

# 3. 汇总
Write-Host "`n==> 3. 安装汇总" -ForegroundColor Cyan
$names = @("cline","gemini","grok","claude","codex","opencode")
$allOk = $true
foreach ($name in $names) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { Write-Host ("  [OK  ] {0,-9} {1}" -f $name, $cmd.Source) -ForegroundColor Green }
    else      { Write-Host ("  [缺失] {0,-9} 未在 PATH 中" -f $name) -ForegroundColor Red; $allOk = $false }
}
if (-not $allOk) {
    Write-Host "`n部分 CLI 当前终端不可见：追加的 PATH 需要新开进程/终端后才生效。" -ForegroundColor Yellow
    Write-Host "验证命令： 'foreach ($c in 'cline','gemini','grok','claude','codex','opencode') { $m=Get-Command $c -EA SilentlyContinue; '{0,-9} {1}' -f $c, $m.Source }'" -ForegroundColor Yellow
}
Write-Host "`n完成。认证与 Fleet 无人值守口径请参考: docs/CLI安装与自动化部署指南.md" -ForegroundColor Cyan