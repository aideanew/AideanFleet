@echo off
rem AideanFleet 启动器（快捷方式目标，TASK-201）
rem 用私有 Python 拉起 api + worker 并自动打开浏览器（/setup 或 /tasks）
setlocal
set HERE=%~dp0
set PYTHON=%HERE%runtime\python\python.exe
if not exist "%PYTHON%" (
  echo 私有 Python 不存在，请重新运行安装器修复。
  pause
  exit /b 1
)
set FLEET_DATA_DIR=%LOCALAPPDATA%\AideanFleet\data
rem N4: wheel 装进 site-packages 后 paths().root 缺 .env.example（ConfigError 链）。
rem FLEET_ROOT 指回安装目录，配合 .iss 拷入的 .env.example 完成首启初始化。
set FLEET_ROOT=%HERE%
set PATH=%HERE%runtime\node;%HERE%npm-global;%PATH%
"%PYTHON%" -m fleet.cli.main up --open %*
if errorlevel 1 (
  echo.
echo 启动失败，请查看 %FLEET_DATA_DIR%\logs\ 下日志。
  pause
)
endlocal
