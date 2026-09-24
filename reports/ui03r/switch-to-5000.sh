#!/usr/bin/env bash
#
# ============================================================================
# UI-03R 主题 1（控制台切回 5000 端口）—— 待执行脚本
#
# 当前状态：**挂起（SUSPENDED）**
#   127.0.0.1:5000 被进程 PID 34196 占用（旧版控制台 v3.1.0-launchbus），
#   且存在一条 ESTABLISHED 长连接（对端 PID 48336），说明有真实客户端在用。
#   按工作包 §5 要求「不得自行杀进程」，本脚本**默认只做干跑（dry-run）**，
#   只有显式传入 CONFIRM=yes 才会真正停进程 + 切端口 + 复测。
#
# 用法：
#   1) 先看它准备做什么（不产生任何副作用）：
#        bash reports/ui03r/switch-to-5000.sh
#   2) 用户确认后一键执行：
#        CONFIRM=yes bash reports/ui03r/switch-to-5000.sh
#
# 回滚：脚本结束会打印回滚命令（重启旧控制台）。
# ============================================================================
set -uo pipefail

# ---------- 可覆盖参数 ----------
ROOT="${FLEET_ROOT:-/e/Code/AideanFleet}"
PY="${PYTHON:-C:/Users/EDY/.workbuddy/binaries/python/envs/default/Scripts/python.exe}"
TARGET_PORT="${TARGET_PORT:-5000}"
LOG_FILE="$ROOT/data/console-${TARGET_PORT}.log"
CONFIRM="${CONFIRM:-no}"

cd "$ROOT" || { echo "[FATAL] 无法进入项目根目录：$ROOT"; exit 1; }

hr() { printf '\n%s\n' "------------------------------------------------------------------"; }

echo "UI-03R 主题1 端口切换脚本"
echo "项目根目录 : $ROOT"
echo "Python     : $PY"
echo "目标端口   : $TARGET_PORT"
echo "确认开关   : CONFIRM=$CONFIRM"

hr
echo "[1/6] 探测 ${TARGET_PORT} 端口占用"
NETSTAT_OUT="$(netstat -ano | grep -E "TCP.*:${TARGET_PORT}[[:space:]].*LISTENING" || true)"
if [ -z "$NETSTAT_OUT" ]; then
  echo "端口 ${TARGET_PORT} 当前无人监听 → 无需停进程，直接进入启动步骤。"
  OCCUPY_PID=""
else
  echo "$NETSTAT_OUT"
  OCCUPY_PID="$(echo "$NETSTAT_OUT" | awk '{print $NF}' | head -1)"
  PROC_NAME="$(powershell -NoProfile -Command "(Get-Process -Id ${OCCUPY_PID} -ErrorAction SilentlyContinue).ProcessName" 2>/dev/null | tr -d '\r')"
  echo "占用 PID  : $OCCUPY_PID"
  echo "进程名    : ${PROC_NAME:-未知}"
  ESTAB="$(netstat -ano | grep -E ":${TARGET_PORT}[[:space:]]+.*ESTABLISHED" | head -3 || true)"
  if [ -n "$ESTAB" ]; then
    echo "存在活动连接（停进程会中断它）："
    echo "$ESTAB"
  fi
fi

hr
echo "[2/6] 检查新控制台静态资源是否就绪（dist）"
if [ -f "$ROOT/fleet/console/dist/index.html" ]; then
  echo "OK: fleet/console/dist/index.html 存在（$(date -r fleet/console/dist/index.html '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo 'mtime未知')）"
else
  echo "[FATAL] 缺少 fleet/console/dist/index.html，请先在 fleet/console/web 执行 npm run build"
  exit 1
fi

hr
if [ "$CONFIRM" != "yes" ]; then
  echo "[3/6] 干跑结束（未执行任何有副作用的操作）"
  echo ""
  echo "若确认执行，请重新运行："
  echo "    CONFIRM=yes bash reports/ui03r/switch-to-5000.sh"
  echo ""
  echo "该命令将依次做："
  echo "  a. 强制结束 PID ${OCCUPY_PID:-<无>}（旧版控制台）"
  echo "  b. 以 FLEET_CONSOLE_PORT=${TARGET_PORT} 启动 fleet.console.server，日志写 $LOG_FILE"
  echo "  c. 轮询 /api/health 直到 200"
  echo "  d. 用 E2E_BASE_URL=http://127.0.0.1:${TARGET_PORT} 重跑全部 e2e 用例"
  exit 0
fi

hr
echo "[3/6] 停止旧进程（用户已确认）"
if [ -n "${OCCUPY_PID:-}" ]; then
  powershell -NoProfile -Command "Stop-Process -Id ${OCCUPY_PID} -Force" \
    && echo "已结束 PID $OCCUPY_PID" \
    || { echo "[FATAL] 结束 PID $OCCUPY_PID 失败"; exit 1; }
  sleep 2
  if netstat -ano | grep -qE "TCP.*:${TARGET_PORT}[[:space:]].*LISTENING"; then
    echo "[FATAL] 端口 ${TARGET_PORT} 仍被占用，终止以避免误判"
    exit 1
  fi
  echo "端口 ${TARGET_PORT} 已释放"
else
  echo "无占用进程，跳过"
fi

hr
echo "[4/6] 启动新控制台于 ${TARGET_PORT}"
FLEET_CONSOLE_PORT="$TARGET_PORT" nohup "$PY" -m fleet.console.server > "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "新进程 PID: $NEW_PID，日志: $LOG_FILE"

hr
echo "[5/6] 等待 /api/health 就绪（最多 40s）"
READY=no
for _ in $(seq 1 40); do
  if "$PY" -c "
import urllib.request,sys
try:
    with urllib.request.urlopen('http://127.0.0.1:${TARGET_PORT}/api/health', timeout=2) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
    READY=yes
    break
  fi
  sleep 1
done

if [ "$READY" != "yes" ]; then
  echo "[FATAL] 新控制台未在 40s 内就绪，请查看 $LOG_FILE"
  echo ""
  echo "回滚（重启旧控制台，按你原来的方式启动即可）"
  exit 1
fi
echo "OK: http://127.0.0.1:${TARGET_PORT}/api/health 已返回 200"

hr
echo "[6/6] 在 ${TARGET_PORT} 上重跑全部 e2e 用例"
cd "$ROOT/tests-e2e" || exit 1
E2E_BASE_URL="http://127.0.0.1:${TARGET_PORT}" npx playwright test --grep-invert @mock --reporter=list
E2E_EXIT=$?

hr
echo "e2e 退出码: $E2E_EXIT"
if [ "$E2E_EXIT" -eq 0 ]; then
  echo "主题1 收口成功：控制台已在 ${TARGET_PORT} 端口服务，且全套 e2e 通过。"
else
  echo "e2e 未全绿，请先看上方失败用例；端口切换本身已完成。"
fi
echo ""
echo "回滚方式：结束新进程 PID $NEW_PID，再按原方式启动旧控制台。"
exit "$E2E_EXIT"
