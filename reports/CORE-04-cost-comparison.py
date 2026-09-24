# 这是什么：CORE-04 9.6 成本对比脚本（硬性验收：改造前后 prompt 体积对比，目标降幅 ≥60%）。
# 运行：.venv/Scripts/python.exe reports/CORE-04-cost-comparison.py
# 口径：tokens ≈ 字符数 ÷ 4（契约 v1.2 §13.7）；全部离线 stub，不发生任何真实模型调用；
#       记忆/事件写入重定向到临时目录，结束即清理，不污染仓库 data/。
"""CORE-04 9.6 成本对比：改造前（全量直拼）vs 改造后（记忆摘要 + 预算裁剪 + 返工增量）。"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="core04-cost-"))
import os  # noqa: E402

os.environ["FLEET_ROOT"] = str(_TMP / "root")
os.environ["FLEET_DATA_DIR"] = str(_TMP / "root" / "data")

from fleet.core import memory  # noqa: E402
from fleet.manager import context_budget  # noqa: E402
from fleet.manager.contracts import TaskPack  # noqa: E402


def _write(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def build_fixtures(base: Path) -> dict:
    """两份代表性上下文文件（真实工程质感，非空壳）。"""
    exporter = "\n".join(
        [
            '"""reporting.exporter：结果导出模块。"""',
            "import csv",
            "import json",
            "",
            "FILTERS = ('status', 'owner', 'created_after')",
            "",
            "def export_json(rows, path, *, status=None, owner=None):",
            '    """导出 JSON；支持 status/owner 过滤。"""',
            "    picked = [r for r in rows if (status is None or r['status'] == status)]",
            "    Path(path).write_text(json.dumps(picked, ensure_ascii=False, indent=2))",
            "    return len(picked)",
            "",
        ]
        + [f"# 历史行 #{i}：占位实现说明，保持与 JSON 导出一致的行为约定。" for i in range(400)]
    )
    api_doc = "\n".join(
        ["# 导出 API 文档", "", "## GET /export/json", "参数：status、owner。", ""]
        + [f"- 历史备注 {i}：分页参数尚未支持，等待 export_csv 落地。" for i in range(300)]
    )
    test_file = "\n".join(
        ["import pytest", "", "from reporting.exporter import export_json", ""]
        + [f"def test_legacy_{i}():\n    assert export_json([], 'out.json') == 0\n" for i in range(120)]
    )
    return {
        "exporter": _write(base / "src" / "reporting" / "exporter.py", exporter),
        "api": _write(base / "docs" / "api.md", api_doc),
        "test": _write(base / "tests" / "test_exporter.py", test_file),
    }


def main() -> None:
    files = build_fixtures(_TMP / "workspace")
    detail = (
        "在 fleet/reporting/exporter.py 中新增 export_csv(page_size) 方法，"
        "保持与 export_json 相同的过滤参数；同步补充 tests/test_exporter.py 三条分页用例；"
        "文档 docs/api.md 增加 GET /export/csv 示例。"
    )
    pack = TaskPack(
        id="T-101",
        title="为导出模块增加 CSV 分页导出",
        detail=detail,
        verify_cmd="python -m pytest tests/test_exporter.py -q",
        assignee="be-1",
        reviewer="reviewer-1",
        project_id="P-001",
        context_budget=8000,
        memory_refs=["M-0001", "M-0002", "M-0003"],
    )
    system_prompt = "你是 AideanFleet 后端执行角色 be-1。只做任务范围内改动，先读文件再动手。"

    # ---- 项目记忆：3 条（含超长原始记录；“改造前”按旧口径把记忆全文塞进 prompt）----
    raw1 = ("所有导出统一收敛到 reporting/exporter.py，禁止散落脚本；历史结论：JSON 导出曾因 "
            "ensure_ascii 缺省产生乱码，已修复；导出目录必须先 os.makedirs(exist_ok=True)；"
            "导出后必须回读校验行数与源数据一致，否则视为失败。相关讨论见评审记录 #118、#121、#134，"
            "以及当初 200 行的临时脚本 misc/export_try.py（已删除，逻辑已并入 exporter.py）。") * 8
    raw2 = ("过滤参数冻结为 status/owner/created_after 三个，新增参数必须走扩展对象；"
            "分页参数 page_size 默认 500，最大 5000；CSV 一律 UTF-8 with BOM，"
            " delimiter=','，换行 \\r\\n；数字列不得加千分位引号。") * 8
    raw3 = ("T-098 产出：落地 export_json；测试 12 条全绿；文档已同步；遗留 TODO：CSV 分页尚未实现，"
            "占位函数 export_csv 只有 NotImplementedError；评审意见要求先补分页再谈流式导出；"
            "性能基线：1 万行导出 < 800ms。") * 8
    memory.record_decision("P-001", title="导出模块单一出口", summary=raw1, task_id="T-098")
    memory.record_decision("P-001", title="过滤参数口径", summary=raw2, task_id="T-099")
    memory.add_entry("P-001", kind="artifact", title="T-098 产出", summary=raw3, task_id="T-098")
    header = memory.build_memory_header("P-001", pack.memory_refs)
    memory_full = "\n".join([f"- [M-000{i}|...] {raw}" for i, raw in enumerate((raw1, raw2, raw3), start=1)])
    assert len(memory_full) > len(header) * 2, "记忆摘要头应显著短于全文"

    context_files = [files["exporter"], files["api"], files["test"]]
    full_context = "".join(
        f"\n\n[CONTEXT FILE] {p}\n" + Path(p).read_text(encoding="utf-8") for p in context_files
    )

    # ================= 场景一：全新任务 =================
    before_new = "\n\n".join([system_prompt, memory_full, pack.to_prompt()]) + full_context
    after_new = context_budget.assemble_prompt(pack, header, context_files, pack.context_budget,
                                               system_prompt=system_prompt, emit=False)

    # ================= 场景二：二轮返工 =================
    retry_context = {
        "attempt": 2,
        "failure": {"gate": {"passed": False, "reasons": ["verify_cmd_failed:exit_code=1"]},
                    "review": "分页参数未透传，docs 未更新"},
        "previous_diff": {"stat": " exporter.py | 12 ++++---\n api.md | 2 +",
                          "files": {"src/reporting/exporter.py": "@@ -12,6 +12,9 @@\n+def export_csv(...)"},
                          "source": "git"},
        "evidence_paths": ["data/projects/P-001/evidence/T-101/gate.json",
                           "data/projects/P-001/evidence/T-101/verify_output.txt"],
    }
    fix = "【返工意见 · 第 2 轮】\n分页参数未透传，docs 未更新。请补 export_csv(page_size) 与文档。"
    before_rework = before_new + "\n\n" + fix  # 旧行为：全量重发 + 意见追加
    after_rework = context_budget.assemble_rework_prompt(pack, retry_context, fix_instructions=fix, emit=False)

    def row(name: str, before: str, after: str) -> dict:
        b_chars, a_chars = len(before), len(after)
        return {
            "场景": name,
            "改造前 chars": b_chars, "改造前 tokens≈": b_chars // 4,
            "改造后 chars": a_chars, "改造后 tokens≈": a_chars // 4,
            "降幅": f"{(b_chars - a_chars) / b_chars * 100:.1f}%",
        }

    rows = [
        row("全新任务（3 记忆 + 3 上下文文件）", before_new, after_new),
        row("二轮返工（retry_context 增量）", before_rework, after_rework),
    ]

    print("CORE-04 · 9.6 成本对比（口径：tokens ≈ chars ÷ 4，契约 v1.2 §13.7）")
    print("-" * 104)
    print(f"{'场景':<28}{'改造前 chars':>14}{'改造前 tokens':>14}{'改造后 chars':>14}{'改造后 tokens':>14}{'降幅':>10}")
    print("-" * 104)
    for item in rows:
        print(f"{item['场景']:<28}{item['改造前 chars']:>14}{item['改造前 tokens≈']:>14}"
              f"{item['改造后 chars']:>14}{item['改造后 tokens≈']:>14}{item['降幅']:>10}")
    print("-" * 104)
    print("附：现状基线（典型 TaskPack 直拼 DISPATCH 模板，无记忆/无上下文文件）：",
          len(pack.to_prompt()), "chars ≈", len(pack.to_prompt()) // 4, "tokens")
    print("附：记忆头 vs 记忆全文：", len(header), "chars vs", len(memory_full), "chars")
    print("附：改造后（新任务）含截断清单：", context_budget.TRUNCATION_NOTICE in after_new)
    print("附：改造后（返工）含模板句：", "这是第 2 轮返工，只需基于以下增量信息修复，不要重新调查全项目" in after_rework)

    shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
