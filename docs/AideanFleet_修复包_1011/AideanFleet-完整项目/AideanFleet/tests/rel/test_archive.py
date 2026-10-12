"""归档连续性测试（REL-01 §9.4）：月度轮转后 seq 全局连续、热文件重建、read_all 穿透归档、幂等重跑。"""

from __future__ import annotations

import gzip
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from fleet.core import events
from fleet.core.paths import paths
from fleet.rel import archive

from tests.rel.conftest import read_events

NOW = datetime(2026, 9, 15).astimezone()


def _seed_events(count: int, *, project: str = "P-001") -> list[int]:
    return [
        events.append(actor="tester", action="test:seed", summary=f"第 {i} 条", project=project)["seq"]
        for i in range(count)
    ]


def _rewrite_hot_timestamps(assign: dict[int, str]) -> None:
    """把热文件里指定 seq 的 timestamp 改写为给定 ISO 时间（模拟"上月数据"后再走真实轮转逻辑）。

    注意：真实运行绝不会改写事件；这里只用于测试造数。
    """
    target = events.events_file()
    rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        if row["seq"] in assign:
            row["timestamp"] = assign[row["seq"]]
    target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    events._CACHE["size"] = -1
    events._CACHE["seq"] = 0


def _force_task_done(task_id: str, updated_at: str) -> None:
    with sqlite3.connect(str(paths().db_file)) as conn:
        conn.execute("UPDATE tasks SET exec_status='DONE', updated_at=? WHERE task_id=?", (updated_at, task_id))
        conn.commit()


def test_rotate_moves_last_month_keeps_seq_continuous(fleet_env):
    """上月事件轮转进 gz，热文件只留锚点，全局 seq 连续无空洞，轮转后追加 seq 顺延。"""
    _seed_events(5)
    _rewrite_hot_timestamps({seq: "2026-08-01T00:00:00+08:00" for seq in range(1, 6)})

    result = archive.rotate_events(now=NOW)

    assert result["rotated"] == 5
    assert result["marker_seq"] == 6  # 锚点事件占住第 6 位
    assert len(result["archives"]) == 1 and result["archives"][0]["month"] == "202608"

    # 归档文件内容逐字保留
    gz = Path(result["archives"][0]["file"])
    with gzip.open(gz, "rt", encoding="utf-8") as handle:
        archived = [json.loads(line) for line in handle]
    assert [row["seq"] for row in archived] == [1, 2, 3, 4, 5]

    # 热文件只剩锚点
    hot = read_events()
    assert [row["seq"] for row in hot] == [6]
    assert hot[0]["action"] == "rel:archived"

    # 轮转后继续追加：seq 全局连续
    new_seq = events.append(actor="tester", action="test:after", summary="轮转后新增")["seq"]
    assert new_seq == 7

    continuity = archive.verify_continuity()
    assert continuity["ok"] is True
    assert continuity["count"] == 7 and continuity["max"] == 7
    assert continuity["gaps"] == [] and continuity["duplicates"] == []


def test_rotate_noop_when_all_current_month(fleet_env):
    """全部是当月事件：轮转 no-op（幂等），不产生锚点、不改热文件。"""
    _seed_events(3)
    before = read_events()
    result = archive.rotate_events(now=NOW)
    assert result["rotated"] == 0 and result["archives"] == []
    assert read_events() == before


def test_rotate_idempotent_rerun(fleet_env):
    """轮转后立即重跑：没有上月数据可搬，no-op；归档文件不重复。"""
    _seed_events(4)
    _rewrite_hot_timestamps({seq: "2026-07-01T00:00:00+08:00" for seq in range(1, 5)})
    first = archive.rotate_events(now=NOW)
    second = archive.rotate_events(now=NOW)
    assert first["rotated"] == 4 and second["rotated"] == 0
    assert len(archive.archived_files()) == 1
    assert archive.verify_continuity()["ok"] is True


def test_read_all_merges_archives_and_hot_in_seq_order(fleet_env):
    """read_all 穿透归档：归档行 + 热行按 seq 全序合并；热数据接口 events.read 只查热文件。"""
    _seed_events(4)
    _rewrite_hot_timestamps({seq: "2026-07-01T00:00:00+08:00" for seq in range(1, 5)})
    archive.rotate_events(now=NOW)
    _seed_events(2)  # 热区新增 seq 6、7（锚点 5 + 2 行）

    everything = archive.read_all()
    assert [row["seq"] for row in everything] == [1, 2, 3, 4, 5, 6, 7]
    assert [row["seq"] for row in events.read()] == [5, 6, 7]  # 热数据语义：只查热文件

    since_5 = archive.read_all(since=5)
    assert [row["seq"] for row in since_5] == [6, 7]


def test_multi_month_rotation_keeps_current_month_rows(fleet_env):
    """混合月份：只有旧月被搬走，当月行（含锚点之后）留在热文件。"""
    _seed_events(5)
    _rewrite_hot_timestamps({1: "2026-06-01T00:00:00+08:00", 2: "2026-06-01T00:00:00+08:00", 3: "2026-08-01T00:00:00+08:00"})

    result = archive.rotate_events(now=NOW)

    assert result["rotated"] == 3 and result["marker_seq"] == 6
    months = {item["month"] for item in result["archives"]}
    assert months == {"202606", "202608"}
    continuity = archive.verify_continuity()
    assert continuity["ok"] is True and continuity["max"] == 6
    assert [row["seq"] for row in events.read()] == [4, 5, 6]  # 当月 4、5 留在热区 + 锚点 6


def test_archive_evidence_zips_terminal_tasks(fleet_env, tmp_path):
    """evidence 归档：终态且超期 -> zip + 删源 + manifest 记账 + 事件；未超期不动；重跑幂等。"""
    from tests.core.stubs import make_task

    workspace = tmp_path / "ws"
    workspace.mkdir()
    make_task("P-001", "T-EV1", workspace=str(workspace))
    dir1 = paths().evidence_dir("P-001", "T-EV1")
    dir1.mkdir(parents=True, exist_ok=True)
    (dir1 / "report.md").write_text("# 六节报告\n证据", encoding="utf-8")
    (dir1 / "gate").mkdir()
    (dir1 / "gate" / "stdout.txt").write_text("ok", encoding="utf-8")
    _force_task_done("T-EV1", "2026-07-01T00:00:00+08:00")

    make_task("P-001", "T-EV2", workspace=str(workspace))
    dir2 = paths().evidence_dir("P-001", "T-EV2")
    dir2.mkdir(parents=True, exist_ok=True)
    (dir2 / "report.md").write_text("近期", encoding="utf-8")
    _force_task_done("T-EV2", "2026-09-14T00:00:00+08:00")  # 未超期

    result = archive.archive_evidence(older_than_days=30, now=NOW)

    assert result["archived"] == 1
    entry = result["entries"][0]
    assert entry["taskId"] == "T-EV1"
    assert Path(entry["zip"]).exists() and not dir1.exists()  # zip 成功且源目录已删
    assert dir2.exists()  # 未超期不动
    manifest = json.loads((archive.evidence_archive_dir() / "manifest.json").read_text(encoding="utf-8"))
    assert manifest[0]["taskId"] == "T-EV1" and len(manifest[0]["files"]) == 2
    assert any(row["action"] == "rel:evidence_archived" for row in read_events())

    # 重跑幂等：不再归档
    assert archive.archive_evidence(older_than_days=30, now=NOW)["archived"] == 0
