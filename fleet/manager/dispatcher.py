"""这是什么：Manager 派工器。把 TaskPack 派给执行体适配器，按状态机推进 DRAFT→ASSIGNED→DOING→SUBMITTED。
怎么用：from fleet.manager import dispatcher;  dispatcher.dispatch("T-001")   # 只走到 SUBMITTED
        dispatcher.run_to_completion("T-001")                                # 再串上机器门 + 审查，走到终态
落盘约定（三个路径互不混用）：
  report_path   = <data>/projects/<pid>/evidence/<tid>/report.md    执行体回执（六节报告）
  evidence_path = 同一个 report.md                                   机器门"证据存在性"检查对象
  baseline_path = <data>/projects/<pid>/evidence/<tid>/baseline.json 派工前快照（用来扫"改了什么"）
  机器门产物    = <data>/projects/<pid>/evidence/<tid>/gate/          由 gates/verify.py 写
断点恢复：ASSIGNED/DOING 的任务再次调用 dispatch 不会重复派工，会如实返回当前状态。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fleet.core import db, events, plan
from fleet.core import config as fleet_config
from fleet.core import memory as project_memory
from fleet.core import state_machine as sm
from fleet.core.paths import paths
from fleet.gates import verify
from fleet.models import pool, retry, transport

from . import context_budget
from . import report as report_parser
from . import reviewer
from .contracts import AdapterNotAvailable, AgentResult, BaseAdapter, TaskPack


@dataclass
class DispatchOutcome:
    """派工结果。state 是落库后的真实状态（SUBMITTED / BLOCKED / 原状态）。"""

    ok: bool
    task_id: str
    state: str
    detail: str = ""
    model: str | None = None
    platform: str | None = None
    duration_ms: int = 0
    attempts: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)
    report_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "taskId": self.task_id,
            "state": self.state,
            "detail": self.detail,
            "model": self.model,
            "platform": self.platform,
            "duration_ms": self.duration_ms,
            "attempts": self.attempts,
            "failures": self.failures,
            "report_path": self.report_path,
        }


#: 允许重复派工的前置状态（其余状态调用 dispatch 一律按非法迁移处理）
RESUMABLE_STATES = frozenset({"ASSIGNED", "DOING"})


def _evidence_dir(task: dict[str, Any]) -> Path:
    return paths().evidence_dir(str(task.get("project_id") or "unassigned"), str(task["task_id"]))


def ensure_paths(task: dict[str, Any]) -> dict[str, str]:
    """补齐任务的三条落盘路径（已设置的不覆盖），并把默认值写回数据库。"""
    directory = _evidence_dir(task)
    directory.mkdir(parents=True, exist_ok=True)
    wanted = {
        "report_path": str(directory / "report.md"),
        "evidence_path": str(directory / "report.md"),
        "baseline_path": str(directory / "baseline.json"),
    }
    patch = {key: value for key, value in wanted.items() if not task.get(key)}
    if patch:
        task = db.update_task(task["task_id"], **patch)
    return {"report_path": task["report_path"], "evidence_path": task["evidence_path"], "baseline_path": task["baseline_path"]}


def _adapter_for(task: dict[str, Any]) -> BaseAdapter:
    """解析执行体适配器：优先任务上的 adapter 字段，其次角色配置里的 adapter。"""
    name = str(task.get("adapter") or "").strip()
    if not name:
        for role in fleet_config.load("roles").get("roles", []):
            if role.get("name") == task.get("assignee"):
                name = str(role.get("adapter") or "").strip()
                break
    # 持久化解析后的适配器名到 DB（P-008 实测：DB adapter 列恒为空，身份仅存事件流）
    if name and not str(task.get("adapter") or "").strip() and task.get("task_id"):
        try:
            db.update_task(str(task["task_id"]), adapter=name)
        except Exception:
            pass
    from .contracts import resolve

    return resolve(name)


def _model_candidates(assignee: str) -> list[tuple[str | None, str]]:
    """角色的模型链 -> [(模型名, model_id)]。链为空时给一个"适配器默认"候选。"""
    chain = pool.chain_for(assignee)
    if not chain:
        return [(None, "")]
    return [(entry.name, entry.model_id) for entry in chain]


def _system_prompt_for(assignee: str) -> str:
    """角色系统提示（roles 段 SYSTEM_PROMPT）；稳定前缀段之一（契约 v1.2 §13.6）。"""
    for role in fleet_config.load("roles").get("roles", []):
        if role.get("name") == assignee:
            return str(role.get("system_prompt") or "")
    return ""


def _context_files_for(pack: TaskPack, workspace: str) -> list[str]:
    """上下文文件候选：TaskPack 指定的（extra.context_files）优先，否则回退 allowed_files 里真实存在的文件。"""
    explicit = [str(item) for item in (pack.extra.get("context_files") or []) if str(item).strip()]
    if explicit:
        return explicit
    if not workspace:
        return []
    root = Path(workspace)
    out: list[str] = []
    for pattern in pack.allowed_list():
        candidate = root / pattern
        if any(part == "*" or "**" in part for part in Path(pattern).parts):
            matches = sorted(root.glob(pattern))
            out.extend(str(item) for item in matches if item.is_file())
        elif candidate.is_file():
            out.append(str(candidate))
    return out


def _build_prompt(pack: TaskPack) -> str:
    """CORE-04 派工 prompt 组装（契约 v1.2 §13.4/§13.5）：
    - 返工任务（retry_context 非空）只发增量 retry_context + 修复指令，不重发记忆/全量上下文；
    - 新任务 = system_prompt + 记忆头（按 memory_refs 引用） + 任务说明 + 预算裁剪后的上下文文件；
    - 统一追加工作区与路径约束，不假定执行体使用哪一种 shell。
    """
    env_note = (
        "\n\n【执行环境约束】以工具实际使用的 shell 为准，不因 Windows 就假定 PowerShell：\n"
        "- 工作区内优先使用相对路径；绝对路径使用正斜杠并加引号（例如 \"E:/Demo/project/src\"），禁止裸反斜杠路径；\n"
        "- 操作前核对工具的工作目录与任务 workspace 一致；不一致立即停止并返回 BLOCKED，不在控制面根目录补建目录；\n"
        "- 只在工作区内创建项目文件。完整六节报告通过标准输出返回，由 Fleet 写入控制面证据目录，禁止执行体越界写报告；\n"
        "- 目录与文件结构以任务计划为准，禁止创建与计划无关的顶层目录。"
    )
    if pack.retry_context:
        fix = last_rework_opinion(pack.detail)
        return context_budget.assemble_rework_prompt(pack, pack.retry_context, fix_instructions=fix) + env_note
    memory_header = ""
    if pack.memory_refs and pack.project_id:
        memory_header = project_memory.build_memory_header(pack.project_id, pack.memory_refs)
    return context_budget.assemble_prompt(
        pack,
        memory_header,
        _context_files_for(pack, pack.workspace),
        pack.context_budget,
        system_prompt=_system_prompt_for(pack.assignee),
    ) + env_note


def last_rework_opinion(detail: str) -> str:
    """从 detail 里取最后一个【返工意见 · 第 N 轮】块（透传 rework_manager 实现）。"""
    from . import rework_manager

    return rework_manager.last_rework_opinion(detail)


def _run_with_chain(
    adapter: BaseAdapter,
    prompt: str,
    workspace: str,
    assignee: str,
    policy: retry.RetryPolicy,
    project: str | None,
    task_id: str,
) -> tuple[AgentResult, dict[str, Any]]:
    """按角色模型链调用适配器：软失败等 10 秒重试（最多 10 次），硬失败立即换模型。

    返回 (最终 AgentResult, 过程信息)。过程信息含 attempts / model / platform / failures / duration_ms。
    """
    candidates = _model_candidates(assignee)
    failures: list[dict[str, Any]] = []
    previous_name: str | None = None
    previous_attempts = 0
    started = time.perf_counter()

    for model_name, model_id in candidates:
        if previous_name is not None:
            events.append(
                actor="router",
                action="launch:model_switch",
                task_id=task_id,
                summary=f"{assignee} 模型切换：{previous_name} -> {model_name or adapter.name}（上一候选已试 {previous_attempts} 次）",
                url=f"/tasks/{task_id}",
                project=project,
                extra={"role": assignee, "from": previous_name, "to": model_name, "attempts": previous_attempts},
            )

        attempts = 0
        while True:
            attempts += 1
            # 运行时上下文（需求4）：spawn 点（base.run_subprocess_tree_safe）据此登记
            # pid/进程名 ↔ 任务/角色/执行体 的归属；线程局部，随 with 退出恢复。
            from fleet.executors import registry as _exec_registry
            with _exec_registry.run_context(
                task_id=task_id, project=project or "", role=assignee,
                adapter=adapter.name, model=model_id or "",
            ):
                # P1-A-3：统一走 run_stream（默认实现 fallback 到 run，不影响非流式适配器）；
                # 有 on_chunk 回调时，支持流式的适配器（如 FakeAdapter 测试）会逐块推送事件。
                def _on_chunk(text: str, _tid=task_id, _role=assignee, _model=model_name or adapter.name, _proj=project) -> None:
                    events.append(
                        actor="manager",
                        action="task:stream_chunk",
                        task_id=_tid,
                        summary=text[:200],
                        url=f"/tasks/{_tid}" if _tid else None,
                        project=_proj,
                        extra={"role": _role, "model": _model},
                    )

                result = adapter.run_stream(prompt, workspace, model_id, policy.timeout_seconds, on_chunk=_on_chunk)
            # 孤儿切换守卫：rel 守卫可能在 adapter.run() 阻塞期间把任务升级为 BLOCKED。
            # 不检查就会在 BLOCKED 任务上继续空转切模型（P-008 T04 实测：BLOCKED 后 26 分钟仍在切 modelscope→amd）。
            _current = db.get_task(task_id) or {}
            if str(_current.get("exec_status") or "") in ("BLOCKED", "ESCALATED"):
                events.append(
                    actor="rel",
                    action="task:blocked",
                    task_id=task_id,
                    summary=f"{assignee} 模型链中止：任务已被外部升级为 {_current.get('exec_status')}",
                    url=f"/tasks/{task_id}",
                    project=project,
                    extra={"aborted": True, "attempts": attempts, "model": model_name or adapter.name},
                )
                return (
                    AgentResult(ok=False, error_code="TASK_BLOCKED",
                                error_msg=f"任务在执行期间被升级为 {_current.get('exec_status')}"),
                    {"attempts": attempts, "model": model_name or adapter.name,
                     "platform": model_name or adapter.name, "model_id": model_id,
                     "failures": failures,
                     "duration_ms": int((time.perf_counter() - started) * 1000)},
                )
            if result.ok:
                events.append(
                    actor="manager",
                    action="model:call",
                    task_id=task_id,
                    summary=(
                        f"{assignee} 调用 {model_name or adapter.name} 成功"
                        f"（attempts={attempts}"
                        + (f"，session={result.session_id}" if result.session_id else "")
                        + "）"
                    ),
                    url=f"/tasks/{task_id}" if task_id else None,
                    project=project,
                    extra={
                        "role": assignee,
                        "model": model_name or adapter.name,
                        "model_id": model_id,
                        "adapter": adapter.name,
                        "attempts": attempts,
                        "session_id": result.session_id,
                        "usage": transport.normalize_usage(result.usage),
                    },
                )
                return result, {
                    "attempts": attempts,
                    "model": model_name or adapter.name,
                    "platform": model_name or adapter.name,
                    "model_id": model_id,
                    "failures": failures,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                }
            kind = retry.classify(result.error_code, result.error_msg)
            if not policy.should_retry(kind, attempts):
                failures.append(
                    {
                        "model": model_name or adapter.name,
                        "attempts": attempts,
                        "error_code": result.error_code,
                        "kind": kind,
                        "error": result.error_msg[:500],
                    }
                )
                break
            policy.wait()

        previous_name, previous_attempts = model_name or adapter.name, attempts

    detail = "；".join(f"{item['model']}:{item['error_code']}x{item['attempts']}" for item in failures) or "无候选模型"
    return (
        AgentResult(ok=False, error_code="all_models_exhausted", error_msg="全部候选耗尽 -> " + detail),
        {
            "attempts": previous_attempts,
            "model": previous_name,
            "platform": previous_name,
            "model_id": None,
            "failures": failures,
            "duration_ms": int((time.perf_counter() - started) * 1000),
        },
    )


def _block(task: dict[str, Any], reason: str, actor: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """把任务置为 BLOCKED（合法迁移：ASSIGNED/DOING/SUBMITTED → BLOCKED）。"""
    return db.transition_and_log(
        task["task_id"],
        "BLOCKED",
        actor=actor,
        summary=f"{task['task_id']} 阻塞：{reason}",
        remark=reason,
        blocked_reason=reason,
        extra=extra or {},
    )


# ---------------------------------------------------------------------------
# 主入口：create_task / dispatch / run_to_completion（CORE-02 补齐，docstring 原承诺）
# ---------------------------------------------------------------------------


def create_task(
    pack: TaskPack,
    *,
    project_id: str,
    stage: str = "默认阶段",
    subtask: str = "",
    dependencies: list[str] | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    """登记一个 DRAFT 任务：落库 + 事件 task:created + plan.json 登记 + 依赖环检测。

    建任务前先做依赖环检测（dag.assert_acyclic），成环直接抛 CycleDetected，不落库。
    """
    from . import dag as dag_engine

    # 依赖入参兼容 list / JSON 文本两种形态（confirm_release 会从 DB 行拷贝依赖）
    deps = dag_engine.parse_dependencies(dependencies)
    existing = {t["task_id"]: dag_engine.parse_dependencies(t.get("dependencies"))
                for t in db.list_tasks(project_id, db_file=db_file)}
    existing[pack.id] = deps
    dag_engine.assert_acyclic(existing)

    fields = {
        "task_id": pack.id,
        "project_id": project_id,
        "title": pack.title,
        "detail": pack.detail,
        "verify_cmd": pack.verify_cmd,
        "assignee": pack.assignee,
        "reviewer": pack.reviewer,
        "workspace": pack.workspace,
        "allowed_files": pack.allowed_files,
        "forbidden_files": pack.forbidden_files,
        "dependencies": deps,
        "adapter": pack.adapter,
        "role": pack.assignee,
        "context_budget": pack.context_budget,
        "memory_refs": pack.memory_refs,
    }
    created = db.create_task(fields, db_file=db_file)
    events.append(
        actor="manager",
        action="task:created",
        task_id=pack.id,
        summary=f"{pack.id} 已创建（DRAFT）：{pack.title}",
        url=f"/tasks/{pack.id}",
        project=project_id,
        extra={"dependencies": deps},
    )
    plan.update_task(project_id, stage, subtask or pack.title, pack.id, "DRAFT")
    return created


def dispatch(
    task_id: str,
    *,
    actor: str = "manager",
    policy: retry.RetryPolicy | None = None,
    db_file: str | Path | None = None,
) -> DispatchOutcome:
    """派工主流程：DRAFT→ASSIGNED→DOING→SUBMITTED（含模型链重试）。

    断点恢复：ASSIGNED/DOING 再次调用不重复派工——DOING 原样返回，
    ASSIGNED 继续往下走。非可恢复状态抛 InvalidTransition（API 层转 409）。
    """
    task = db.get_task(task_id, db_file=db_file)
    if task is None:
        raise KeyError(f"任务不存在：{task_id}")
    state = task["exec_status"]

    if state == "DOING":
        return DispatchOutcome(ok=True, task_id=task_id, state="DOING",
                               detail="already_doing（断点恢复：不重复派工）")
    if state == "SUBMITTED":
        # SUBMITTED 幂等返回：执行体回执已落盘，等待机器门评审。
        # run_to_completion 依赖本分支续跑评审，否则 SUBMITTED 永远卡死（调度循环与手动推进双断路）。
        return DispatchOutcome(ok=True, task_id=task_id, state="SUBMITTED",
                               detail="already_submitted（断点恢复：等待机器门评审）")
    if state not in ("DRAFT",) and state not in RESUMABLE_STATES:
        raise sm.InvalidTransition(state, "DOING", f"任务当前状态 {state} 不可派工")

    # ---- 准备（DRAFT→ASSIGNED 或 ASSIGNED 断点续跑都会经过）：补路径 + 拍基线 ----
    if state == "DRAFT":
        task = db.transition_and_log(
            task_id,
            "ASSIGNED",
            actor=actor,
            summary=f"{task_id} 已派工（assignee={task.get('assignee') or '未指定'}）",
            extra={"adapter": task.get("adapter") or ""},
            db_file=db_file,
        )
    task = db.get_task(task_id, db_file=db_file)
    settled = ensure_paths(task)
    if not Path(settled["baseline_path"]).exists():
        workspace = str(task.get("workspace") or "").strip()
        if workspace:
            workspace_path = Path(workspace)
            workspace_path.mkdir(parents=True, exist_ok=True)
            verify.capture_baseline(workspace, settled["baseline_path"])

    # ---- ASSIGNED → DOING：解析适配器并调用 ----
    task = db.get_task(task_id, db_file=db_file)
    # 并发复核：ready 快照可能过期（如上一拍同任务已进入 DOING），DOING->DOING 会抛 InvalidTransition
    if task.get("exec_status") == "DOING":
        return DispatchOutcome(ok=True, task_id=task_id, state="DOING",
                               detail="already_doing（并发复核：不重复派工）")
    try:
        adapter = _adapter_for(task)
    except AdapterNotAvailable as error:
        blocked = _block(task, f"adapter_unavailable: {error}", actor, {"adapter": task.get("adapter")})
        return DispatchOutcome(ok=False, task_id=task_id, state="BLOCKED",
                               detail=f"adapter_unavailable: {error}")

    pack = TaskPack.from_task(task)
    db.transition_and_log(
        task_id, "DOING", actor=actor,
        summary=f"{task_id} 进入执行（adapter={adapter.name}）",
        extra={"adapter": adapter.name},
        db_file=db_file,
    )

    active_policy = policy or retry.policy()
    prompt = _build_prompt(pack)
    result, meta = _run_with_chain(
        adapter, prompt, pack.workspace, pack.assignee or "default",
        active_policy, task.get("project_id"), task_id,
    )

    if not result.ok:
        blocked = _block(
            db.get_task(task_id, db_file=db_file),
            f"executor_failed: {result.error_code}",
            actor,
            {"error_code": result.error_code, "attempts": meta.get("attempts")},
        )
        return DispatchOutcome(
            ok=False, task_id=task_id, state="BLOCKED",
            detail=f"executor_failed: {result.error_code}",
            model=meta.get("model"), platform=meta.get("platform"),
            duration_ms=meta.get("duration_ms", 0), attempts=meta.get("attempts", 0),
            failures=meta.get("failures", []),
        )

    # ---- DOING → SUBMITTED：确保六节报告落盘 ----
    report_file = Path(task["report_path"] or (task.get("evidence_path") or ""))
    if not (report_file.name and report_file.exists()):
        report_file = Path(task["report_path"] or task["evidence_path"])
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(result.output or "", encoding="utf-8")

    submitted = db.transition_and_log(
        task_id, "SUBMITTED", actor=actor,
        summary=f"{task_id} 已提交回执（等待机器门）",
        extra={
            "model": meta.get("model"),
            "attempts": meta.get("attempts"),
            "session_id": result.session_id,
        },
        report_path=str(report_file),
        evidence_path=str(report_file),
        platform=meta.get("platform"), model=meta.get("model"),
        duration_ms=meta.get("duration_ms", 0), token=result.usage,
        executor_session_id=result.session_id,
        db_file=db_file,
    )
    return DispatchOutcome(
        ok=True, task_id=task_id, state="SUBMITTED",
        detail="submitted", model=meta.get("model"), platform=meta.get("platform"),
        duration_ms=meta.get("duration_ms", 0), attempts=meta.get("attempts", 0),
        failures=meta.get("failures", []), report_path=str(report_file),
    )


def run_to_completion(
    task_id: str,
    *,
    actor: str = "manager",
    router_fn: Callable[..., Any] | None = None,
    policy: retry.RetryPolicy | None = None,
    max_rework_rounds: int = 4,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    """派工 + 机器门 + 审查 + 返工重派，一路推到终态（DONE/PARTIAL/BLOCKED/ESCALATED）。

    REWORK 由 rework_manager 走完整重派；升级 ESCALATED 或 BLOCKED 即停，交人工/上游处理。
    max_rework_rounds 是防呆上限（正常由 rework_count>3 的契约规则先触发）。
    """
    from . import rework_manager

    outcome: dict[str, Any] = {"taskId": task_id, "rounds": []}
    for _ in range(max(1, max_rework_rounds) + 1):
        result = dispatch(task_id, actor=actor, policy=policy, db_file=db_file)
        outcome["rounds"].append(result.to_dict())
        if result.state != "SUBMITTED":
            outcome["state"], outcome["ok"] = result.state, False
            return outcome

        review = reviewer.review(task_id, actor=actor, router_fn=router_fn, db_file=db_file)
        outcome["rounds"].append(review.to_dict())
        if review.verdict in ("PASS", "PARTIAL"):
            # CORE-04 契约 v1.2 §13.3 来源②：任务 DONE 时从六节报告自动提炼 1 条项目记忆
            done_task = db.get_task(task_id, db_file=db_file) or {}
            if done_task.get("project_id"):
                project_memory.distill_from_report(
                    str(done_task["project_id"]),
                    task_id=task_id,
                    title=str(done_task.get("title") or task_id),
                    report_path=done_task.get("report_path") or done_task.get("evidence_path"),
                )
            outcome["state"], outcome["ok"] = review.state, True
            return outcome
        if review.state == "BLOCKED":
            outcome["state"], outcome["ok"] = "BLOCKED", False
            return outcome

        # REWORK（或升级 ESCALATED）→ 交返工管理器
        handled = rework_manager.handle_rework(task_id, actor=actor, db_file=db_file)
        outcome["rounds"].append(handled)
        if handled.get("state") == "ESCALATED":
            outcome["state"], outcome["ok"] = "ESCALATED", False
            return outcome
        # handled.state == ASSIGNED → 继续下一轮派工

    outcome["state"] = db.get_task(task_id, db_file=db_file)["exec_status"]
    outcome["ok"] = False
    return outcome