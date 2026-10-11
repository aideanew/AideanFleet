"""这是什么：Turn Runner（P1，取代 scheduler 线程 + dispatcher 的 kernel 侧执行器）。
每轮 8 步（对标方案 4.2）：
  1 should_run  2 claim(lease)  3 组装 packet  4 调 harness（流式+续约）
  5 gate（真实 verify）  6 写回（done/successor/blocked/needs_user）  7 计费在写回内  8 下一轮
并发：kernel.claimable 已按 allowed_files 顶层域互斥；推荐每任务一个 git worktree（由上层编排）。
Harness 链：来自 fleet.toml [roles.<role>] harness=[...]；缺省 ["claude","codex","opencode"]；
  逐个 detect，第一个可用者执行；全部不可用 → blocked（原因写明，UI 标红）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from ..harness import HarnessProfile, detect as harness_detect, load_profile, run_profile
from ..kernel import Kernel
from ..kernel import state as st
from ..kernel.state import TurnResult
from . import gates

DEFAULT_HARNESS_CHAIN = ["claude", "codex", "opencode"]


def packet_prompt(packet: dict) -> str:
    """把 kernel packet 组装成给执行体的提示词（目标+任务+白名单+验收+写回格式）。"""
    todo = packet["todo"]
    goal = packet["goal"] or {}
    lines = [
        f"# 任务：{todo['title']}",
        "",
        f"## 总目标\n{goal.get('title', '')}",
        f"## 任务说明\n{todo.get('packet') or todo['title']}",
        "",
        f"## 允许改动的文件\n{json.dumps(todo['allowed_files'], ensure_ascii=False)}",
        f"## 完成判定\n{todo['done_when'] or '通过下述验收命令'}",
        "## 验收命令（必须真实执行并通过）\n"
        + "\n".join(f"- `{cmd}`" for cmd in todo["verify"]),
        "",
        "## 规则\n" + "\n".join(f"- {rule}" for rule in packet["rules"]),
        "## 其他任务（避免越界）\n"
        + json.dumps(packet["siblings"], ensure_ascii=False),
    ]
    return "\n".join(lines)


def _harness_chain_for(role: str) -> list[str]:
    """角色 → 执行体链（fleet.toml [roles.X] harness）；缺省通用链。"""
    try:
        from ..core.fleet_toml import load_config

        cfg = load_config()
        role_cfg = cfg.roles.get(role)
        chain = role_cfg.harness if role_cfg else []
        return [str(h) for h in chain] or list(DEFAULT_HARNESS_CHAIN)
    except Exception:
        return list(DEFAULT_HARNESS_CHAIN)


def _pick_harness(chain: list[str]) -> tuple[HarnessProfile | None, str]:
    for name in chain:
        try:
            profile = load_profile(name)
        except (FileNotFoundError, ValueError) as exc:
            continue
        ok, reason = harness_detect(profile)
        if ok:
            return profile, ""
    return None, "；".join(f"{n}:{reason}" for n, reason in
                          [(n, harness_detect(load_profile(n))[1]) for n in chain if _loadable(n)])


def _loadable(name: str) -> bool:
    try:
        load_profile(name)
        return True
    except Exception:
        return False


def _evidence_dir(kernel_db: str, todo_id: str) -> Path:
    root = Path(kernel_db).parent / "evidence"
    return root / todo_id


def run_once(
    kernel: Kernel,
    *,
    worker: str,
    planner_client: Callable[[str], str] | None = None,
    model_for: Callable[[str], str] | None = None,
    workspace_root: str = "",
) -> dict:
    """跑一轮：返回 {"action": "done|blocked|idle|...", "todo": id, "detail": str}。"""
    ok, reason = kernel.should_run()
    if not ok:
        return {"action": "idle", "detail": reason}
    candidates = kernel.claimable()
    if not candidates:
        return {"action": "idle", "detail": "no_runnable_todo"}
    todo = candidates[0]
    chain = _harness_chain_for(todo["role"]) if todo["kind"] == "exec" else []
    model = model_for(todo["role"]) if model_for else ""
    profile = None
    if todo["kind"] == "exec":
        profile, detect_fail = _pick_harness(chain)
        if profile is None:
            claimed = kernel.claim(todo["id"], worker)
            return {
                "action": "writeback",
                "todo": todo["id"],
                "result": TurnResult(
                    verdict=st.VERDICT_BLOCKED,
                    note=f"执行体链全部不可用（{chain}）：{detect_fail}",
                ),
                "claimed": claimed,
            }
    claimed = kernel.claim(
        todo["id"], worker,
        harness=profile.name if profile else "planner",
        model=model,
    )
    kernel.mark_running(todo["id"], worker)

    def _renew() -> None:
        try:
            kernel.renew_lease(todo["id"], worker)
        except Exception:
            pass

    # ---- plan / steer 任务：Planner（LLM 拆解 / 对话改计划） ----
    if todo["kind"] in ("plan", "steer"):
        if planner_client is None:
            return {"action": "writeback", "todo": todo["id"],
                    "result": TurnResult(verdict=st.VERDICT_BLOCKED,
                                         note="未配置 planner 模型客户端")}
        kernel.mark_verifying(todo["id"], worker)
        if todo["kind"] == "plan":
            result = _run_planner(kernel, todo["id"], planner_client, _renew)
        else:
            result = _run_steer(kernel, todo["id"], planner_client, _renew)
        return {"action": "writeback", "todo": todo["id"], "result": result, "claimed": claimed}

    # ---- exec 任务：harness → gate → 写回 ----
    assert profile is not None
    workspace = todo["workspace"] or workspace_root
    outcome = run_profile(
        profile,
        packet_prompt(kernel.packet_for(todo["id"])),
        workspace,
        model=model,
        renew=_renew,
    )
    kernel.mark_verifying(todo["id"], worker)
    evidence_dir = _evidence_dir(kernel.db_path, todo["id"])
    if not outcome.ok:
        gates.save_evidence(evidence_dir, gates.GateReport(ok=False), outcome.output)
        return {
            "action": "writeback", "todo": todo["id"], "claimed": claimed,
            "result": TurnResult(
                verdict=st.VERDICT_BLOCKED,
                note=f"harness {profile.name} 执行失败: {outcome.error_code} {outcome.error_msg[:200]}",
                **outcome.to_turn_kwargs(),
            ),
        }
    report = gates.run_verify(todo["verify"], workspace)
    gates.save_evidence(evidence_dir, report, outcome.output)
    if not report.ok:
        return {
            "action": "writeback", "todo": todo["id"], "claimed": claimed,
            "result": TurnResult(
                verdict=st.VERDICT_SUCCESSOR,
                note=f"机器门未通过，需返工：\n{report.summary()}",
                successor={
                    "title": todo["title"], "role": todo["role"],
                    "allowed_files": todo["allowed_files"], "verify": todo["verify"],
                    "done_when": todo["done_when"],
                    "packet": (todo["packet"] or "")
                              + f"\n\n【上一轮机器门结果】机器门未通过，按以下失败项修复：\n{report.summary()}",
                    "workspace": workspace,
                },
                **outcome.to_turn_kwargs(),
            ),
        }
    return {
        "action": "writeback", "todo": todo["id"], "claimed": claimed,
        "result": TurnResult(
            verdict=st.VERDICT_DONE,
            note="机器门通过",
            evidence_path=str(evidence_dir),
            **outcome.to_turn_kwargs(),
        ),
    }


def _run_planner(kernel: Kernel, todo_id: str, client, renew: Callable[[], None]) -> TurnResult:
    renew()
    from ..planner import run_plan_todo

    return run_plan_todo(kernel, todo_id, client)


def _run_steer(kernel: Kernel, todo_id: str, client, renew: Callable[[], None]) -> TurnResult:
    """steer todo：auto 模式（fleet.toml runtime.scheduler=auto）直接应用，否则 needs_user。"""
    renew()
    from ..planner.steer import run_steer_todo

    auto = False
    try:
        from ..core.fleet_toml import load_config

        auto = (load_config().scheduler == "auto")
    except Exception:
        pass
    return run_steer_todo(kernel, todo_id, client, auto_apply=auto)


def run_loop(
    kernel: Kernel,
    *,
    worker: str,
    interval_s: float = 2.0,
    max_rounds: int = 0,
    planner_client: Callable[[str], str] | None = None,
    model_for: Callable[[str], str] | None = None,
    workspace_root: str = "",
    on_round: Callable[[dict], None] | None = None,
) -> None:
    """常驻 worker 循环（fleet worker）。max_rounds=0 表示不限（测试传 1~N）。"""
    rounds = 0
    while True:
        outcome = run_once(kernel, worker=worker, planner_client=planner_client,
                           model_for=model_for, workspace_root=workspace_root)
        if on_round is not None:
            try:
                on_round(outcome)
            except Exception:
                pass
        if outcome["action"] == "writeback":
            kernel.transition(outcome["todo"], outcome["result"])
        else:
            time.sleep(interval_s)
        rounds += 1
        if max_rounds and rounds >= max_rounds:
            return
