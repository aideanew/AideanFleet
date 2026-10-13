"""P4 模型直写执行路径（runner/model_write.py）单测：
协议解析（围栏容错/坏 JSON/未知 op）· 三重边界（绝对路径/../symlink 逃逸/allowed_files）·
原子落盘（整批拒绝不写半套）· worker 接线（exec 无 harness + 有 client → model-write → 机器门 → done）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from fleet.kernel import Kernel
from fleet.kernel import state as st
from fleet.runner import model_write as mw
from fleet.runner import worker as worker_mod

PY = sys.executable.replace("\\", "/")


def _client(reply, capture=None):
    def client(prompt: str) -> str:
        if capture is not None:
            capture.append(prompt)
        return reply
    return client


OPS_OK = json.dumps({
    "ops": [{"op": "write", "path": "src/main.py", "content": "def main():\n    return 42\n"}],
    "report": "改动: src/main.py",
}, ensure_ascii=False)


def _ops(path: str, content: str = "x") -> str:
    return json.dumps({"ops": [{"op": "write", "path": path, "content": content}],
                       "report": ""}, ensure_ascii=False)


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("当前环境无法创建 symlink（Windows 需开发者模式/管理员）")


# ---------- 协议 ----------

def test_write_ops_applied(tmp_path):
    out = mw.run_model_write("prompt", str(tmp_path), _client(OPS_OK), allowed_files=["src/**"])
    assert out.ok and out.exit_code == 0 and out.error_code is None
    assert (tmp_path / "src" / "main.py").read_text(encoding="utf-8") == "def main():\n    return 42\n"


def test_protocol_block_appended_to_prompt(tmp_path):
    cap: list[str] = []
    out = mw.run_model_write("基础提示", str(tmp_path), _client(OPS_OK, cap), allowed_files=["src/**"])
    assert out.ok and len(cap) == 1
    assert "基础提示" in cap[0] and "写回协议" in cap[0]


def test_fenced_reply_parsed(tmp_path):
    reply = "好的，改动如下：\n```json\n" + OPS_OK + "\n```\n以上。"
    out = mw.run_model_write("p", str(tmp_path), _client(reply), allowed_files=["src/**"])
    assert out.ok


def test_bad_json_is_protocol_error(tmp_path):
    out = mw.run_model_write("p", str(tmp_path), _client("抱歉，我无法给出 JSON"), allowed_files=["**"])
    assert not out.ok and out.error_code == "MODEL_PROTOCOL"


def test_unknown_op_rejected(tmp_path):
    out = mw.run_model_write("p", str(tmp_path), _client(_ops("a.py") .replace('"write"', '"delete"')),
                             allowed_files=["**"])
    assert not out.ok and out.error_code == "MODEL_PROTOCOL"


def test_empty_ops_rejected(tmp_path):
    out = mw.run_model_write("p", str(tmp_path), _client(json.dumps({"ops": [], "report": ""})),
                             allowed_files=["**"])
    assert not out.ok and out.error_code == "MODEL_PROTOCOL"


def test_client_exception_is_observable(tmp_path):
    def boom(prompt: str) -> str:
        raise RuntimeError("连接失败")
    out = mw.run_model_write("p", str(tmp_path), boom, allowed_files=["**"])
    assert not out.ok and out.error_code == "MODEL_PROTOCOL" and "连接失败" in out.error_msg


# ---------- 边界三重校验 ----------

def test_absolute_path_rejected(tmp_path):
    out = mw.run_model_write("p", str(tmp_path), _client(_ops("/etc/evil.py")), allowed_files=["**"])
    assert not out.ok and out.error_code == "MODEL_OUT_OF_SCOPE"
    out2 = mw.run_model_write("p", str(tmp_path), _client(_ops("C:/evil.py")), allowed_files=["**"])
    assert not out2.ok and out2.error_code == "MODEL_OUT_OF_SCOPE"


def test_dotdot_rejected(tmp_path):
    out = mw.run_model_write("p", str(tmp_path), _client(_ops("src/../../evil.py")), allowed_files=["**"])
    assert not out.ok and out.error_code == "MODEL_OUT_OF_SCOPE"
    assert not (tmp_path.parent / "evil.py").exists()


def test_symlink_parent_escape_rejected(tmp_path):
    outside = tmp_path.parent / "outside_dir"
    outside.mkdir(exist_ok=True)
    _symlink_or_skip(tmp_path / "link", outside)
    out = mw.run_model_write("p", str(tmp_path), _client(_ops("link/evil.py")), allowed_files=["**"])
    assert not out.ok and out.error_code == "MODEL_OUT_OF_SCOPE"
    assert not (outside / "evil.py").exists()


def test_symlink_target_rejected(tmp_path):
    real = tmp_path / "real.txt"
    real.write_text("原文件", encoding="utf-8")
    _symlink_or_skip(tmp_path / "linked.txt", real)
    out = mw.run_model_write("p", str(tmp_path), _client(_ops("linked.txt", "篡改")), allowed_files=["**"])
    assert not out.ok and out.error_code == "MODEL_OUT_OF_SCOPE"
    assert real.read_text(encoding="utf-8") == "原文件"


def test_allowed_files_mismatch_rejected(tmp_path):
    out = mw.run_model_write("p", str(tmp_path), _client(_ops("src/x.py")), allowed_files=["docs/**"])
    assert not out.ok and out.error_code == "MODEL_OUT_OF_SCOPE"
    assert not (tmp_path / "src" / "x.py").exists()


def test_allowed_files_match_ok(tmp_path):
    out = mw.run_model_write("p", str(tmp_path), _client(_ops("docs/readme.md", "# d")), allowed_files=["docs/**"])
    assert out.ok and (tmp_path / "docs" / "readme.md").read_text(encoding="utf-8") == "# d"


def test_empty_allowed_files_refuses_everything(tmp_path):
    out = mw.run_model_write("p", str(tmp_path), _client(OPS_OK), allowed_files=[])
    assert not out.ok and out.error_code == "MODEL_OUT_OF_SCOPE"


# ---------- 原子性 ----------

def test_batch_atomic_no_partial_write(tmp_path):
    reply = json.dumps({"ops": [
        {"op": "write", "path": "src/ok.py", "content": "ok"},
        {"op": "write", "path": "src/../../evil.py", "content": "evil"},
    ], "report": ""}, ensure_ascii=False)
    out = mw.run_model_write("p", str(tmp_path), _client(reply), allowed_files=["**"])
    assert not out.ok and out.error_code == "MODEL_OUT_OF_SCOPE"
    assert not (tmp_path / "src" / "ok.py").exists()  # 整批拒绝：合法 op 也不落盘


# ---------- worker 接线 ----------

def _checker_cmd(tmp_path: Path) -> list[str]:
    checker = tmp_path / "checker.py"
    checker.write_text(
        "import importlib.util, pathlib, sys\n"
        "target = pathlib.Path('src/main.py')\n"
        "if not target.is_file():\n    sys.exit(3)\n"
        "spec = importlib.util.spec_from_file_location('m', target)\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "sys.exit(0 if mod.main() == 42 else 1)\n",
        encoding="utf-8",
    )
    return [f"\"{PY}\" \"{str(checker).replace(chr(92), '/')}\""]


def test_run_once_model_write_fallback_to_done(tmp_path, monkeypatch):
    """exec：harness 链全不可用 + 注入模型客户端 → 模型直写 → 真实机器门 → done（attempts 记 model-write）。"""
    monkeypatch.setattr(worker_mod, "_harness_chain_for", lambda role: ["no-such-harness"])
    kernel = Kernel(tmp_path / "kernel.db", lease_seconds=60)
    ws = tmp_path / "ws"
    ws.mkdir()
    gid = kernel.create_goal("g")
    tid = kernel.create_todo(gid, title="实现 main", role="fe-1",
                             allowed_files=["src/**"], verify=_checker_cmd(tmp_path), workspace=str(ws))
    outcome = worker_mod.run_once(kernel, worker="w1", planner_client=_client(OPS_OK))
    assert outcome["action"] == "writeback"
    kernel.transition(tid, outcome["result"])
    assert kernel.get_todo(tid)["status"] == st.DONE
    attempts = kernel.attempts_of(tid)
    assert attempts and attempts[0]["harness"] == "model-write"
    gate_json = tmp_path / "evidence" / tid / "gate.json"
    assert gate_json.is_file() and json.loads(gate_json.read_text(encoding="utf-8"))["ok"] is True


def test_run_once_out_of_scope_write_blocks(tmp_path, monkeypatch):
    """越界写（未命中 allowed_files）→ 整批拒绝 → blocked；文件未落盘。"""
    monkeypatch.setattr(worker_mod, "_harness_chain_for", lambda role: ["no-such-harness"])
    kernel = Kernel(tmp_path / "kernel.db", lease_seconds=60)
    ws = tmp_path / "ws"
    ws.mkdir()
    gid = kernel.create_goal("g")
    tid = kernel.create_todo(gid, title="只许改 docs", role="fe-1",
                             allowed_files=["docs/**"], verify=[f"\"{PY}\" -c \"pass\""],
                             workspace=str(ws))
    outcome = worker_mod.run_once(kernel, worker="w1", planner_client=_client(OPS_OK))
    kernel.transition(tid, outcome["result"])
    assert kernel.get_todo(tid)["status"] == st.BLOCKED
    assert not (ws / "src" / "main.py").exists()


def test_run_once_no_harness_no_client_still_blocks(tmp_path, monkeypatch):
    """无 harness 且无客户端：保持既有 blocked 语义（备注含"未配置模型直写回退"）。"""
    monkeypatch.setattr(worker_mod, "_harness_chain_for", lambda role: ["no-such-harness"])
    kernel = Kernel(tmp_path / "kernel.db", lease_seconds=60)
    ws = tmp_path / "ws"
    ws.mkdir()
    gid = kernel.create_goal("g")
    tid = kernel.create_todo(gid, title="t", role="fe-1", verify=["x"], workspace=str(ws))
    outcome = worker_mod.run_once(kernel, worker="w1")  # 不注入 planner_client
    kernel.transition(tid, outcome["result"])
    assert kernel.get_todo(tid)["status"] == st.BLOCKED
    notes = []
    for e in kernel.pending_events(100):
        if e["kind"] == "todo:blocked":
            notes.append(json.loads(e.get("payload") or "{}").get("note") or "")
    assert any("未配置模型直写回退" in n for n in notes)
