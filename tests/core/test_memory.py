# 这是什么：Project Memory 单测（CORE-04 · 契约 v1.2 §13.3）。
# 目的：验证条目 schema 冻结、三类来源、原子写、build_memory_header 每条 ≤200 字摘要、DONE 提炼器。
from fleet.core import events, memory


SIX_SECTION_REPORT = """# T-M1 六节报告
## 一、改动清单
新增 fleet/core/memory.py；导出函数 build_memory_header；同步契约 v1.2。
## 二、命令记录
pytest tests/core/test_memory.py -q
## 三、证据链
data/projects/P-001/evidence/T-M1/report.md
## 四、四要素
结论：完成；风险：无；遗留：无；下一步：联调。
## 五、未完成事项
无
## 六、模型自述
provider=stub model=demo-1 未降级
"""


def test_add_entry_schema_frozen(fleet_env, project):
    entry = memory.add_entry(
        "P-001", kind="decision", title="采用 SQLite 单文件",
        summary="d7.md 裁决：SQLite 存现在，events 存过去，evidence 存证据。", refs=["docs/adr.md"],
    )
    # schema 七字段冻结（控制台API.md §13.3）
    assert tuple(entry.keys()) == memory.ENTRY_FIELDS
    assert entry["id"] == "M-0001" and entry["kind"] == "decision"
    assert entry["created_at"] and entry["task_id"] is None
    # 落盘位置：data/memory/<project_id>.json
    assert memory._store_file("P-001").exists()
    assert memory.load_entries("P-001") == [entry]


def test_add_entry_rejects_bad_kind_and_truncates_summary(fleet_env, project):
    try:
        memory.add_entry("P-001", kind="rumor", title="x", summary="y")
        raise AssertionError("非法 kind 必须抛 MemoryError")
    except memory.MemoryError:
        pass
    entry = memory.add_entry("P-001", kind="fact", title="长" * 100, summary="摘" * 500)
    assert entry["title"] == "长" * memory.TITLE_LIMIT
    assert len(entry["summary"]) == memory.SUMMARY_LIMIT  # ≤200 字硬上限
    assert "\n" not in entry["summary"]


def test_record_decision_and_correction_emit_events(fleet_env, project):
    memory.record_decision("P-001", title="决策 A", summary="选 a 方案", task_id="T-1")
    memory.record_correction("P-001", title="用户纠正", summary="端口必须 5000")
    rows = [row for row in events.read(project="P-001") if row["action"] == "memory:recorded"]
    assert len(rows) == 2
    assert {row["extra"]["source"] for row in rows} == {"decision", "correction"}
    assert {row["extra"]["kind"] for row in rows} == {"decision", "fact"}
    assert rows[0]["extra"]["task_id"] == "T-1"


def test_build_memory_header_empty_or_unknown_refs_is_empty(fleet_env, project):
    assert memory.build_memory_header("P-001", []) == ""
    assert memory.build_memory_header("P-001", None) == ""
    assert memory.build_memory_header("P-001", ["M-9999"]) == ""  # 未知 id 忽略


def test_build_memory_header_summary_only_never_full_text(fleet_env, project):
    long_text = "全" * 800
    memory.add_entry("P-001", kind="fact", title="大文件事实", summary=long_text)
    header = memory.build_memory_header("P-001", ["M-0001"])
    assert header.startswith("[PROJECT MEMORY]")
    assert "M-0001" in header and "|fact" in header
    # 每条只渲染 ≤200 字摘要，绝不内嵌全文/全代码
    assert "全" * 201 not in header
    assert "全" * memory.SUMMARY_LIMIT in header


def test_distill_from_report_creates_artifact_once(fleet_env, project):
    report_file = fleet_env["data"] / "projects" / "P-001" / "evidence" / "T-M1" / "report.md"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(SIX_SECTION_REPORT, encoding="utf-8")

    entry = memory.distill_from_report("P-001", task_id="T-M1", title="记忆模块", report_path=str(report_file))
    assert entry is not None and entry["kind"] == "artifact" and entry["task_id"] == "T-M1"
    assert "memory.py" in entry["summary"]  # 摘要来自「改动清单」
    assert entry["refs"] == ["T-M1"]
    assert len(memory.load_entries("P-001")) == 1


def test_distill_from_report_missing_report_returns_none(fleet_env, project):
    assert memory.distill_from_report("P-001", task_id="T-X", title="x", report_path=None) is None
    assert memory.load_entries("P-001") == []


def test_ids_increase_monotonically_never_reuse(fleet_env, project):
    first = memory.add_entry("P-001", kind="fact", title="一", summary="1")
    second = memory.add_entry("P-001", kind="fact", title="二", summary="2")
    assert (first["id"], second["id"]) == ("M-0001", "M-0002")
