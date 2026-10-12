"""这是什么：fleet CLI（方案 §4 目标入口）：init / up / run / doctor / worker / next / writeback / skills。
怎么用（安装后）：
    fleet init            向导：扫描已装 CLI、探测模型 key 环境变量、写 fleet.toml 默认配置
    fleet up              进程管理器：拉起 api（控制台）+ worker，日志落 data/logs/，健康轮询 20s
    fleet run             旧交互式启动（launch_core 9 步流程，兼容保留）
    fleet doctor          对每个 harness profile 跑 detect+auth_check；--config 打印生效配置与来源
    fleet worker          常驻 worker 循环（kernel 侧执行器）
    fleet next --agent X  宿主内驱动：认领一个 todo 并打印 packet JSON（供 /fleet skill 使用）
    fleet writeback ...   宿主内驱动：写回执行结果
    fleet skills install  把 /fleet skill 装进 Claude Code / Codex / OpenCode
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from fleet.core.paths import paths

from fleet.core.ports import DEFAULT_CONSOLE_PORT
from fleet.cli.pidutil import write_pidfile, read_pidfile, stop_fleet, pidfile_path

DEFAULT_PORT = DEFAULT_CONSOLE_PORT


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


# ---------------------------------------------------------------------------
# init：向导生成 fleet.toml
# ---------------------------------------------------------------------------

_PROBE_HARNESSES = ["claude", "codex", "opencode"]
_PROBE_KEY_VARS = [
    "AGNES_API_KEY", "MODELSCOPE_API_KEY", "BIGMODEL_API_KEY", "BAI_API_KEY",
    "AMD_API_KEY", "NVIDIA_API_KEY", "SENSNOVA_API_KEY", "V3_API_KEY",
]


def cmd_init(args: argparse.Namespace) -> int:
    from fleet.executors.base import resolve_cli
    from fleet.core import fleet_toml

    root = paths().root
    # 零基础体验：检测 Node.js，缺失时提示安装
    try:
        from fleet.setup import core as _setup_core
        if not _setup_core.ensure_node_available():
            print("== ⚠ Node.js 未检测到 ==")
            print("  Node.js >= 20 是安装 CLI 执行体（claude/codex/opencode 等）的前置依赖。")
            if os.name != "nt":
                print("  输入 yes 自动下载安装 Node.js 到私有目录，或按回车跳过：")
                try:
                    choice = input("  自动安装 Node.js? [yes/no] ").strip().lower()
                except EOFError:
                    choice = "no"
                if choice in ("yes", "y", "是"):
                    ok, msg = _setup_core.install_node_binary()
                    print(f"  {'✓' if ok else '✗'} {msg}")
                else:
                    print("  跳过。后续可用 `fleet setup install node` 或手动安装。")
            else:
                print("  Windows 用户请运行安装器（Inno Setup），或手动安装 Node.js >= 20。")
        else:
            print("✓ Node.js 已就绪")
    except Exception as _e:
        pass  # 不阻塞 init 流程

    target = root / fleet_toml.CONFIG_NAME
    if target.exists() and not args.force:
        print(f"✓ {fleet_toml.CONFIG_NAME} 已存在（--force 覆盖）：{target}")
        return 0

    print("== 扫描已安装的 CLI ==")
    found: list[str] = []
    for name in _PROBE_HARNESSES:
        resolved = resolve_cli(name)
        installed = resolved != name or bool(Path(resolved).exists())
        print(f"  {'✓' if installed else '✗'} {name}: {resolved if installed else '未安装'}")
        if installed:
            found.append(name)

    print("== 探测模型 API key 环境变量 ==")
    keys_present = [var for var in _PROBE_KEY_VARS if os.environ.get(var)]
    for var in _PROBE_KEY_VARS:
        state = "✓ 已设置" if var in keys_present else "✗ 未设置"
        print(f"  {state} {var}")

    allowed_roots = str(root) if not args.roots else args.roots
    lines = [
        "# fleet.toml —— fleet init 生成的默认配置（密钥只写环境变量名，绝不写值）",
        "# 优先级：环境变量 > fleet.toml > 内置默认；fleet doctor --config 查看生效值与来源",
        "",
        "[workspace]",
        f"allowed_roots = [\"{allowed_roots.replace(chr(92), '/')}\"]",
        "",
        "[runtime]",
        'scheduler = "auto"',
        "lease_minutes = 15",
        "",
    ]
    if found:
        lines += ["[roles.default]", f"harness = {json.dumps(found)}", ""]
    if not found:
        lines += [
            "# 未检测到任何执行体 CLI；宿主内驱动（/fleet skill）不依赖它们：",
            "# 在 Claude Code / Codex / OpenCode 里运行 `fleet skills install` 后使用 /fleet <任务>。",
            "",
        ]
    target.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ 已写出 {target}")
    return 0


# ---------------------------------------------------------------------------
# doctor：harness 探测 + 配置打印
# ---------------------------------------------------------------------------

def cmd_doctor(args: argparse.Namespace) -> int:
    from fleet.harness import auth_check, detect, load_profile, available_profiles
    from fleet.core import fleet_toml

    _configure_stdio()
    if args.config:
        cfg = fleet_toml.load_config()
        print(fleet_toml.print_config_source(cfg))
        return 0

    print("== Harness Profiles 探测 ==")
    failures = 0
    missing_components: list[str] = []
    for name in available_profiles():
        try:
            profile = load_profile(name)
        except Exception as exc:
            print(f"  ✗ {name}: profile 加载失败: {exc}")
            failures += 1
            continue
        ok, detail = detect(profile)
        if not ok:
            print(f"  ✗ {name}: 未安装/不可用（{detail}）→ 修复命令: fleet setup install {name}")
            missing_components.append(name)
            failures += 1
            continue
        auth_ok, auth_detail = auth_check(profile)
        if auth_ok:
            print(f"  ✓ {name}: 已安装且已登录/可用")
        else:
            print(f"  ⚠ {name}: 已安装但未登录/不可用（{auth_detail}）→ 修复: 打开控制台 /setup 第 3 步点『去登录』")
            failures += 1
    if failures:
        if missing_components:
            print(f"\n一键修复: fleet setup install {' '.join(missing_components)}")
        print(f"{failures} 个 profile 不可用——对应角色的任务会自动降级到链中下一个执行体。")
        return 1
    print("\n全部 profile 可用。")
    return 0


# ---------------------------------------------------------------------------
# up：进程管理器拉起 api + worker
# ---------------------------------------------------------------------------

def _log_file(name: str) -> Path:
    log_dir = paths().ensure_dir(paths().data_dir / "logs")
    stamp = time.strftime("%Y%m%d")
    return log_dir / f"{name}-{stamp}.log"


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _loopback_opener():
    """F-07 修复：127.0.0.1 探活绝不走系统代理（HTTP(S)_PROXY 会把回环请求交给代理）。"""
    import urllib.request

    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _wait_healthy(port: int, timeout_s: float = 20.0, interval_s: float = 0.5) -> bool:
    """健康检查轮询：每 0.5s、最长 20s（U1 修复的 CLI 侧同款语义）。"""
    import urllib.request

    opener = _loopback_opener()
    deadline = time.monotonic() + timeout_s
    url = f"http://127.0.0.1:{port}/api/health"
    while time.monotonic() < deadline:
        try:
            with opener.open(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(interval_s)
    return False


def cmd_up(args: argparse.Namespace) -> int:
    _configure_stdio()
    port = args.port
    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    _api_pid = None
    if _port_open(port):
        print(f"⚠ 端口 {port} 已被占用——复用既有控制台（若非 Fleet 实例请换 --port）")
    else:
        api_log = open(_log_file("api"), "ab")
        print(f"→ 启动 api（控制台 :{port}），日志: {_log_file('api')}")
        _api_proc = subprocess.Popen(
            [sys.executable, "-m", "fleet.console.server"],
            cwd=str(paths().root), env={**os.environ, "FLEET_CONSOLE_PORT": str(port)},
            stdout=api_log, stderr=subprocess.STDOUT, creationflags=creationflags,
        )
        _api_pid = _api_proc.pid
    ready = _wait_healthy(port)
    if not ready:
        print(f"✗ 控制台在 20s 内未就绪；最后日志：")
        _print_log_tail(_log_file("api"), 50)
        return 1
    print(f"✓ api 就绪: http://127.0.0.1:{port}/")

    # TASK-204：--open 自动开浏览器；ready 判定来自 fleet.setup.status
    if args.open:
        target = "/tasks"
        try:
            from fleet.setup import core as setup_core

            target = "/tasks" if setup_core.status()["ready"] else "/setup"
        except Exception:
            target = "/setup"
        url = f"http://127.0.0.1:{port}{target}"
        import webbrowser

        webbrowser.open(url)
        print(f"✓ 已打开浏览器: {url}")

    if not args.no_worker:
        worker_log = open(_log_file("worker"), "ab")
        print(f"→ 启动 worker，日志: {_log_file('worker')}")
        _worker_proc = subprocess.Popen(
            [sys.executable, "-m", "fleet.cli.main", "worker", "--loop"],
            cwd=str(paths().root),
            stdout=worker_log, stderr=subprocess.STDOUT, creationflags=creationflags,
        )
        print("✓ worker 已启动（单写者内核：kernel.db）")
        write_pidfile({"api": _api_pid, "worker": _worker_proc.pid, "port": port,
                       "started": time.strftime("%Y-%m-%dT%H:%M:%S")})
    else:
        write_pidfile({"api": _api_pid, "worker": None, "port": port,
                       "started": time.strftime("%Y-%m-%dT%H:%M:%S")})
    print("\n完成。fleet down 可停止后台服务；Ctrl+C 退出本进程不会停掉后台服务。")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nbye")
    return 0


def cmd_launch(args: argparse.Namespace) -> int:
    """一键启动：等价于 fleet up --open --no-worker，小白双击图标即可。"""
    args.open = True
    args.no_worker = True
    if not hasattr(args, 'port'):
        args.port = DEFAULT_PORT
    return cmd_up(args)


def cmd_down(args: argparse.Namespace) -> int:
    """停止 fleet up 拉起的 api + worker 进程。"""
    _configure_stdio()
    result = stop_fleet()
    if result.get("stopped"):
        details = result.get("details", {})
        for key in ("api", "worker"):
            d = details.get(key, {})
            pid = d.get("pid")
            if pid:
                status = "✓ 已停止" if d.get("stopped") else "✗ 停止失败"
                print(f"  {status} {key} (pid={pid})")
            else:
                print(f"  · {key}: 未运行")
        print("✓ fleet 已停止")
    else:
        print(f"✗ {result.get('reason', '停止失败')}")
    return 0


def _print_log_tail(path: Path, lines: int) -> None:
    if not path.is_file():
        print("  （日志文件尚未生成）")
        return
    tail = path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    for line in tail:
        print(f"  | {line}")


# ---------------------------------------------------------------------------
# worker：kernel 侧执行器
# ---------------------------------------------------------------------------

def cmd_worker(args: argparse.Namespace) -> int:
    from fleet.kernel import Kernel
    from fleet.runner import run_loop

    _configure_stdio()
    kernel = Kernel(paths().data_dir / "kernel.db")
    worker = f"worker-{os.getpid()}"

    # F-01/F-06 修复（ADR-004 选项 C）：planner_client 与 model_for 在 fleet/cli 组装注入
    from fleet.cli import clients

    planner_client = clients.make_planner_client("planner")
    model_for = clients.model_for

    def _on_round(outcome: dict) -> None:
        detail = str(outcome.get("detail") or outcome.get("result") or "")
        print(f"[{worker}] {outcome.get('action')} {outcome.get('todo') or ''} {detail[:160]}")

    if args.loop:
        run_loop(kernel, worker=worker, planner_client=planner_client, model_for=model_for,
                 on_round=_on_round, workspace_root=args.workspace or "")
        return 0
    from fleet.runner import run_once
    outcome = run_once(kernel, worker=worker, planner_client=planner_client,
                       model_for=model_for, workspace_root=args.workspace or "")
    print(json.dumps(outcome, ensure_ascii=False, default=str)[:2000])
    if outcome.get("action") == "writeback":
        kernel.transition(outcome["todo"], outcome["result"])
        print(f"✓ 已写回: {outcome['todo']} -> {outcome['result'].verdict}")
    return 0


# ---------------------------------------------------------------------------
# next / writeback：宿主内驱动（P4）
# ---------------------------------------------------------------------------

def cmd_next(args: argparse.Namespace) -> int:
    from fleet.kernel import Kernel

    kernel = Kernel(paths().data_dir / "kernel.db")
    # --agent 是认领者身份（哪个宿主/执行体来干活），不按角色过滤：
    # todo 的 role 决定 harness 链，host 模式下任何可认领 todo 都可以交给当前会话。
    claimables = kernel.claimable()
    if not claimables:
        print(json.dumps({"todo": None, "reason": "no_runnable_todo"}, ensure_ascii=False))
        return 0
    todo = claimables[0]
    agent = args.agent or "host"
    kernel.claim(todo["id"], worker=agent, harness="host")
    kernel.mark_running(todo["id"], agent)  # F-03 修复：host 写回 done 需要 verifying 态
    packet = kernel.packet_for(todo["id"])
    print(json.dumps(packet, ensure_ascii=False, indent=2))
    return 0


def cmd_writeback(args: argparse.Namespace) -> int:
    """宿主内写回（TASK-401）：done 前由 Fleet 自己跑机器门（F-04 修复）。

    B4：--agent 必须与 todo.claimed_by 一致，否则拒绝且状态不变。
    语义：done → mark_verifying → run_verify(verify, workspace) → 通过=done / 不通过=successor。
    """
    from fleet.kernel import Kernel
    from fleet.kernel.state import TurnResult
    from fleet.runner import gates

    kernel = Kernel(paths().data_dir / "kernel.db")
    todo = kernel.get_todo(args.todo)
    agent = args.agent or "host"
    if todo["claimed_by"] and todo["claimed_by"] != agent:
        print(json.dumps({
            "ok": False,
            "error": f"todo 被认领人 {todo['claimed_by']} 持有，写入方 {agent} 不一致（identity B4）",
            "reason": "HOLD_MISMATCH",
        }, ensure_ascii=False))
        return 3

    evidence = args.evidence or ""
    if evidence and Path(evidence).is_file():
        evidence = Path(evidence).read_text(encoding="utf-8", errors="replace")[:20000]

    if args.verdict == "done":
        if todo["status"] == "claimed":
            kernel.mark_running(args.todo, agent)
        if todo["status"] in ("claimed", "running"):
            kernel.mark_verifying(args.todo, agent)
        workspace = todo["workspace"]
        report = gates.run_verify(todo["verify"], workspace) if todo["verify"] else None
        evidence_dir = Path(paths().data_dir) / "evidence" / args.todo
        if report is not None:
            gates.save_evidence(evidence_dir, report, "")
        if report is not None and not report.ok:
            summary = report.summary()
            (evidence_dir / "writeback_note.txt").write_text(
                "host 写回被机器门拦截：\n" + summary + "\n\nhost note: " + (args.note or ""),
                encoding="utf-8")
            result = TurnResult(
                verdict="successor",
                note="host 写回 done 被机器门拦截，转返工：\n" + summary,
                successor={
                    "title": todo["title"], "role": todo["role"],
                    "allowed_files": todo["allowed_files"], "verify": todo["verify"],
                    "done_when": todo["done_when"], "workspace": workspace,
                    "packet": (todo["packet"] or "")
                              + "\n\n【上一轮机器门结果】机器门未通过，按以下失败项修复：\n" + summary,
                },
            )
        else:
            # O-01 修复：exec todo 无 verify 命令时，不接受任意文本作为证据；
            # 必须提供真实证据文件路径（已读取为内容）或由机器门产生证据。
            if not todo["verify"] and not evidence:
                print(json.dumps({
                    "ok": False,
                    "error": "exec todo 无 verify 命令，必须提供 --evidence 指向真实证据文件",
                    "reason": "EVIDENCE_REQUIRED",
                }, ensure_ascii=False))
                return 1
            result = TurnResult(
                verdict="done",
                note=args.note or "",
                evidence_path=str(evidence_dir) if report is not None else (evidence or ""),
            )
    else:
        result = TurnResult(
            verdict=args.verdict,
            note=args.note or "",
            evidence_path=evidence,
            successor={"title": args.successor_title or f"{todo['title']}（返工）"} if args.verdict == "successor" else {},
        )

    updated = kernel.transition(args.todo, result)
    print(json.dumps({"ok": True, "todo": updated["id"], "status": updated["status"],
                      "verdict": args.verdict}, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# skills：宿主内 /fleet skill 安装（P4）
# ---------------------------------------------------------------------------

_SKILL_BODY = """---
name: fleet
description: 通过 AideanFleet kernel 认领任务、执行并写回（宿主内驱动）
---

# /fleet —— AideanFleet 宿主内驱动

当用户输入 `/fleet <任务描述>` 时：

1. 运行 `fleet init`（仅首次）与 `fleet doctor` 确认内核可用。
2. 运行 `python -m fleet.cli.main next --agent claude --json` 认领一个 todo；
   返回 `{"todo": null}` 说明当前无可认领任务，直接如实告知用户。
3. 按 packet 执行任务：只改 allowed_files 白名单内文件；workspace 是 packet.todo.workspace。
4. 完成任务后写回（机器门由 writeback 自动执行，你不必伪造通过）：
   `python -m fleet.cli.main writeback --todo <id> --agent claude --verdict done --note "<改动摘要>"`
   gate 未通过会自动转返工 successor（你重新 next 认领即可修复）；被阻塞 `--verdict blocked`。
5. 需要继续跑后续任务时，回到第 2 步（平级会话通过 claim 互斥，不会撞车）。
"""


def cmd_skills(args: argparse.Namespace) -> int:
    home = Path.home()
    targets = {
        "claude": home / ".claude" / "skills" / "fleet" / "SKILL.md",
        "codex": home / ".codex" / "skills" / "fleet" / "SKILL.md",
        "opencode": home / ".config" / "opencode" / "skills" / "fleet" / "SKILL.md",
    }
    chosen = [args.host] if args.host else list(targets)
    for host in chosen:
        path = targets.get(host)
        if path is None:
            print(f"✗ 未知宿主: {host}（允许 {sorted(targets)}）")
            return 2
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_SKILL_BODY, encoding="utf-8")
        print(f"✓ 已安装 /fleet skill -> {path}")
    return 0


# ---------------------------------------------------------------------------
# argparse 装配
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fleet", description="AideanFleet 控制面 CLI")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="向导生成 fleet.toml 默认配置")
    p_init.add_argument("--force", action="store_true", help="覆盖已有 fleet.toml")
    p_init.add_argument("--roots", default="", help="允许的项目根目录（逗号分隔）")
    p_init.set_defaults(func=cmd_init)

    p_doctor = sub.add_parser("doctor", help="执行体/配置体检")
    p_doctor.add_argument("--config", action="store_true", help="打印生效配置与来源")
    p_doctor.set_defaults(func=cmd_doctor)

    p_up = sub.add_parser("up", help="拉起 api + worker")
    p_up.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_up.add_argument("--open", action="store_true", help="就绪后自动打开浏览器（未就绪进 /setup）")
    p_up.add_argument("--no-worker", action="store_true", help="只起控制台")
    p_up.set_defaults(func=cmd_up)

    p_down = sub.add_parser("down", help="停止 fleet up 拉起的 api + worker")
    p_down.set_defaults(func=cmd_down)

    p_launch = sub.add_parser("launch", help="一键启动：拉起控制台并打开浏览器（小白入口）")
    p_launch.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_launch.set_defaults(func=cmd_launch)

    p_worker = sub.add_parser("worker", help="kernel 侧 worker")
    p_worker.add_argument("--loop", action="store_true", help="常驻循环")
    p_worker.add_argument("--workspace", default="", help="缺省工作区（todo 未带 workspace 时用）")
    p_worker.set_defaults(func=cmd_worker)

    p_next = sub.add_parser("next", help="宿主内驱动：认领 todo 并打印 packet")
    p_next.add_argument("--agent", default="", help="执行体/宿主名（如 claude）")
    p_next.add_argument("--json", action="store_true", help="JSON 输出（默认即 JSON）")
    p_next.set_defaults(func=cmd_next)

    p_wb = sub.add_parser("writeback", help="宿主内驱动：写回执行结果")
    p_wb.add_argument("--todo", required=True)
    p_wb.add_argument("--verdict", required=True,
                      choices=["done", "successor", "blocked", "needs_user"])
    p_wb.add_argument("--agent", default="host", help="写入方身份（必须与认领人一致，B4）")
    p_wb.add_argument("--note", default="")
    p_wb.add_argument("--evidence", default="", help="证据文件路径或文本")
    p_wb.add_argument("--successor-title", default="")
    p_wb.set_defaults(func=cmd_writeback)

    p_skill = sub.add_parser("skills", help="宿主内 /fleet skill 安装")
    p_skill.add_argument("action", choices=["install"])
    p_skill.add_argument("--host", default="", help="claude|codex|opencode（缺省全装）")
    p_skill.set_defaults(func=cmd_skills)

    p_setup = sub.add_parser("setup", help="组件安装与状态（= python -m fleet.setup）")
    p_setup.add_argument("setup_args", nargs=argparse.REMAINDER)
    p_setup.set_defaults(func=_run_fleet_setup)

    p_run = sub.add_parser("run", help="旧交互式启动（兼容保留）")
    p_run.set_defaults(func=lambda args: _legacy_run())

    return parser


def _run_fleet_setup(args: argparse.Namespace) -> int:
    """fleet setup → python -m fleet.setup（输出保持一致，TASK-204 验收）。"""
    from fleet.setup import __main__ as setup_main

    return setup_main.main(list(args.setup_args)) or 0


def _legacy_run() -> int:
    from fleet.launcher.cli_start import main as cli_start_main

    return cli_start_main() or 0


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n中断")
        return 130


if __name__ == "__main__":
    sys.exit(main())
