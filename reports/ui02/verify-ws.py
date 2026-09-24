"""UI-02 验证用：WS 契约 + 实时延迟实测（不改动任何产品文件，仅本地验证）。"""
import asyncio
import json
import sys
import time

import websockets

BASE = "http://127.0.0.1:5050"
TOKEN = sys.argv[1]


async def main() -> int:
    uri = f"ws://127.0.0.1:5050/ws?token={TOKEN}"
    results = []
    async with websockets.connect(uri) as ws:
        # 1) 客户端 -> 服务端：chat（应立刻收到 chat_message）
        t0 = time.perf_counter()
        await ws.send(json.dumps({"type": "chat", "project": "AideanFleet", "message": "UI-02 实时链路验证"}))
        got_chat = None
        deadline = time.perf_counter() + 5
        while time.perf_counter() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            if msg.get("type") == "chat_message" and (msg.get("event") or {}).get("action") == "chat":
                got_chat = msg
                break
        dt_chat = (time.perf_counter() - t0) * 1000
        results.append(("chat -> chat_message", bool(got_chat), f"{dt_chat:.0f} ms"))

        # 2) set_mode -> notification(mode)
        t0 = time.perf_counter()
        await ws.send(json.dumps({"type": "set_mode", "mode": "step", "actor": "UI-02"}))
        got_mode = None
        deadline = time.perf_counter() + 5
        while time.perf_counter() < deadline:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if msg.get("type") == "notification" and msg.get("mode"):
                got_mode = msg
                break
        dt_mode = (time.perf_counter() - t0) * 1000
        results.append(("set_mode -> notification(mode)", got_mode is not None and got_mode.get("mode") == "step", f"{dt_mode:.0f} ms, mode={got_mode and got_mode.get('mode')}"))

        # 3) confirm_step -> notification(event)
        t0 = time.perf_counter()
        await ws.send(json.dumps({"type": "confirm_step", "taskId": "T-001", "note": "UI-02 人工确认"}))
        got_confirm = None
        deadline = time.perf_counter() + 5
        while time.perf_counter() < deadline:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if msg.get("type") == "notification" and msg.get("event"):
                got_confirm = msg
                break
        dt_confirm = (time.perf_counter() - t0) * 1000
        results.append(("confirm_step -> notification(event)", bool(got_confirm), f"{dt_confirm:.0f} ms"))

        # 4) 未知类型 -> notification(error)，不得静默丢弃
        await ws.send(json.dumps({"type": "bogus_kind"}))
        got_err = None
        deadline = time.perf_counter() + 5
        while time.perf_counter() < deadline:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if msg.get("type") == "notification" and msg.get("error"):
                got_err = msg
                break
        results.append(("unknown type -> notification(error)", bool(got_err), str(got_err and got_err.get("error"))))

        # 5) 非法 JSON -> notification(error)，连接不断
        await ws.send("not-a-json")
        got_bad = None
        deadline = time.perf_counter() + 5
        while time.perf_counter() < deadline:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if msg.get("type") == "notification" and msg.get("error"):
                got_bad = msg
                break
        results.append(("invalid json -> notification(error)", bool(got_bad), str(got_bad and got_bad.get("error"))))

    print("=== WS 契约与实时延迟实测 ===")
    ok_all = True
    for name, ok, detail in results:
        ok_all = ok_all and ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name:38s} {detail}")
    print("=== 结论:", "全部通过" if ok_all else "存在失败项", "===")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
