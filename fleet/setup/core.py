"""这是什么：fleet.setup —— 零基础安装的组件清单、检测与 CLI 安装作业（TASK-202）。
怎么用：python -m fleet.setup status [--json] / install [components...] [--mirror auto|official|cn]
设计（ADR-003 / DESIGN-001 / schemas/setup-status.json）：
- manifest 唯一源 scripts/installer/manifest.json；打包副本 fleet/setup/_manifest.json 由
  scripts/sync_migrations.py 同步（同一构建期脚本管两类副本），内容一致性由 Guard 测试校验；
- detect：私有运行时（%LOCALAPPDATA%/Programs/AideanFleet）优先，其次系统 PATH；
- install：用私有 npm `npm i -g <pkg>@<min> --prefix <runtime>/npm-global`；
  官方 registry 失败自动切 manifest 国内镜像；grok（official_script）默认不装（A-10）；
- 作业流水 <data_dir>/setup/jobs/<job_id>.jsonl（A-07：不入 kernel.db）；
- 本包禁止 import console/manager（import 边界测试守门）。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fleet.core.paths import paths

MANIFEST_REPO = Path(__file__).resolve().parents[2] / "scripts" / "installer" / "manifest.json"
MANIFEST_PACKAGED = Path(__file__).resolve().parent / "_manifest.json"
INSTALL_STEP_ERRORS = {
    "DOWNLOAD_FAILED", "CHECKSUM_MISMATCH", "NETWORK_BLOCKED", "DISK_FULL", "PERMISSION_DENIED",
    "NPM_INSTALL_FAILED", "VERSION_TOO_OLD", "POST_INSTALL_NOT_ON_PATH", "UNSUPPORTED_ARCH",
}


def manifest_path() -> Path:
    """manifest 唯一源：仓库 scripts/installer/manifest.json；打包环境用副本。"""
    if MANIFEST_REPO.is_file():
        return MANIFEST_REPO
    if MANIFEST_PACKAGED.is_file():
        return MANIFEST_PACKAGED
    raise FileNotFoundError(
        f"manifest 不存在：{MANIFEST_REPO} 与 {MANIFEST_PACKAGED} 均未找到")


def load_manifest() -> dict[str, Any]:
    return json.loads(manifest_path().read_text(encoding="utf-8"))


def runtime_dir() -> Path:
    """私有运行时目录（ADR-003）：Windows %LOCALAPPDATA%/Programs/AideanFleet。"""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Programs" / "AideanFleet"
    return Path.home() / ".aideanfleet"


# ---------------------------------------------------------------------------
# detect
# ---------------------------------------------------------------------------


def _probe_version(cmd: list[str], pattern: str = r"(\d+\.\d+(?:\.\d+)?)") -> str:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        text = (proc.stdout or "") + (proc.stderr or "")
        match = re.search(pattern, text)
        return match.group(1) if match else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _version_at_least(version: str, min_version: str) -> bool:
    def parts(value: str) -> list[int]:
        return [int(p) for p in re.findall(r"\d+", value)][:3]
    try:
        return parts(version) >= parts(min_version)
    except ValueError:
        return False


@dataclass
class Detected:
    name: str
    kind: str          # runtime | cli
    installed: bool
    version: str = ""
    source: str = "none"   # managed | system | none
    detail: str = ""
    npm_pkg: str = ""      # cli 专用
    min_version: str = ""
    default: bool = True


def _detect_entry(entry: dict[str, Any]) -> Detected:
    name = entry["name"]
    detect_cmds = entry.get("detect") or []
    managed_root = runtime_dir()

    # 1) 私有运行时（managed）
    for cmd in detect_cmds:
        candidate = managed_root / cmd[0]
        exe_candidates = [candidate.with_suffix(".cmd"), candidate.with_suffix(".exe"), candidate]
        for exe in exe_candidates:
            if exe.is_file():
                version = _probe_version([str(exe), *cmd[1:]])
                if version:
                    return Detected(name=name, kind=entry.get("kind", "cli"), installed=True,
                                    version=version, source="managed", npm_pkg=entry.get("install", {}).get("package", ""),
                                    min_version=entry.get("min_version", ""), default=entry.get("default", True),
                                    detail=f"私有副本: {exe.parent}")

    # 2) 系统 PATH
    if shutil_which(detect_cmds[0][0] if detect_cmds else ""):
        version = _probe_version([shutil_which(detect_cmds[0][0]) or "", *detect_cmds[0][1:]])
        min_version = entry.get("min_version", "")
        installed = bool(version)
        outdated = installed and min_version and not _version_at_least(version, min_version)
        return Detected(name=name, kind=entry.get("kind", "cli"), installed=installed,
                        version=version, source="system" if installed else "none",
                        npm_pkg=entry.get("install", {}).get("package", ""),
                        min_version=min_version, default=entry.get("default", True),
                        detail=("版本低于下限" if outdated else ""))

    return Detected(name=name, kind=entry.get("kind", "cli"), installed=False,
                    npm_pkg=entry.get("install", {}).get("package", ""),
                    min_version=entry.get("min_version", ""), default=entry.get("default", True),
                    detail="未安装")


def shutil_which(name: str) -> str | None:
    from shutil import which

    return which(name)


def detect_all() -> list[Detected]:
    manifest = load_manifest()
    return [_detect_entry(entry) for entry in manifest.get("components", [])]


def detect_named(name: str) -> Detected | None:
    for detected in detect_all():
        if detected.name == name:
            return detected
    return None


# ---------------------------------------------------------------------------
# 安装作业（jobs）
# ---------------------------------------------------------------------------

_JOB_LOCK = threading.Lock()
_RUNNING_JOB: dict[str, str] = {"id": "", "state": ""}


def jobs_dir() -> Path:
    return paths().ensure_dir(paths().data_dir / "setup" / "jobs")


def _new_job_id() -> str:
    return f"J-{int(time.time() * 1000):x}-1"


def _write_step(job_id: str, record: dict[str, Any]) -> None:
    jobs_dir()
    line = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **record}, ensure_ascii=False)
    with open(jobs_dir() / f"{job_id}.jsonl", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def read_job(job_id: str) -> dict[str, Any] | None:
    file = jobs_dir() / f"{job_id}.jsonl"
    if not file.is_file():
        return None
    steps: list[dict[str, Any]] = []
    state = "queued"
    for line in file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("event") == "job_state":
            state = str(record.get("state") or state)
        elif record.get("event") == "step":
            steps.append(record)
    return {"ok": True, "job_id": job_id, "state": state, "steps": steps}


def install_components(components: list[str], *, mirror: str = "auto") -> str:
    """启动安装作业（后台线程）。并发第二个 install 抛 InstallInProgress。"""
    with _JOB_LOCK:
        if _RUNNING_JOB["id"] and _RUNNING_JOB["state"] in ("queued", "running"):
            raise InstallInProgress(_RUNNING_JOB["id"])
        job_id = _new_job_id()
        _RUNNING_JOB["id"] = job_id
        _RUNNING_JOB["state"] = "running"

    manifest = load_manifest()
    by_name = {entry["name"]: entry for entry in manifest.get("components", [])}
    thread = threading.Thread(
        target=_run_install_job, args=(job_id, components, mirror, by_name), daemon=True)
    thread.start()
    return job_id


class InstallInProgress(RuntimeError):
    def __init__(self, job_id: str) -> None:
        super().__init__(f"已有安装作业进行中：{job_id}")
        self.job_id = job_id


def _npm_registry(mirror: str, entry: dict[str, Any]) -> list[str]:
    urls = entry.get("urls") or {}
    official = urls.get("registry") or "https://registry.npmjs.org"
    cn = urls.get("registry_cn") or "https://registry.npmmirror.com"
    if mirror == "official":
        return [official]
    if mirror == "cn":
        return [cn]
    return [official, cn]  # auto：官方失败切镜像（REQ-NF-05）


def _run_install_job(job_id: str, components: list[str], mirror: str,
                     by_name: dict[str, dict[str, Any]]) -> None:
    final_state = "failed"
    try:
        _write_step(job_id, {"event": "job_state", "state": "running"})
        overall_failed = False
        for name in components:
            entry = by_name.get(name)
            if entry is None:
                _write_step(job_id, {"event": "step", "component": name, "state": "failed",
                                     "error_code": "VALIDATION_FAILED", "log_tail": "manifest 中无此组件"})
                overall_failed = True
                continue
            try:
                ok = _run_component(job_id, entry, mirror)
            except Exception as exc:  # 审计修复：任何意外异常都落为该组件失败，作业不得卡在 running
                _write_step(job_id, {"event": "step", "component": name, "state": "failed",
                                     "error_code": "NPM_INSTALL_FAILED",
                                     "log_tail": f"{type(exc).__name__}: {exc}"[-4000:]})
                ok = False
            if not ok:
                overall_failed = True
        final_state = "failed" if overall_failed else "succeeded"
    finally:
        try:
            _write_step(job_id, {"event": "job_state", "state": final_state})
        finally:
            with _JOB_LOCK:
                if _RUNNING_JOB["id"] == job_id:
                    _RUNNING_JOB["id"] = ""
                    _RUNNING_JOB["state"] = final_state


def _run_component(job_id: str, entry: dict[str, Any], mirror: str) -> bool:
    name = entry["name"]
    install_spec = entry.get("install") or {}
    install_type = install_spec.get("type")
    if not entry.get("default", True) and name not in _explicit():
        _write_step(job_id, {"event": "step", "component": name, "state": "skipped",
                             "error_code": None, "log_tail": "默认不安装（A-10），向导可勾选"})
        return True  # 审计修复：按设计跳过不是失败（原 return None 会把整个作业判 failed）
    _write_step(job_id, {"event": "step", "component": name, "state": "running",
                         "error_code": None, "log_tail": ""})

    def finish(state: str, error_code: str | None = None, log_tail: str = "") -> bool:
        _write_step(job_id, {"event": "step", "component": name, "state": state,
                             "error_code": error_code, "log_tail": log_tail[-4000:]})
        return state == "succeeded"

    if install_type == "npm":
        pkg = install_spec.get("package") or ""
        min_version = entry.get("min_version", "")
        spec = f"{pkg}@{min_version}" if min_version else pkg
        npm = _private_npm() or "npm"
        last_log = ""
        for registry in _npm_registry(mirror, entry):
            cmd = [npm, "install", "-g", spec, "--registry", registry,
                   "--prefix", str(runtime_dir() / "npm-global")]
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=900,
                    encoding="utf-8", errors="replace",
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                )
            except FileNotFoundError:
                return finish("failed", "NPM_INSTALL_FAILED", "npm 不存在")
            except OSError as exc:  # 审计修复：权限拒绝/杀软拦截等，按安装失败报告
                return finish("failed", "NPM_INSTALL_FAILED", f"无法启动 npm：{exc}")
            except subprocess.TimeoutExpired:
                last_log = f"npm 超时（900s）：{registry}"
                continue
            last_log = ((proc.stdout or "") + (proc.stderr or ""))[-2000:]
            if proc.returncode == 0:
                detected = detect_named(name)
                if detected and detected.installed:
                    return finish("succeeded", None, last_log)
                return finish("failed", "POST_INSTALL_NOT_ON_PATH",
                              "安装命令成功但未在 PATH/私有目录发现可执行文件；新开终端后重试")
        return finish("failed", "NPM_INSTALL_FAILED", last_log)

    if install_type == "official_script":
        # MN-02/A-10：官方脚本类安装必须用户知情；向导勾选后由用户手动执行，
        # 这里只产出引导命令，不代跑远程脚本（供应链口径，DESIGN-001 安全节）。
        url = (entry.get("urls") or {}).get("official") or ""
        return finish("skipped", None,
                      f"官方脚本安装需用户确认：请在终端运行 {url} 中的官方命令后点重试")

    return finish("failed", "VALIDATION_FAILED", f"未知安装类型: {install_type}")


_EXPLICIT: set[str] = set()


def _explicit() -> set[str]:
    return _EXPLICIT


def note_explicit(names: list[str]) -> None:
    """用户在向导中显式勾选的组件（如 grok），install 时不再按 default 跳过。"""
    _EXPLICIT.update(names)


def _private_npm() -> str | None:
    """私有 Node 的 npm；不存在返回 None（回落 PATH npm）。"""
    for suffix in (".cmd", ""):
        candidate = runtime_dir() / "node" / "npm" + suffix
        if candidate.is_file():
            return str(candidate)
    node_dir = runtime_dir() / "node"
    if (node_dir / "node.exe").is_file():
        npm_cli = node_dir / "node_modules" / "npm" / "bin" / "npm-cli.js"
        if npm_cli.is_file():
            return str(node_dir / "node.exe") + f" {npm_cli}"
    return None


# ---------------------------------------------------------------------------
# SetupStatus（契约 schemas/setup-status.json）
# ---------------------------------------------------------------------------


def status() -> dict[str, Any]:
    manifest = load_manifest()
    components: list[dict[str, Any]] = []
    harness_auth: list[dict[str, Any]] = []
    for detected in detect_all():
        state = ("installed" if detected.installed else "missing")
        if detected.installed and detected.min_version and \
                not _version_at_least(detected.version, detected.min_version):
            state = "outdated"
        components.append({
            "name": detected.name, "kind": detected.kind, "state": state,
            "version": detected.version, "min_version": detected.min_version,
            "source": detected.source, "detail": detected.detail[:500],
        })
        if detected.kind == "cli":
            authed = False
            detail = detected.detail
            if detected.installed:
                from fleet.harness import auth_check, load_profile

                try:
                    profile = load_profile(detected.name)
                    authed, auth_detail = auth_check(profile)
                    detail = auth_detail[:500] if not authed else "已登录/可用"
                except Exception as exc:
                    detail = f"profile 不可用: {exc}"[:500]
            harness_auth.append({
                "harness": detected.name, "installed": detected.installed,
                "authed": bool(authed), "detail": detail,
            })

    models: list[dict[str, Any]] = []
    try:
        from fleet.core import fleet_toml

        cfg = fleet_toml.load_config()
        for name, m in cfg.models.items():
            models.append({
                "name": name, "base_url": m.base_url, "model_id": m.model_id,
                "api_key_env": m.api_key_env, "key_present": m.key_present(),
            })
    except Exception:
        pass

    key_ok = any(m["key_present"] for m in models)
    cli_ok = any(h["installed"] and h["authed"] for h in harness_auth)
    platform = "windows" if os.name == "nt" else ("macos" if sys_platform() == "darwin" else "linux")
    return {
        "platform": platform,
        "ready": bool(key_ok and cli_ok),
        "components": components,
        "models": models,
        "harness_auth": harness_auth,
    }


def sys_platform() -> str:
    import sys

    return sys.platform
