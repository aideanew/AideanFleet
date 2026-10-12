# AideanFleet make.ps1
# Usage: .\make.ps1 <target>  e.g. .\make.ps1 test, .\make.ps1 run

param(
  [Parameter(Position = 0)]
  [string]$Target = "help"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
$Venv = ".venv"

function Show-Help {
  Write-Host "AideanFleet make.ps1 - available targets:"
  Write-Host "  setup             create venv and install deps"
  Write-Host "  run               start console server (port 3100)"
  Write-Host "  run-cli           start CLI interactive mode"
  Write-Host "  test              run all unit tests"
  Write-Host "  guard             contracts check + migrations sync + all tests (CI gate)"
  Write-Host "  installer         build Windows installer (requires Inno Setup iscc)"
  Write-Host "  test-e2e          run end-to-end tests (Playwright)"
  Write-Host "  test-all          run all tests (incl. e2e)"
  Write-Host "  lint              run pyflakes"
  Write-Host "  frontend-install  install frontend deps"
  Write-Host "  frontend-build    build frontend -> dist/"
  Write-Host "  frontend-dev      frontend dev mode"
  Write-Host "  clean-cache       clean __pycache__ / .pyc"
  Write-Host "  clean-data        wipe data/ (runtime data)"
  Write-Host "  clean-all         clean caches and venv"
  Write-Host "  git-status        show git status"
  Write-Host "  check-creds       credential regression check"
}

switch ($Target) {
  "setup" {
    & python -m venv $Venv
    & "$Venv\Scripts\python.exe" -m pip install --upgrade pip
    & "$Venv\Scripts\python.exe" -m pip install -e ".[dev]"
    & "$Venv\Scripts\python.exe" -m pip install -r requirements.txt
    Write-Host "[OK] environment ready: $Venv\Scripts\Activate.ps1"
  }
  "run" {
    & $Python -m fleet.console.server
  }
  "run-cli" {
    & $Python run_interactive.py
  }
  "test" {
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    & $Python -m pytest tests -q
  }
  "guard" {
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    & $Python scripts/contracts_gen.py --check
    if ($LASTEXITCODE -ne 0) { throw "contracts_gen --check failed" }
    & $Python scripts/sync_migrations.py --check
    if ($LASTEXITCODE -ne 0) { throw "sync_migrations --check failed" }
    & $Python -m pytest tests -q
    if ($LASTEXITCODE -ne 0) { throw "pytest failed" }
  }
  "installer" {
    # 修复 N1：对齐 CI installer.yml——此前缺 sync/wheel/wheelhouse，
    # 干净检出直接构建会产出缺 _migrations/_manifest.json 的坏 wheel
    & $Python scripts/sync_migrations.py
    if ($LASTEXITCODE -ne 0) { throw "sync_migrations failed" }
    & $Python scripts/sync_migrations.py --check
    if ($LASTEXITCODE -ne 0) { throw "sync_migrations --check failed" }
    & $Python -m build --wheel
    if ($LASTEXITCODE -ne 0) { throw "build wheel failed" }
    & $Python -m pip download -q -d scripts/installer/windows/_wheelhouse .
    if ($LASTEXITCODE -ne 0) { throw "pip download wheelhouse failed" }
    & $Python scripts/installer/windows/fetch_runtimes.py
    if ($LASTEXITCODE -ne 0) { throw "fetch_runtimes failed" }
    & iscc scripts\installer\windows\AideanFleet.iss
    if ($LASTEXITCODE -ne 0) { throw "iscc failed" }
  }
  "test-e2e" {
    Push-Location tests-e2e
    try {
      if (-not (Test-Path "node_modules")) { npm install }
      npx playwright test
    } finally { Pop-Location }
  }
  "test-all" {
    & "$PSScriptRoot\make.ps1" test
    & "$PSScriptRoot\make.ps1" test-e2e
  }
  "lint" {
    & $Python -m pyflakes fleet/
    if ($LASTEXITCODE -ne 0) { Write-Host "[WARN] pyflakes found issues (non-fatal)" }
  }
  "frontend-install" {
    Push-Location fleet\console\web
    try { pnpm install } finally { Pop-Location }
  }
  "frontend-build" {
    Push-Location fleet\console\web
    try { pnpm build } finally { Pop-Location }
  }
  "frontend-dev" {
    Push-Location fleet\console\web
    try { pnpm dev } finally { Pop-Location }
  }
  "clean-cache" {
    Get-ChildItem -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Recurse -File -Filter "*.pyc" | Remove-Item -Force -ErrorAction SilentlyContinue
    if (Test-Path ".pytest_cache") { Remove-Item ".pytest_cache" -Recurse -Force }
    Write-Host "[OK] caches cleaned"
  }
  "clean-data" {
    Write-Host "[WARN] will wipe data/ folder, continuing in 5s (Ctrl+C to cancel)"
    Start-Sleep -Seconds 5
    if (Test-Path "data") {
      Get-ChildItem "data" -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }
    Write-Host "[OK] data/ wiped"
  }
  "clean-all" {
    & "$PSScriptRoot\make.ps1" clean-cache
    if (Test-Path $Venv) { Remove-Item $Venv -Recurse -Force }
    Get-ChildItem -Directory -Filter "*.egg-info" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] all cleaned, run .\make.ps1 setup to re-init"
  }
  "git-status" {
    git status -s
  }
  "check-creds" {
    $env:PYTHONIOENCODING = "utf-8"
    & $Python scripts\check_credentials.py
  }
  default {
    Show-Help
  }
}