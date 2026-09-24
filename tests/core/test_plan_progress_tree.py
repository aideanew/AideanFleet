"""权重化进度树（需求3）：compute_progress 的口径与「叶子和=100」不变式。"""

from fleet.core.plan import STAGE_NAME_KEY, STAGE_KEY, TASK_ID_KEY, TASK_KEY, _distribute_pct, compute_progress


def _stage(name, tasks, weight=None):
    stage = {
        STAGE_NAME_KEY: name,
        TASK_KEY: [
            {TASK_ID_KEY: task_id, **({"权重": w} if w is not None else {})}
            for task_id, w in tasks
        ],
    }
    if weight is not None:
        stage["权重"] = weight
    return stage


def _leaf_sum(progress):
    return round(sum(t["contrib_pct"] for s in progress["stages"] for t in s["tasks"]), 6)


def test_equal_mode_matches_legacy_done_over_total():
    """未配置权重 ⟹ 与旧口径 done/total 一致（向后兼容的回归锚点）。"""
    plan_data = {STAGE_KEY: [_stage("阶段1", [(f"T{i}", None) for i in range(5)])]}
    states = {"T0": "DONE", "T1": "DOING", "T2": "DRAFT", "T3": "DRAFT", "T4": "DRAFT"}
    progress = compute_progress(plan_data, states)
    assert progress["mode"] == "equal"
    assert progress["percent"] == 20.0
    assert _leaf_sum(progress) == 100.0


def test_weighted_leaf_sum_is_exactly_100():
    """任意权重组合下，全部叶子份额之和恒等于 100.0（Hamilton 无舍入漂移）。"""
    plan_data = {STAGE_KEY: [
        _stage("设计", [("T1", 3), ("T2", 1)], weight=7),
        _stage("实现", [("T3", 1), ("T4", 1), ("T5", 1)]),
    ]}
    states = {"T1": "DONE", "T2": "PARTIAL", "T3": "DOING", "T4": "DRAFT", "T5": "REWORK"}
    progress = compute_progress(plan_data, states)
    assert progress["mode"] == "weighted"
    assert _leaf_sum(progress) == 100.0
    stage_totals = {s["name"]: s["contrib_pct"] for s in progress["stages"]}
    assert round(sum(stage_totals.values()), 6) == 100.0
    # 阶段权重 7 : (默认 Σ 子权重 3) ⟹ 设计阶段约占 70%
    assert abs(stage_totals["设计"] - 70.0) <= 0.2


def test_stage_default_weight_is_sum_of_children():
    """阶段未写权重时默认 = Σ 任务权重：阶段内份额按任务权重切分。"""
    plan_data = {STAGE_KEY: [
        _stage("A", [("T1", 4)]),          # 默认阶段权重 4
        _stage("B", [("T2", 1)]),          # 默认阶段权重 1
    ]}
    progress = compute_progress(plan_data, {"T1": "DRAFT", "T2": "DRAFT"})
    totals = {s["name"]: s["contrib_pct"] for s in progress["stages"]}
    assert totals["A"] == 80.0 and totals["B"] == 20.0


def test_explicit_stage_weight_overrides_child_rollup():
    """显式阶段权重优先于子权重合计（文档化语义）。"""
    plan_data = {STAGE_KEY: [
        _stage("A", [("T1", 1), ("T2", 1)]),        # 默认权重 2
        _stage("B", [("T3", 1)], weight=6),         # 显式 6 ⟹ B 占 6/8
    ]}
    progress = compute_progress(plan_data, {"T1": "DONE", "T2": "DONE", "T3": "DRAFT"})
    assert abs(progress["percent"] - 25.0) <= 0.1   # 只有 A 完成：2/8=25%


def test_orphan_tasks_form_virtual_stage():
    """SQLite 有但 plan.json 未登记的任务归入「未归入计划」，保证不丢分母。"""
    plan_data = {STAGE_KEY: [_stage("A", [("T1", None)])]}
    progress = compute_progress(plan_data, {"T1": "DRAFT", "T9": "DONE"})
    virtual = next(s for s in progress["stages"] if s["virtual"])
    assert virtual["name"] == "未归入计划"
    assert virtual["done"] == 1
    assert _leaf_sum(progress) == 100.0
    assert progress["percent"] == 50.0


def test_empty_stage_excluded_from_denominator():
    """没有可识别任务（task_id 不在 states）的阶段不占权重。"""
    plan_data = {STAGE_KEY: [
        _stage("空阶段", [("GHOST", 100)]),
        _stage("实阶段", [("T1", 1), ("T2", 1)]),
    ]}
    progress = compute_progress(plan_data, {"T1": "DONE", "T2": "DRAFT"})
    assert [s["name"] for s in progress["stages"]] == ["实阶段"]
    assert progress["percent"] == 50.0


def test_empty_plan_with_all_done_tasks_reaches_100():
    """plan.json 缺失（{}）时全部走虚拟阶段：全完成即 100.0。"""
    progress = compute_progress({}, {"T1": "DONE", "T2": "PARTIAL"})
    assert progress["percent"] == 100.0
    assert _leaf_sum(progress) == 100.0


def test_no_tasks_zero_percent():
    progress = compute_progress({}, {})
    assert progress["percent"] == 0.0
    assert progress["stages"] == []


def test_invalid_weights_fall_back_to_default():
    """非法/非正权重回落缺省值，绝不让进度树抛异常。"""
    plan_data = {STAGE_KEY: [{STAGE_NAME_KEY: "A", TASK_KEY: [
        {TASK_ID_KEY: "T1", "权重": "abc"},
        {TASK_ID_KEY: "T2", "权重": -5},
        {TASK_ID_KEY: "T3", "权重": None},
    ]}]}
    progress = compute_progress(plan_data, {"T1": "DONE", "T2": "DRAFT", "T3": "DONE"})
    # 权重键存在但非法：数值回落缺省（等权），mode 标记为 weighted 仅表示"配过权重"
    assert progress["percent"] == round(2 / 3 * 100, 1)
    assert _leaf_sum(progress) == 100.0


def test_distribute_pct_exact_one_decimal():
    """Hamilton 拆分：3 等分 100 必须凑回 100.0 而不是 99.9。"""
    parts = _distribute_pct([1.0, 1.0, 1.0])
    assert round(sum(parts), 6) == 100.0
    # 浮点边界：abs(33.4-33.3)=0.10000000000000142 严格大于 0.1，必须带 epsilon 容差
    assert all(abs(p - 33.3) <= 0.1 + 1e-9 for p in parts)
    assert _distribute_pct([]) == []
