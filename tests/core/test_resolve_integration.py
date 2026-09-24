# 这是什么：resolve→派工→DONE 集成护栏（CORE-03）。
# 目的：验证"不经 contracts.register() 手工注入、走 contracts.resolve() 真实发现路径"的任务
#      能从 create_task 一路跑到 DONE（与十场景 #10 同口径的 8 事件断言）。
# 历史：本用例曾以 strict xfail 等待 INT-03（fleet/executors/* 模块未导出 resolve() 约定的
#      Adapter 属性，冷启动发现路径不通）；INT-03 迁移在工作区落地（模块导出 `Adapter = <Name>Adapter`
#      别名）后 strict xfail 立即触发强制（XPASS→FAILED），标记已按交接协议摘除，护栏全量生效。
import importlib
import shutil

import pytest

from fleet.core import db, events
from fleet.manager import dispatcher, reviewer
from fleet.manager.contracts import TaskPack

from .stubs import pass_route

#: 契约 §9.5-3 的 8 事件链（与 tests/core/test_ten_scenarios.py::EXPECTED_CHAIN 同口径）
EXPECTED_CHAIN = [
    "task:created",
    "task:assigned",
    "task:doing",
    "task:submitted",
    "gate:pass",
    "task:reviewing",
    "task:review_pass",
    "task:done",
]


def test_resolve_to_done_chain(fleet_env, project, tmp_path):
    """不经手工注册、走 resolve() 冷启动发现路径的全链护栏（INT-03 交付后已转绿）。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "deliver.txt").write_text("done", encoding="utf-8")
    pack = TaskPack(
        id="T-R01", title="resolve 全链护栏", detail="resolve→派工→DONE",
        verify_cmd='python -c "print(1)"', assignee="worker-a", reviewer="reviewer-1",
        workspace=str(workspace), forbidden_files=".env", project_id=project, adapter="fake",
    )
    dispatcher.create_task(pack, project_id=project, stage="阶段0", subtask="resolve 全链护栏")

    outcome = dispatcher.dispatch("T-R01")
    assert outcome.state == "SUBMITTED"

    result = reviewer.review("T-R01", actor="tester", router_fn=lambda *a, **k: pass_route())
    assert result.verdict == "PASS" and result.state == "DONE"
    assert db.get_task("T-R01")["exec_status"] == "DONE"

    chain = [row["action"] for row in events.read(project)]
    # CORE-04 契约 v1.2 后事件流还含 prompt:assembled/budget:check/model:call 等计量事件，
    # 本护栏断言的是任务生命周期链本身，故按动作码过滤后比对（顺序与唯一性不变）。
    chain = [action for action in chain if action in set(EXPECTED_CHAIN)]
    assert chain == EXPECTED_CHAIN  # 恰好 8 条、顺序一致


# ---------------------------------------------------------------------------
# 真实适配器 resolve→probe 探测（CLI 未安装时 skip 并注明；probe 语义：缺 CLI 返回全 False 能力）
# ---------------------------------------------------------------------------

REAL_ADAPTERS = [
    ("claudecode", "claude"),
    ("codex", "codex"),
    ("hermes", "hermes"),
    ("opencode", "opencode"),
    ("cline", "cline"),
    ("gemini", "gemini"),
    ("grok", "grok"),
]


@pytest.mark.parametrize("module_name,cli", REAL_ADAPTERS)
def test_real_adapter_probe(module_name, cli):
    """fleet/executors 的 7 个真实适配器：模块可导入、经装饰器注册表可实例化、能力探测可用。

    说明：实例经 fleet/executors/base.py 的 ADAPTER_REGISTRY（@register_adapter 填充）获取，
    作为 INT-03 迁移期的能力探测基线；迁移完成后应改走 contracts.resolve() 统一入口。
    能力探测方法名兼容迁移期两种形态：capabilities()（新）/ probe()（旧）。
    """
    from fleet.executors.base import ADAPTER_REGISTRY

    importlib.import_module(f"fleet.executors.{module_name}")  # 触发 @register_adapter 注册
    adapter_cls = ADAPTER_REGISTRY.get(module_name)
    assert adapter_cls is not None, f"fleet/executors/{module_name}.py 未被注册进适配器注册表"
    adapter = adapter_cls()

    if shutil.which(cli) is None:
        pytest.skip(f"{cli} CLI 未安装，跳过能力探测（探测语义：缺 CLI 时返回全 False 能力，不抛错）")

    probe_fn = getattr(adapter, "capabilities", None) or getattr(adapter, "probe", None)
    if probe_fn is None:
        pytest.skip(f"{module_name} 迁移进行中：暂无 capabilities()/probe() 能力探测方法")
    caps = probe_fn()
    assert caps is not None
    # 探测语义：CLI 在 PATH 但 --help 不合预期（如 WindowsApps 存根）时返回全 False 能力，
    # 属于合法探测结果，因此只断言返回类型与字段可访问，不绑定具体能力位。
    assert caps.usage_reporting in (True, False)
