"""P3-A-1: stream_chunk 端到端测试

验证 FakeAdapter.run_stream → dispatcher._run_with_chain → events 中出现 task:stream_chunk。
"""
import pathlib

from fleet.core import db, events, config
from fleet.executors.fake import FakeAdapter
from fleet.manager import contracts, dispatcher
from fleet.models.retry import policy as default_policy

import sys
sys.path.insert(0, "tests/core")
from stubs import pass_route


def test_stream_chunk_e2e(fleet_env, monkeypatch):
    """FakeAdapter run_stream → dispatcher → events 中有 stream_chunk 事件。"""
    config.allow_write(True)
    db.init_db()

    project_id = "StreamChunkE2E"
    workspace = fleet_env["root"] / project_id
    workspace.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FLEET_ALLOWED_ROOTS", str(fleet_env["root"]))

    adapter = FakeAdapter()
    contracts.register("fake-stream-test", adapter)

    db.create_project(project_id, project_id, str(workspace))
    task = db.create_task({
        "project_id": project_id,
        "task_id": f"{project_id}-T01",
        "title": "流式测试任务",
        "detail": "测试 stream_chunk",
        "assignee": "fake-stream-test",
        "reviewer": "reviewer-1",
        "verify_cmd": "python -c \"import pathlib,sys; sys.exit(0 if pathlib.Path('docs/design.md').exists() else 1)\"",
        "workspace": str(workspace),
        "allowed_files": "docs/**",
    })

    dispatcher.ensure_paths(task)

    # 直接调 _run_with_chain（与 P1-A-3 复验方式一致）
    result, info = dispatcher._run_with_chain(
        adapter=adapter,
        prompt="标题: 流式测试任务\n4. 原样运行机器门命令：python -c \"import pathlib,sys; sys.exit(0)\"",
        workspace=str(workspace),
        assignee="fake-stream-test",
        policy=default_policy(),
        project=project_id,
        task_id=f"{project_id}-T01",
    )

    assert result.ok, f"Expected ok result, got: {result.error_msg}"

    rows = events.read(project=project_id)
    chunk_events = [r for r in rows if r.get("action") == "task:stream_chunk"]
    assert len(chunk_events) >= 1, f"Expected stream_chunk events, got {len(chunk_events)}"
    assert len(chunk_events) == 3, f"Expected 3 chunks, got {len(chunk_events)}"
