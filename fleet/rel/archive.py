"""这是什么：events.jsonl 月度轮转 + 证据目录归档 + seq 连续性校验（REL-01 §9.4）。
语义冻结（docs/契约/控制台API.md §14 增补注记，与角色D 对齐）：
  · events.read / read_events_since 只查热数据（data/events.jsonl）；归档数据走报表通道
    fleet.rel.archive.read_all()（按 seq 全序合并归档与热数据）。
  · 轮转锚点：归档前先写一条 rel:archived 事件占住当前最大 seq，随后热文件只保留
    seq >= 锚点的事件——因此热文件重建后 events.append 的 seq 依然全局连续。
  · 治理层 usage 聚合读 SQLite（governance_usage 表），不经 events.jsonl，归档不影响其口径。
铁律：本模块绝不修改任何事件行的内容，只做"搬移到归档 + 重建热文件"，且全程持有 events._LOCK。
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fleet.core import db, events
from fleet.core.paths import paths

#: 归档根目录名（data/archive/）
ARCHIVE_DIR_NAME = "archive"

#: 证据归档默认门槛：任务终态（DONE/PARTIAL）且 updated_at 早于该天数才归档
EVIDENCE_OLDER_THAN_DAYS = 30


def archive_dir() -> Path:
    """归档根目录：data/archive/。"""
    return paths().data_dir / ARCHIVE_DIR_NAME


def evidence_archive_dir() -> Path:
    """证据归档目录：data/archive/evidence/。"""
    return archive_dir() / "evidence"


def _month_of(row: dict[str, Any]) -> str:
    """从事件 timestamp（ISO-8601）取 YYYYMM；无法解析返回空串。"""
    ts = str(row.get("timestamp") or "")
    if len(ts) >= 7 and ts[4] == "-":
        return ts[:7].replace("-", "")
    return ""


def _gz_path(month: str) -> Path:
    return archive_dir() / f"events-{month}.jsonl.gz"


def _existing_seqs(path: Path) -> set[int]:
    """读取归档文件里已有的 seq 集合（中断重跑幂等：绝不重复归档同一行）。"""
    existing: set[int] = set()
    if not path.exists():
        return existing
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            try:
                existing.add(int(json.loads(line).get("seq") or 0))
            except (json.JSONDecodeError, ValueError):
                continue
    return existing


def rotate_events(*, now: datetime | None = None) -> dict[str, Any]:
    """把"已完成月份"的事件从热文件搬进 data/archive/events-YYYYMM.jsonl.gz。

    步骤（全程持有 events._LOCK，与 append 互斥）：
      1) 扫热文件，取时间戳月份 < 当前月的行；没有则原样返回（幂等）。
      2) 先写锚点事件 rel:archived（拿到当前最大 seq）。
      3) 把 seq < 锚点 的行按月分组压缩进归档（已有同 seq 行则跳过，幂等）。
      4) 热文件原子重建为 seq >= 锚点 的行，并失效 events 读缓存。
    返回统计 dict；绝不修改任何事件行内容。
    """
    current = (now or datetime.now().astimezone()).strftime("%Y%m")
    target = events.events_file()
    if not target.exists():
        return {"rotated": 0, "archives": [], "marker_seq": 0, "hot_rows": 0}

    # 先无锁扫描判断是否有可归档数据（events._LOCK 非重入，append 会自取锁，绝不能锁内调用）
    rows = events._iter_rows(target)
    stale = [row for row in rows if _month_of(row) and _month_of(row) < current]
    if not stale:
        return {"rotated": 0, "archives": [], "marker_seq": 0, "hot_rows": len(rows)}

    months = sorted({_month_of(row) for row in stale})
    marker = events.append(
        actor="rel",
        action="rel:archived",
        summary=f"事件归档：{len(stale)} 行转入 {','.join(months)}",
        extra={"months": months, "rows": len(stale)},
    )
    marker_seq = int(marker["seq"])

    with events._LOCK:
        # 持锁重扫：锚点之前（seq < 锚点）的行归档；当月行与锚点及以后一律留在热文件
        rows_now = events._iter_rows(target)
        gone = [
            row
            for row in rows_now
            if int(row.get("seq") or 0) < marker_seq and (_month_of(row) or "999999") < current
        ]
        gone_seqs = {int(row.get("seq") or 0) for row in gone}
        keep = [row for row in rows_now if int(row.get("seq") or 0) not in gone_seqs]

        written: list[dict[str, Any]] = []
        for month in sorted({_month_of(row) for row in gone}):
            batch = sorted((row for row in gone if _month_of(row) == month), key=lambda row: int(row["seq"]))
            path = _write_gz(month, batch)
            written.append({"file": str(path), "rows": len(batch), "month": month})

        tmp = target.with_name(target.name + ".rotating")
        tmp.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in keep), encoding="utf-8")
        os.replace(tmp, target)
        events._CACHE["size"] = -1  # 强制下次 max_seq 重扫
        events._CACHE["seq"] = 0

    return {"rotated": len(gone), "archives": written, "marker_seq": marker_seq, "hot_rows": len(keep)}


def _write_gz(month: str, batch: list[dict[str, Any]]) -> Path:
    path = _gz_path(month)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _existing_seqs(path)
    fresh = [row for row in batch if int(row.get("seq") or 0) not in existing]
    with gzip.open(path, "at", encoding="utf-8") as handle:
        for row in fresh:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def archived_files() -> list[Path]:
    """归档文件列表（按月份名排序，即按时间序）。"""
    root = archive_dir()
    if not root.is_dir():
        return []
    return sorted(root.glob("events-*.jsonl.gz"))


def read_all(
    project: str | None = None,
    since: int = 0,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """全量读取（归档 + 热数据），按 seq 升序合并。报表/角色D 长期聚合走这里。"""
    rows: list[dict[str, Any]] = []
    for path in archived_files():
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    rows.extend(events.read(project=project, since=since))
    threshold = int(since or 0)
    merged = [
        row
        for row in rows
        if int(row.get("seq") or 0) > threshold and (project is None or row.get("project") == project)
    ]
    merged.sort(key=lambda row: int(row.get("seq") or 0))
    if limit is not None and limit >= 0:
        merged = merged[-int(limit):] if limit else []
    return merged


def verify_continuity() -> dict[str, Any]:
    """校验全局 seq 连续性（归档 + 热数据合并后必须无空洞、无重复、从 1 开始）。"""
    rows = read_all()
    seqs = sorted(int(row.get("seq") or 0) for row in rows if row.get("seq") is not None)
    duplicates = sorted({seq for seq in seqs if seqs.count(seq) > 1})
    unique = sorted(set(seqs))
    gaps = [seq for seq in range(1, (unique[-1] if unique else 0) + 1) if seq not in set(unique)]
    return {
        "min": unique[0] if unique else 0,
        "max": unique[-1] if unique else 0,
        "count": len(unique),
        "gaps": gaps,
        "duplicates": duplicates,
        "ok": not gaps and not duplicates and (unique[0] == 1 if unique else True),
    }


def archive_evidence(
    *,
    older_than_days: int = EVIDENCE_OLDER_THAN_DAYS,
    now: datetime | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    """把已完成任务（DONE/PARTIAL）的 evidence 目录按完成月份压缩归档。

    只动终态任务（终态无出边，机器门不会再读其 baseline）；zip 成功才删源目录，
    并在 data/archive/evidence/manifest.json 追加一条记录（含原路径与文件清单）。
    """
    cutoff = (now or datetime.now().astimezone()) - timedelta(days=older_than_days)
    manifest_path = evidence_archive_dir() / "manifest.json"
    manifest: list[dict[str, Any]] = []
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = []
    done_ids = {entry.get("taskId") for entry in manifest}

    results: list[dict[str, Any]] = []
    for task in db.list_tasks(db_file=db_file):
        if task.get("exec_status") not in ("DONE", "PARTIAL"):
            continue
        task_id = str(task["task_id"])
        if task_id in done_ids:
            continue
        updated = str(task.get("updated_at") or "")
        try:
            if datetime.fromisoformat(updated) >= cutoff:
                continue
        except ValueError:
            continue
        source = paths().evidence_dir(str(task.get("project_id") or "unassigned"), task_id)
        if not source.is_dir():
            continue
        month = updated[:7].replace("-", "") or "unknown"
        zip_path = evidence_archive_dir() / f"{task_id}-{month}.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        files: list[str] = []
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as bundle:
            for item in sorted(source.rglob("*")):
                if item.is_file():
                    bundle.write(item, item.relative_to(source))
                    files.append(str(item.relative_to(source)))
        if len(files) == 0:  # 空目录不值得归档
            zip_path.unlink(missing_ok=True)
            continue
        shutil.rmtree(source)
        entry = {"taskId": task_id, "zip": str(zip_path), "files": files, "archived_at": db.iso_now()}
        manifest.append(entry)
        events.append(
            actor="rel",
            action="rel:evidence_archived",
            task_id=task_id,
            summary=f"{task_id} 证据目录已归档（{len(files)} 个文件 -> {zip_path.name}）",
            extra={"zip": str(zip_path), "files": len(files)},
        )
        results.append(entry)

    if results:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"archived": len(results), "entries": results}
