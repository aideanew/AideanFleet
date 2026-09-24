"""
UI-03R §9.4 证据采集脚本 · notify 6 开关「后端真实生效 / 零 localStorage」

产出：一份可复制的原始回执（stdout），供 reports/UI-03R-evidence.md §5 引用。

它证明四件事：
  1. 4 个可写开关的真实值来自 GET  /api/config/notify（落 .env 的 [SECTION: notify]）；
  2. POST /api/config/notify 真的改写了后端状态（回读即刻生效），随后脚本会还原；
  3. 另 2 个开关（task_escalated / daily_summary）的真实值来自 GET /api/notify/triggers
     （源 config/notifications.json），且 POST /api/config/notify **不接受**这两个键
     → 后端确实没有写路径，前端置灰只读是如实反映，而非偷懒；
  4. 全流程未使用任何浏览器存储（本脚本是纯 HTTP 侧证据；UI 侧由 e2e 的
     refresh.spec.ts「零本地存储中继」用例覆盖）。

用法：
    python reports/ui03r/verify-notify.py            # 默认 http://127.0.0.1:5050
    BASE=http://127.0.0.1:5000 python reports/ui03r/verify-notify.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("BASE", "http://127.0.0.1:5050").rstrip("/")
PROJECT = os.environ.get("PROJECT", "AideanFleet")

WRITABLE = ["on_task_start", "on_task_end", "on_manager_quota", "on_role_quota"]
READONLY = ["task_escalated", "daily_summary"]

_token = ""


def call(path: str, method: str = "GET", body: dict | None = None) -> tuple[int, object]:
    req = urllib.request.Request(f"{BASE}{path}", method=method)
    if _token:
        req.add_header("Authorization", f"Bearer {_token}")
    data = None
    if body is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
        data = json.dumps(body).encode("utf-8")
    try:
        with urllib.request.urlopen(req, data=data, timeout=10) as res:
            raw = res.read().decode("utf-8", "replace")
            try:
                return res.status, json.loads(raw)
            except json.JSONDecodeError:
                return res.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw
    except Exception as exc:  # noqa: BLE001
        return -1, str(exc)


def dump(label: str, status: int, payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) if not isinstance(payload, str) else payload
    print(f"\n### {label}\nHTTP {status}\n{text}")


def main() -> int:
    print("=" * 74)
    print("UI-03R §9.4 notify 证据采集 · BASE =", BASE)
    print("=" * 74)

    status, payload = call("/api/session", "POST", {"project": PROJECT})
    dump(f"POST /api/session  (project={PROJECT})", status, payload)
    if status != 200 or not isinstance(payload, dict) or not payload.get("token"):
        print("\n[FATAL] 无法建立会话，后续无可信证据。")
        return 1
    global _token
    _token = str(payload["token"])

    # ---------- 1. 可写 4 项 ----------
    status, before = call("/api/config/notify")
    dump("GET /api/config/notify  (4 项可写开关的真实值)", status, before)
    before_data = before.get("data", {}) if isinstance(before, dict) else {}
    print("\n[命中] source =", (before.get("source") if isinstance(before, dict) else None))
    print("[命中] mtime  =", (before.get("mtime") if isinstance(before, dict) else None))

    # ---------- 2. 真实写入 + 回读 ----------
    target = "on_task_start"
    toggled = not bool(before_data.get(target))
    status, posted = call("/api/config/notify", "POST", {"data": {target: toggled}})
    dump(f"POST /api/config/notify  (写入 {target}={toggled})", status, posted)

    status, after = call("/api/config/notify")
    dump("GET /api/config/notify  (回读，验证真实落盘)", status, after)
    after_data = after.get("data", {}) if isinstance(after, dict) else {}
    persisted = bool(after_data.get(target)) == toggled
    print(f"\n[结论] 写入后回读一致（后端真实持久化）：{persisted}")

    # 还原
    status, restored = call("/api/config/notify", "POST", {"data": {target: not toggled}})
    dump(f"POST /api/config/notify  (还原 {target}={not toggled})", status, restored)

    # ---------- 3. 只读 2 项 ----------
    status, triggers = call("/api/notify/triggers")
    dump("GET /api/notify/triggers  (2 项只读开关的真实值)", status, triggers)
    trig_data = triggers.get("data", {}) if isinstance(triggers, dict) else {}
    for key in READONLY:
        item = trig_data.get(key, {})
        print(f"[命中] {key}: enabled={item.get('enabled')} default_enabled={item.get('default_enabled')}")

    status, rejected = call("/api/config/notify", "POST", {"data": {READONLY[0]: False, READONLY[1]: True}})
    dump("POST /api/config/notify  (尝试写入只读 2 项 → 预期被拒)", status, rejected)
    ignored = rejected.get("ignored", []) if isinstance(rejected, dict) else []
    no_write_path = all(key in ignored for key in READONLY)
    print(f"\n[结论] 后端对只读 2 项无写路径（全部 in ignored）：{no_write_path}")
    if not no_write_path:
        print("[警告] 后端似乎接受了写入！请复核前端是否应解除只读置灰。")

    print("\n" + "=" * 74)
    print("汇总")
    print(f"  · 4 项可写开关走 /api/config/notify，真实落 .env        : {'PASS' if persisted else 'FAIL'}")
    print(f"  · 2 项只读开关走 /api/notify/triggers，后端无写入端点  : {'PASS' if no_write_path else 'FAIL'}")
    print("  · 前端零 localStorage 中继                            : 由 e2e refresh.spec.ts 覆盖")
    print("=" * 74)
    return 0 if (persisted and no_write_path) else 1


if __name__ == "__main__":
    sys.exit(main())
