# AideanFleet 干净 Windows 机验收脚本（P6 / S13）
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify_clean_windows.ps1            # 完整验收
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify_clean_windows.ps1 -DryRun    # 仅环境+语法
# 说明：无干净 VM 时的最接近验收——不伪装安装器构建（iscc 由 CI installer.yml 承接）。
#   完整模式：1) Python>=3.11 探测  2) 全量 .py 语法编译（py_compile，不依赖第三方包）
#             3) 依赖安装（requirements.txt + -e .）  4) 密钥扫描  5) pytest 收集
#   -DryRun：只做 1)+2)（新机器无网/无依赖时也能跑）。
param([switch]$DryRun)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONDONTWRITEBYTECODE = "1"   # 不留 __pycache__ 污染

$failed = 0

function Fail($msg) {
    Write-Host "[FAIL] $msg" -ForegroundColor Red
    $script:failed++
}

# ---------- 1) Python 版本 ----------
Write-Host "==> 1/5 Python 探测（>= 3.11）"
try { $verOut = (python --version 2>&1) | Out-String } catch { Fail "未找到 python：$_"; exit 1 }
$verText = "$verOut".Trim() -replace "^Python\s+", ""
try {
    $ver = [version]$verText
    if ($ver -lt [version]"3.11") { Fail "Python $ver 低于 3.11（requires-python>=3.11）" }
    else { Write-Host "    OK: Python $ver" }
} catch {
    Fail "无法解析 python 版本：$verOut"
}

# ---------- 2) 语法编译（无需第三方依赖） ----------
Write-Host "==> 2/5 全量 .py 语法编译（compileall fleet scripts）"
python -m compileall -q fleet scripts
if ($LASTEXITCODE -ne 0) { Fail "compileall 退出码 $LASTEXITCODE（存在语法错误）" }
else { Write-Host "    OK" }

if ($DryRun) {
    Write-Host ""
    if ($failed -eq 0) { Write-Host "[PASS] DryRun（环境+语法）通过" -ForegroundColor Green }
    else { Write-Host "[FAIL] DryRun 未通过：$failed 项" -ForegroundColor Red }
    exit $failed
}

# ---------- 3) 依赖安装 ----------
Write-Host "==> 3/5 安装依赖（requirements.txt + -e .）"
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { Fail "pip install -r requirements.txt 失败（$LASTEXITCODE）" }
python -m pip install --quiet --disable-pip-version-check -e .
if ($LASTEXITCODE -ne 0) { Fail "pip install -e . 失败（$LASTEXITCODE）" }
if ($failed -eq 0) { Write-Host "    OK" }

# ---------- 4) 密钥扫描 ----------
Write-Host "==> 4/5 密钥回归扫描（scripts/check_credentials.py）"
python scripts/check_credentials.py
if ($LASTEXITCODE -ne 0) { Fail "check_credentials 未通过" }
else { Write-Host "    OK" }

# ---------- 5) pytest 收集 ----------
Write-Host "==> 5/5 pytest 收集（--collect-only，验证可导入性）"
python -m pytest tests --collect-only -q | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "pytest 收集失败（导入错误）" }
else { Write-Host "    OK" }

Write-Host ""
if ($failed -eq 0) { Write-Host "[PASS] 干净机验收（本机可仿真部分）全部通过" -ForegroundColor Green }
else { Write-Host "[FAIL] 验收未通过：$failed 项（真机验收另有 CI installer.yml 兜底）" -ForegroundColor Red }
exit $failed
