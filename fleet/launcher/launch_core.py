"""统一启动核心

LaunchRequest + launch_core() 替代 CLI 和 Hermes 两条启动路径。
9步统一流程：env probe → port precheck → ensure_env_file → start console →
start manager gateway → health check → project register SQLite only →
open browser 5000 → pull up watch_events_loop
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from fleet.core import config as fleet_config
from fleet.core.paths import paths


@dataclass
class LaunchRequest:
    """启动请求（CLI 和 Hermes 统一数据结构）"""

    project: str
    mode: str  # run | intake | audit | discuss | plan
    tasks: str = "all"
    requirements: str = ""
    port: int = 5000
    notes: str = ""
    model: str = "auto"
    seats: str = ""
    source: str = "cli"  # cli | hermes
    project_path: str = ""  # 项目工作区绝对路径；空则回退用项目名（兼容旧调用）


def _configure_stdio() -> None:
    """Windows 控制台默认 GBK，打印 ✓/✗/⚠ 会抛 UnicodeEncodeError 直接中断启动；
    统一切到 UTF-8 并以 replace 容错，任何不可编码字符都降级而非崩溃。"""
    for stream in (sys.stdout, sys.stderr):
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """子进程环境：强制 UTF-8 输出，避免控制台进程继承 GBK 后打印符号崩溃。"""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if extra:
        env.update(extra)
    return env


def _check_port(port: int) -> bool:
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _get_creationflags() -> int:
    """获取Windows子进程创建标志"""
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        return subprocess.CREATE_NO_WINDOW
    return 0


def _probe_versions() -> dict[str, str]:
    """探测Python和Hermes版本，返回版本信息"""
    versions = {}

    # Python
    try:
        result = subprocess.run(
            [sys.executable, "--version"],
            capture_output=True,
            text=True,
            creationflags=_get_creationflags(),
        )
        versions["python"] = result.stdout.strip()
    except Exception as e:
        versions["python"] = f"ERROR: {e}"

    # Hermes
    try:
        result = subprocess.run(
            ["hermes", "--version"],
            capture_output=True,
            text=True,
            creationflags=_get_creationflags(),
        )
        versions["hermes"] = result.stdout.strip().split("\n")[0]
    except Exception as e:
        versions["hermes"] = f"ERROR: {e}"

    return versions


def _ensure_env_file() -> bool:
    """确保 .env 文件存在（从 .env.example 复制）"""
    p = paths()
    if p.env_file.exists():
        return True
    if p.env_example_file.exists():
        p.env_file.write_text(
            p.env_example_file.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        print(f"  ✓ 已从 .env.example 创建 .env")
        return True
    print(f"  ✗ .env.example 不存在，无法创建 .env")
    return False


def _start_console(port: int) -> bool:
    """启动控制台（python -m fleet.console.server）"""
    print(f"\n=== 启动控制台 (端口 {port}) ===")
    try:
        creationflags = _get_creationflags()
        subprocess.Popen(
            [sys.executable, "-m", "fleet.console.server"],
            cwd=str(paths().root),
            env=_child_env({"FLEET_CONSOLE_PORT": str(port)}),
            creationflags=creationflags,
        )
        print(f"  ✓ 控制台启动命令已发送")
        return True
    except Exception as e:
        print(f"  ✗ 控制台启动失败: {e}")
        return False


def _start_manager_gateway(port: int = 9900) -> bool:
    """启动Manager网关"""
    print(f"\n=== 启动Manager网关 (端口 {port}) ===")
    try:
        creationflags = _get_creationflags()
        subprocess.Popen(
            ["hermes", "-p", "manager", "gateway", "run"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        print(f"  ✓ Manager网关启动命令已发送")
        return True
    except Exception as e:
        print(f"  ✗ Manager网关启动失败: {e}")
        return False


def _health_check(console_port: int = 5000, manager_port: int = 9900) -> dict[str, bool]:
    """探活检查"""
    import json
    import urllib.request

    print("\n=== 健康检查 ===")
    result = {"console": False, "manager": False}

    # 检查控制台
    try:
        url = f"http://127.0.0.1:{console_port}/api/health"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            if (isinstance(data.get("version"), str) and data["version"]
                    and all(data.get(key) is True for key in ("db", "events", "config"))):
                print(f"  ✓ 控制台健康检查通过")
                result["console"] = True
            else:
                print(f"  ✗ 控制台健康检查失败: {data}")
    except Exception as e:
        print(f"  ⚠ 控制台健康检查跳过: {e}")

    # 检查Manager网关
    try:
        url = f"http://127.0.0.1:{manager_port}/.well-known/agent-card.json"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            if data.get("name") == "Hermes-Manager":
                print(f"  ✓ Manager网关健康检查通过")
                result["manager"] = True
            else:
                print(f"  ✗ Manager网关名称不匹配: {data}")
    except Exception as e:
        print(f"  ⚠ Manager网关健康检查跳过: {e}")

    return result


def _register_project(project_name: str, project_path: str) -> Optional[str]:
    """注册项目到SQLite（仅SQLite，不写projects.json）"""
    from fleet.core import db

    print(f"\n=== 注册项目: {project_name} ===")

    # 检查路径是否在允许的根目录内
    cfg = fleet_config.load("basic")
    # allowed_roots 在 config.py 里以 list 类型解析（FLEET_ALLOWED_ROOTS 逗号串 → list），
    # 旧写法 `str(cfg.get("allowed_roots", ""))` 对 list 会 AttributeError。
    raw_allowed = cfg.get("allowed_roots", [])
    if isinstance(raw_allowed, str):
        allowed_roots = [r.strip() for r in raw_allowed.split(",") if r.strip()]
    elif isinstance(raw_allowed, list):
        allowed_roots = [str(r).strip() for r in raw_allowed if str(r).strip()]
    else:
        allowed_roots = []
    if not allowed_roots:
        # 从系统环境变量读取
        env_roots = os.environ.get("FLEET_ALLOWED_ROOTS", "")
        allowed_roots = [r.strip() for r in env_roots.split(",") if r.strip()]

    project_path_resolved = Path(project_path).resolve()
    is_allowed = False
    for root in allowed_roots:
        try:
            if str(project_path_resolved).startswith(str(Path(root).resolve())):
                is_allowed = True
                break
        except Exception:
            continue

    if not is_allowed and allowed_roots:
        print(f"  ✗ 项目路径不在允许的根目录内: {project_path}")
        print(f"    允许的根目录: {allowed_roots}")
        return None

    # 检查项目是否已存在
    projects = db.list_projects()
    for p in projects:
        if p.get("name") == project_name:
            pid = p.get("project_id") or p.get("id")
            print(f"  ✓ 项目已存在: {pid}")
            return pid

    # 创建新项目（db.create_project 签名：project_id, name, path, port=None）
    pid = f"P-{len(projects) + 1:03d}"
    db.create_project(pid, project_name, str(project_path_resolved))
    print(f"  ✓ 项目已创建: {pid}")
    return pid


def _open_browser(port: int = 5000) -> None:
    """打开浏览器"""
    print(f"\n=== 打开浏览器 ===")
    url = f"http://127.0.0.1:{port}/"
    webbrowser.open(url)
    print(f"  ✓ 已打开: {url}")


def _start_watch_events_loop(project_id: str) -> Optional[asyncio.Task]:
    """启动事件监控循环（异步）"""
    try:
        from fleet.notify.triggers import watch_events_loop, get_trigger

        trigger_svc = get_trigger()

        def _run_loop():
            watch_events_loop(project_id, trigger_svc)

        # 在新线程中运行（避免阻塞主线程）
        import threading
        thread = threading.Thread(target=_run_loop, daemon=True, name=f"watch-{project_id}")
        thread.start()
        print(f"  ✓ 事件监控已启动 (project={project_id})")
        return None  # 返回None表示已启动线程
    except Exception as e:
        print(f"  ⚠ 事件监控启动失败: {e}")
        return None


def launch_core(request: LaunchRequest) -> dict:
    """统一流程：9步启动

    Returns:
        dict: 启动结果 {"ok": bool, "project_id": str, "errors": list}
    """
    console_url = f"http://127.0.0.1:{request.port}/"
    manager_port = int(os.environ.get("FLEET_MANAGER_PORT", "9900"))
    result = {"ok": False, "project_id": None, "errors": [], "warnings": [],
              "steps": [], "console_url": console_url}

    _configure_stdio()

    print("=" * 60)
    print(f"Fleet 启动器 - {request.source.upper()}模式")
    print(f"项目: {request.project} | 模式: {request.mode} | 端口: {request.port}")
    print("=" * 60)

    # Step 1: env probe
    print("\n[1/9] 环境探测")
    versions = _probe_versions()
    for name, ver in versions.items():
        status = "✓" if not ver.startswith("ERROR") else "✗"
        print(f"  {status} {name}: {ver}")
    result["steps"].append({"step": "env_probe", "ok": True, "versions": versions})

    # Step 2: port precheck
    print("\n[2/9] 端口预检")
    ports_to_check = sorted({request.port, manager_port})
    for port in ports_to_check:
        occupied = _check_port(port)
        status = "✓ 空闲" if not occupied else "⚠ 被占用"
        print(f"  端口 {port}: {status}")
    result["steps"].append({"step": "port_precheck", "ok": True})

    # Step 3: ensure_env_file
    print("\n[3/9] 配置文件检查")
    env_ok = _ensure_env_file()
    result["steps"].append({"step": "ensure_env_file", "ok": env_ok})
    if not env_ok:
        result["errors"].append("无法创建 .env 文件")
        return result

    # Step 4: 已占用端口只探活复用，不能再次启动另一个控制台。
    print("\n[4/9] 启动控制台")
    reused = _check_port(request.port)
    console_started = reused or _start_console(request.port)
    result["steps"].append({"step": "start_console", "ok": console_started, "reused": reused})
    if not console_started:
        result["errors"].append("控制台进程启动失败")
        return result

    # 内置调度器不依赖 Hermes 网关；网关不可用需明确报告降级。
    print("\n[5/9] 启动Manager网关")
    manager_started = _check_port(manager_port) or _start_manager_gateway(manager_port)
    result["steps"].append({"step": "start_manager_gateway", "ok": manager_started})

    print("\n[6/9] 健康检查")
    if not reused:
        time.sleep(1)
    health = _health_check(request.port, manager_port)
    result["steps"].append({"step": "health_check", "ok": health["console"], "health": health})
    if not health["console"]:
        result["errors"].append("控制台健康检查失败，停止项目注册与执行")
        return result
    if not health["manager"]:
        result["warnings"].append("Hermes Manager 网关不可用；仅使用控制台内置调度器与 CLI 执行体")

    # Step 7: project register SQLite only
    print("\n[7/9] 项目注册")
    register_path = request.project_path or request.project
    pid = _register_project(request.project, register_path)
    if not pid:
        result["errors"].append("项目注册失败")
    result["project_id"] = pid
    result["steps"].append({"step": "project_register", "ok": pid is not None, "pid": pid})

    # Step 8: open browser 5000
    print("\n[8/9] 打开浏览器")
    _open_browser(request.port)
    result["steps"].append({"step": "open_browser", "ok": True})

    # Step 9: pull up watch_events_loop
    print("\n[9/9] 启动事件监控")
    if pid:
        _start_watch_events_loop(pid)
    result["steps"].append({"step": "watch_events_loop", "ok": True})

    # REL-01：watchdog 进程守护（FLEET_WATCHDOG=1 开启，缺省关，遵循 FLEET_SCHEDULER 模式）
    if os.environ.get("FLEET_WATCHDOG") == "1":
        try:
            from fleet.rel.watchdog import spawn_for_console

            spawn_for_console(request.port)
            print("  ✓ watchdog 守护已启动（FLEET_WATCHDOG=1）")
        except Exception as e:
            print(f"  ⚠ watchdog 启动失败: {e}")

    # 汇总
    result["ok"] = len(result["errors"]) == 0 and pid is not None

    print("\n" + "=" * 60)
    if result["ok"]:
        print(f"✓ Fleet启动完成！")
        print(f"  项目ID: {pid}")
        print(f"  控制台: {console_url}")
        if health["manager"]:
            print(f"  Manager: http://127.0.0.1:{manager_port}")
        for warning in result["warnings"]:
            print(f"  ⚠ {warning}")
    else:
        print(f"✗ Fleet启动完成（有错误）:")
        for err in result["errors"]:
            print(f"  - {err}")
    print("=" * 60)

    return result
