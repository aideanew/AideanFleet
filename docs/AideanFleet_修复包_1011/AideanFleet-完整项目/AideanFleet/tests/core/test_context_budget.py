# 这是什么：Task Context 预算裁剪单测（CORE-04 · 契约 v1.2 §13.4/§13.5）。
# 目的：验证固定组装顺序、关键词段落裁剪、单文件上限与总预算双重约束、
#       截断清单、prompt:assembled / budget:check / budget:exceeded 事件字段，以及四段链路集成冒烟。
import json

from fleet.core import events, memory
from fleet.manager import context_budget
from fleet.manager.contracts import TaskPack


def _pack(**overrides) -> TaskPack:
    fields = dict(
        id="T-C1",
        title="为导出模块增加 CSV 分页导出",
        detail="在 exporter.py 中新增 export_csv(page_size)，保持过滤参数一致，并补测试。",
        verify_cmd="python -m pytest -q",
        assignee="be-1",
        workspace="",
        project_id="P-001",
    )
    fields.update(overrides)
    return TaskPack(**fields)


def _actions(project_id: str) -> list[str]:
    return [row["action"] for row in events.read(project=project_id)]


def test_estimate_tokens_is_chars_over_four():
    assert context_budget.estimate_tokens("") == 0
    assert context_budget.estimate_tokens("x" * 40) == 10


def test_assemble_prompt_fixed_order(fleet_env, project):
    prompt = context_budget.assemble_prompt(
        _pack(), "[PROJECT MEMORY] 头部", [], 8000,
        system_prompt="SYS-PROMPT", emit=False,
    )
    assert prompt.index("SYS-PROMPT") < prompt.index("[PROJECT MEMORY]") < prompt.index("[MANAGER DISPATCH]")


def test_assemble_prompt_trims_files_within_budget(fleet_env, project, tmp_path):
    big = tmp_path / "big.md"
    hit = tmp_path / "hit.md"
    big.write_text("头部说明\n\n" + ("无关填充段落。\n\n" * 4000) + "尾部收尾", encoding="utf-8")
    hit.write_text("export_csv 是本文件的主题段落。\n\n" + ("其他内容。\n\n" * 2000), encoding="utf-8")

    prompt = context_budget.assemble_prompt(
        _pack(), "", [str(big), str(hit)], 900, per_file_cap=300, emit=False,
    )
    assert context_budget.TRUNCATION_NOTICE in prompt
    assert f"- {big}" in prompt and f"- {hit}" in prompt
    # 单文件上限生效（300 token ≈ 1200 字符，远小于原文件）
    assert len(prompt) < (900 + 400) * 4
    # 关键词命中段被保留（任务说明里的 export_csv）
    assert "export_csv 是本文件的主题段落" in prompt


def test_assemble_prompt_missing_file_marked(fleet_env, project, tmp_path):
    prompt = context_budget.assemble_prompt(_pack(), "", [str(tmp_path / "ghost.py")], 8000, emit=False)
    assert "（文件不存在或不可读）" in prompt


def test_assembly_events_fields_frozen(fleet_env, project):
    pack = _pack(memory_refs=[])
    context_budget.assemble_prompt(pack, "", [], 8000, system_prompt="S")
    assembled = [row for row in events.read(project="P-001") if row["action"] == "prompt:assembled"]
    checks = [row for row in events.read(project="P-001") if row["action"] == "budget:check"]
    assert len(assembled) == 1 and len(checks) == 1
    extra = assembled[0]["extra"]
    for key in ("budget", "actual", "fixed_tokens", "files", "trimmed", "memory_refs", "rework"):
        assert key in extra
    assert extra["budget"] == 8000 and extra["rework"] is False
    assert checks[0]["extra"]["within"] is True


def test_budget_exceeded_when_fixed_section_alone_overflows(fleet_env, project):
    pack = _pack(detail="长" * 40000)  # 固定段 ~10000 tokens > 8000 预算
    context_budget.assemble_prompt(pack, "", [], 8000, emit=True)
    exceeded = [row for row in events.read(project="P-001") if row["action"] == "budget:exceeded"]
    assert len(exceeded) == 1
    extra = exceeded[0]["extra"]
    assert extra["oversize_tokens"] > 0 and extra["budget"] == 8000


def test_extract_keywords_hit_relevant_paragraphs():
    pack = _pack()
    keywords = context_budget.extract_keywords(pack)
    assert "export_csv" in keywords
    trimmed = context_budget._trim_file("无关段\n\nexport_csv(page_size) 相关段\n\n尾部", keywords, 10_000)
    assert "export_csv(page_size) 相关段" in trimmed and "尾部" in trimmed and "无关段" in trimmed


def test_assemble_rework_prompt_incremental_only(fleet_env, project):
    retry_context = {
        "attempt": 2,
        "failure": {"gate": None, "review": "实现不完整"},
        "previous_diff": {"stat": " exporter.py | 2 +-", "files": {}, "source": "git"},
        "evidence_paths": ["data/projects/P-001/evidence/T-C1/gate.json"],
    }
    prompt = context_budget.assemble_rework_prompt(_pack(), retry_context, fix_instructions="修 export_csv")
    assert "这是第 2 轮返工，只需基于以下增量信息修复，不要重新调查全项目" in prompt
    assert "修 export_csv" in prompt
    assert '"attempt": 2' in prompt
    assert "[MANAGER DISPATCH]" not in prompt  # 不重发全量派工模板
    assembled = [row for row in events.read(project="P-001") if row["action"] == "prompt:assembled"]
    assert len(assembled) == 1 and assembled[0]["extra"]["rework"] is True


def test_smoke_memory_ref_trim_model_call_chain(fleet_env, project, tmp_path):
    """集成冒烟：记忆生成→引用→裁剪→前缀稳定 四段链路（stub 场景，无真实网络）。"""
    from fleet.models import transport

    # ① 记忆生成（Manager 决策）
    entry = memory.record_decision("P-001", title="CSV 导出统一走 exporter",
                                   summary="所有导出集中在 exporter.py，不再散落脚本。", task_id="T-C9")
    # ② 引用 → 记忆头
    pack = _pack(id="T-C9", memory_refs=[entry["id"]], context_budget=4000)
    context_file = tmp_path / "exporter.py"
    context_file.write_text("def export_csv():\n" + "    pass\n" * 5000, encoding="utf-8")
    prompt = context_budget.assemble_prompt(
        pack,
        memory.build_memory_header("P-001", pack.memory_refs),
        [str(context_file)],
        pack.context_budget,
        system_prompt="SYS",
    )
    assert entry["id"] in prompt and "不再散落脚本" in prompt
    assert context_budget.TRUNCATION_NOTICE in prompt
    # ③ 预算事件落事件流
    actions = _actions("P-001")
    assert "prompt:assembled" in actions and "budget:check" in actions
    # ④ 稳定前缀：同角色同项目字节级不变 → 版本号不变；内容变化 → 版本号 +1
    prefix = "SYS\n[PROJECT MEMORY] 头部"
    v1 = transport.set_stable_prefix("be-1", "P-001", prefix)
    v2 = transport.set_stable_prefix("be-1", "P-001", prefix)
    v3 = transport.set_stable_prefix("be-1", "P-001", prefix + "\n")
    assert (v1, v2, v3) == (1, 1, 2)
    assert transport.get_stable_prefix("be-1", "P-001") == (2, prefix + "\n")
    transport.reset_prefix_cache()
