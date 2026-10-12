"""TASK-105：步行骨架 e2e——经 HTTP 建 goal → worker（假模型 + fake harness）→ done → attention 可见。

链路全部走生产代码：kernel_api.goals_create（HTTP）→ run_once → clients.make_planner_client
（假 OpenAI 端点）→ apply_plan → harness（本地 fake profile 子进程）→ gates 真实 verify → attention。
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from fleet.console import server as console_server
from fleet.core import paths as paths_mod
from fleet.runner import worker as worker_mod

PY = sys.executable.replace("\\", "/")


class _FakeOpenAI(BaseHTTPRequestHandler):
    """假 OpenAI 兼容端点：/chat/completions 返回固定计划 JSON。"""

    plan: dict = {}

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        content = json.dumps(self.plan, ensure_ascii=False)
        body = json.dumps({
            "id": "chatcmpl-fake", "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def fake_openai():
    server = HTTPServer(("127.0.0.1", 0), _FakeOpenAI)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()


@pytest.fixture()
def fake_harness(tmp_path, monkeypatch):
    """本地 fake harness profile：写 src/main.py（main()==42）并输出报告。"""
    script = tmp_path / "fake_harness.py"
    script.write_text(
        "import sys, pathlib\n"
        "workspace = pathlib.Path.cwd()\n"
        "(workspace / 'src').mkdir(parents=True, exist_ok=True)\n"
        "(workspace / 'src' / 'main.py').write_text('def main():\\n    return 42\\n', encoding='utf-8')\n"
        "print('FAKE-REPORT: 六节报告\\n改动: src/main.py\\n模型自述: fake')\n",
        encoding="utf-8",
    )
    checker = tmp_path / "checker.py"
    checker.write_text(
        "import importlib.util, pathlib, sys\n"
        "target = pathlib.Path('src/main.py')\n"
        "if not target.is_file():\n"
        "    sys.exit(3)\n"
        "spec = importlib.util.spec_from_file_location('m', target)\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "sys.exit(0 if mod.main() == 42 else 1)\n",
        encoding="utf-8",
    )
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "fakeh.yaml").write_text(
        f"name: fakeh\n"
        f"detect: [\"{PY}\", \"--version\"]\n"
        f"auth_check: [\"{PY}\", \"-c\", \"pass\"]\n"
        f"invoke: [\"{PY}\", \"{str(script).replace(chr(92), '/')}\"]\n"
        f"prompt_via: stdin\n"
        f"model_protocol: none\n"
        f"output_parser: plain\n"
        f"timeout_idle_s: 60\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("fleet.harness.profile.PROFILES_DIR", profiles)
    return {"verify": [f"\"{PY}\" \"{str(checker).replace(chr(92), '/')}\""]}


def _make_plan(base_url: str, verify_cmd: list[str]) -> dict:
    return {
        "milestones": [{"id": "M1", "title": "可运行骨架"}],
        "todos": [
            {"id": "T1", "milestone": "M1", "title": "实现 main", "role": "fe-1",
             "depends_on": [], "allowed_files": ["**"], "verify": verify_cmd,
             "done_when": "main() == 42"},
        ],
    }


def test_walking_skeleton_goal_to_done_via_http(fleet_env, project, client, fake_openai, fake_harness, monkeypatch):
    """REQ-F-03/REQ-F-04：HTTP 建 goal → 自动计划 → 执行 → 验收 → attention 可见。"""
    workspace = fleet_env["root"] / "ws"
    workspace.mkdir()
    _FakeOpenAI.plan = _make_plan(fake_openai, fake_harness["verify"])

    # fleet.toml：planner 模型（假端点）+ fe-1 的 harness 链（fakeh）
    (fleet_env["root"] / "fleet.toml").write_text(
        f'[models.fake]\n'
        f'base_url = "{fake_openai}"\n'
        f'model_id = "fake-1"\n'
        f'api_key_env = "FAKE_KEY"\n\n'
        f'[roles.planner]\n'
        f'models = ["fake"]\n\n'
        f'[roles.fe-1]\n'
        f'harness = ["fakeh"]\n'
        f'models = ["fake"]\n\n'
        f'[workspace]\n'
        f'allowed_roots = ["{str(fleet_env["root"]).replace(chr(92), "/")}"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("FAKE_KEY", "k" * 8)

    started = time.monotonic()
    response = client.post("/api/kernel/goals", json={
        "title": "实现返回 42 的程序",
        "requirements": "实现一个 main()==42 的 Python 程序",
        "workspace": str(workspace),
    }, headers={"Idempotency-Key": "ws-1"})
    assert response.status_code == 200, response.text
    payload = response.json()
    goal_id, plan_todo_id = payload["goal"]["id"], payload["plan_todo_id"]

    # worker 循环（生产 run_once/transition 链）至 goal 完成
    from fleet.kernel import Kernel
    from fleet.cli import clients

    kernel = Kernel(paths_mod.paths().data_dir / "kernel.db")
    planner_client = clients.make_planner_client("planner")
    rounds = 0
    while rounds < 20:
        rounds += 1
        outcome = worker_mod.run_once(
            kernel, worker="e2e-worker",
            planner_client=planner_client,
            model_for=clients.model_for,
            workspace_root=str(workspace),
        )
        if outcome["action"] != "writeback":
            time.sleep(0.05)
            continue
        kernel.transition(outcome["todo"], outcome["result"])
        statuses = {t["status"] for t in kernel.todos(goal_id)}
        if statuses == {"done"}:
            break
    elapsed = time.monotonic() - started
    assert elapsed < 60, f"步行骨架超时（{elapsed:.1f}s）"

    # attention 断言：done_recent 含子 todo，blocked==0
    view = client.get("/api/kernel/attention").json()
    assert view["ok"] is True
    assert view["counts"]["blocked"] == 0, view["blocked"]
    done_ids = {t["id"] for t in view["done_recent"]}
    assert plan_todo_id in done_ids
    exec_todos = [t for t in kernel.todos(goal_id) if t["kind"] == "exec"]
    assert exec_todos and all(t["id"] in done_ids for t in exec_todos)

    # 证据链：gate.json 存在且 ok=true（A5：完成必须可信）
    for todo in exec_todos:
        gate_file = paths_mod.paths().data_dir / "evidence" / todo["id"] / "gate.json"
        assert gate_file.is_file()
        assert json.loads(gate_file.read_text(encoding="utf-8"))["ok"] is True

    # todo 详情 API：attempts 记录了 fakeh
    detail = client.get(f"/api/kernel/todos/{exec_todos[0]['id']}").json()
    assert detail["attempts"] and detail["attempts"][0]["harness"] == "fakeh"
