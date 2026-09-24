"""这是什么：机器验收门（Machine Gate）。在人工/LLM 审查**之前**强制执行，结果不可被 LLM 改判。
怎么用：from fleet.gates import verify;  res = verify.run_gate(task);  res.passed 必须为 True 才允许进审查。
四项检查：①原样执行 verify_cmd 并记录 exit_code 与原始输出（截尾 2000 字）②禁改/白名单文件扫描
         ③证据文件存在性 ④基线存在性（没有基线就无法证明"改了什么"，宁可真失败）。
口径：任何一项失败 → REWORK；门本身无法执行（workspace/基线缺失）→ BLOCKED（fatal=True）。
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fleet.core import db
from fleet.core.paths import paths

#: 输出截尾长度（工作包 §9.5-3）
OUTPUT_TAIL_LIMIT = 2000

#: 扫描时忽略的目录/后缀（版本库与构建缓存，不是交付物）
IGNORE_DIRS = frozenset(
    {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
     ".pytest_cache", ".ruff_cache", "playwright-report", "test-results", ".next", "dist",
     "coverage", ".nyc_output", "build"}
)
IGNORE_SUFFIXES = frozenset({".pyc", ".pyo", ".log", ".tmp", ".lock"})

#: Windows 保留设备名（P-008 T05 的 changed_files 捕获到 "nul"，污染门证据）
_WIN_RESERVED = frozenset({"nul", "con", "aux", "prn"})


@dataclass
class GateResult:
    """机器门结果。fatal=True 表示"门跑不起来"，调用方按 BLOCKED 处理而不是 REWORK。"""

    passed: bool
    reasons: list[str] = field(default_factory=list)
    exit_code: int | None = None
    output_tail: str = ""
    verify_cmd: str = ""
    changed_files: list[str] = field(default_factory=list)
    forbidden_touched: list[str] = field(default_factory=list)
    outside_allowed: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    fatal: bool = False
    baseline_source: str = "baseline"  # baseline / git / none
    checked_at: str = ""
    evidence_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reasons": self.reasons,
            "exit_code": self.exit_code,
            "output_tail": self.output_tail,
            "verify_cmd": self.verify_cmd,
            "changed_files": self.changed_files,
            "forbidden_touched": self.forbidden_touched,
            "outside_allowed": self.outside_allowed,
            "missing_evidence": self.missing_evidence,
            "fatal": self.fatal,
            "baseline_source": self.baseline_source,
            "checked_at": self.checked_at,
            "evidence_dir": self.evidence_dir,
        }

    def summarize(self) -> dict[str, Any]:
        """事件流/API 用的轻量摘要（不含 2000 字原文）。"""
        return {
            "passed": self.passed,
            "reasons": self.reasons,
            "exit_code": self.exit_code,
            "fatal": self.fatal,
            "changed_files": len(self.changed_files),
        }


def parse_patterns(text: str | None) -> list[str]:
    """把 allowed_files / forbidden_files 解析成模式列表（换行、逗号、分号、竖线都算分隔符）。"""
    raw = str(text or "").replace("\r", "\n")
    for separator in (",", ";", "|"):
        raw = raw.replace(separator, "\n")
    return [item.strip().lstrip("./") for item in raw.split("\n") if item.strip()]


def is_ignored(relative: str) -> bool:
    """是否属于扫描忽略项。"""
    parts = Path(relative).parts
    if any(part in IGNORE_DIRS for part in parts):
        return True
    # Windows 保留设备名（nul/con/aux 等）被 os.walk 当成普通文件扫到，必须显式排除
    if any(part.lower() in _WIN_RESERVED for part in parts):
        return True
    return Path(relative).suffix.lower() in IGNORE_SUFFIXES


def to_relative(workspace: Path, target: Path) -> str:
    """统一成 posix 风格相对路径（Windows 上也用 /，便于 fnmatch 与契约文档比对）。"""
    return target.relative_to(workspace).as_posix()


def snapshot_workspace(workspace: str | Path, max_files: int = 20000) -> dict[str, dict[str, int]]:
    """给工作区拍快照：{相对路径: {mtime_ns, size}}。派工前调用，事后据此扫"改了什么"。"""
    root = Path(workspace)
    if not root.is_dir():
        raise FileNotFoundError(f"workspace 不存在或不是目录：{root}")
    snapshot: dict[str, dict[str, int]] = {}
    for current, dirs, files in os.walk(root):
        dirs[:] = [item for item in dirs if item not in IGNORE_DIRS]
        for name in files:
            target = Path(current) / name
            try:
                relative = to_relative(root, target)
            except ValueError:
                continue
            if is_ignored(relative):
                continue
            stat = target.stat()
            snapshot[relative] = {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
            if len(snapshot) >= max_files:
                return snapshot
    return snapshot


def capture_baseline(workspace: str | Path, baseline_path: str | Path) -> Path:
    """把快照原子写到 baseline_path（派工前由 dispatcher 调用）。"""
    target = Path(baseline_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "workspace": str(Path(workspace).resolve()),
        "captured_at": db.iso_now(),
        "files": snapshot_workspace(workspace),
    }
    tmp = target.parent / f".{target.name}.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)
    return target


def load_baseline(baseline_path: str | Path | None) -> dict[str, Any] | None:
    """读基线；不存在或损坏返回 None。"""
    if not baseline_path:
        return None
    target = Path(baseline_path)
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def diff_snapshot(baseline: dict[str, dict[str, int]], current: dict[str, dict[str, int]]) -> dict[str, list[str]]:
    """比对两份快照，返回 {added, modified, removed}。"""
    added = sorted(set(current) - set(baseline))
    removed = sorted(set(baseline) - set(current))
    modified = sorted(
        path
        for path in set(current) & set(baseline)
        if baseline[path].get("size") != current[path].get("size")
        or baseline[path].get("mtime_ns") != current[path].get("mtime_ns")
    )
    return {"added": added, "modified": modified, "removed": removed}


def git_changed_files(workspace: str | Path) -> list[str] | None:
    """git 兜底：只读地列出改动文件（`git status --porcelain`）。非仓库 / 无 git 返回 None。"""
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(Path(workspace)),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    files: list[str] = []
    for line in completed.stdout.splitlines():
        path = line[3:].strip().strip('"')
        if " -> " in path:  # 重命名：取新名字
            path = path.split(" -> ", 1)[1]
        if path and not is_ignored(path):
            files.append(path)
    return sorted(set(files))


def changed_files_of(task: dict[str, Any]) -> tuple[list[str], str]:
    """得到"本任务改动了哪些文件"：优先基线快照，退化时用 git（只读），都没有则 (空, "none")。

    来源为 "none" 时调用方必须判 fatal（见 run_gate）：没有基线就无法证明"改了什么"。
    """
    workspace = str(task.get("workspace") or "").strip()
    baseline = load_baseline(task.get("baseline_path"))
    if workspace and baseline and Path(workspace).is_dir():
        current = snapshot_workspace(workspace)
        diff = diff_snapshot(baseline.get("files") or {}, current)
        merged = sorted(set(diff["added"]) | set(diff["modified"]) | set(diff["removed"]))
        return merged, "baseline"
    if workspace and Path(workspace).is_dir():
        files = git_changed_files(workspace)
        if files is not None:
            return files, "git"
    return [], "none"


def matches_any(relative: str, patterns: list[str]) -> bool:
    """相对路径是否命中任一模式（支持 `dir/**`、`*.py`、精确路径）。"""
    for pattern in patterns:
        candidate = pattern.rstrip("/")
        if relative == candidate:
            return True
        if fnmatch.fnmatch(relative, candidate):
            return True
        if candidate.endswith("/**"):
            prefix = candidate[:-3].rstrip("/")
            if relative.startswith(prefix + "/"):
                return True
        elif fnmatch.fnmatch(relative, candidate + "/*"):
            return True
    return False


def evaluate_files(changed: list[str], allowed: list[str], forbidden: list[str]) -> tuple[list[str], list[str]]:
    """扫描禁改文件与白名单越界：返回 (命中禁止清单的, 不在允许清单内的)。"""
    touched_forbidden = [path for path in changed if matches_any(path, forbidden)]
    outside_allowed = [path for path in changed if allowed and not matches_any(path, allowed)]
    return touched_forbidden, outside_allowed


#: 压扁形态判定用的已知路径段词表（2026-09-17 Test09171131 事故的 40 个压扁名全量覆盖）。
_FLATTEN_SEGMENTS = ("src", "tests", "public", "docs", ".github", ".vscode", ".husky",
                     "components", "features", "pages", "shared", "app", "layout", "providers",
                     "table", "core", "data", "hooks", "store", "types", "ui", "animations",
                     "renderers", "constants", "styles", "utils", "unit", "integration", "e2e",
                     "fixtures", "workflows", "images", "Dashboard", "Settings", "TableView",
                     "Button", "Input", "Select", "Modal", "Dropdown", "Tooltip", "Avatar",
                     "Badge", "Skeleton", "Spinner")


def flattened_path_dirs(workspace: str | Path) -> list[str]:
    """找出工作区根目录下"压扁路径"形态的目录（相对路径列表）。

    形态：单层目录名 = 多段路径去掉分隔符的拼接（srcfeaturestablestore、publicimages），
    即名字能完整分解成 ≥2 个已知路径段。压扁名与真实层级并存也是污染（实测事故两者并存），
    不以"真实层级是否存在"为条件——那会把同源污染漏掉。
    正常单层目录（src、docs、public）只分解出 1 段，不会命中。
    """
    root = Path(workspace)
    hits: list[str] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.is_symlink():
            continue
        segments = _split_flattened(entry.name)
        if segments is not None and len(segments) >= 2:
            hits.append(entry.name)
    return hits


def _split_flattened(name: str) -> list[str] | None:
    """把压扁名贪心分解回路径段；无法完全分解返回 None。

    词表即 _FLATTEN_SEGMENTS：单层目录名分解不出 ≥2 段时返回 None。
    """
    known = list(_FLATTEN_SEGMENTS)
    tokens = sorted(known, key=len, reverse=True)
    remaining, segments = name, []
    while remaining:
        for token in tokens:
            if remaining.startswith(token):
                segments.append(token)
                remaining = remaining[len(token):]
                break
        else:
            return None
    return segments


def run_command(command: str, cwd: str | Path, timeout: int | None = None) -> tuple[int | None, str]:
    """原样执行命令（shell=True），返回 (exit_code, 输出)。超时返回 (None, 带 TIMEOUT 标记的输出)。"""
    from fleet.models import retry

    limit = timeout or retry.policy().timeout_seconds
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            shell=True,
            capture_output=True,
            text=True,
            timeout=limit,
        )
    except subprocess.TimeoutExpired:
        return None, f"TIMEOUT：verify_cmd 超过 {limit}s 未结束"
    except OSError as error:
        return None, f"EXEC_ERROR：{error}"
    combined = completed.stdout or ""
    if completed.stderr:
        combined += "\n[stderr]\n" + completed.stderr
    return completed.returncode, combined


def truncate_tail(text: str, limit: int = OUTPUT_TAIL_LIMIT) -> str:
    """截尾 2000 字（保留末尾，因为错误信息通常出现在尾部）。"""
    content = str(text or "")
    if len(content) <= limit:
        return content
    return f"…（已截尾，仅保留末尾 {limit} 字）\n" + content[-limit:]


def check_evidence(task: dict[str, Any]) -> list[str]:
    """证据文件存在性检查：evidence_path 必须存在且非空（相对路径按 workspace 解析）。"""
    raw = str(task.get("evidence_path") or "").strip()
    if not raw:
        return ["evidence_path 未设置"]
    workspace = str(task.get("workspace") or "").strip()
    candidate = Path(raw)
    if not candidate.is_absolute() and workspace:
        candidate = Path(workspace) / raw
    if not candidate.exists():
        return [f"证据不存在：{raw}"]
    if candidate.is_file():
        return [] if candidate.stat().st_size > 0 else [f"证据文件为空：{raw}"]
    if candidate.is_dir():
        entries = list(candidate.rglob("*"))
        if not any(item.is_file() and item.stat().st_size > 0 for item in entries):
            return [f"证据目录为空：{raw}"]
        return []
    return [f"证据路径不可识别：{raw}"]


def run_gate(task: dict[str, Any], timeout: int | None = None) -> GateResult:
    """执行机器门。task 为 SQLite 的任务行（dict）。

    顺序固定：workspace 检查 → 改动扫描（基线/git）→ verify_cmd → 禁改扫描 → 证据存在性。
    任一失败即 passed=False；调用方必须转 REWORK（LLM 无权改判）。
    """
    result = GateResult(
        passed=True,
        verify_cmd=str(task.get("verify_cmd") or ""),
        checked_at=db.iso_now(),
    )
    workspace = str(task.get("workspace") or "").strip()

    if not workspace or not Path(workspace).is_dir():
        result.passed = False
        result.fatal = True
        result.reasons.append(f"workspace_missing:{workspace or '(空)'}")
        return _finish(task, result)

    changed, source = changed_files_of(task)
    result.changed_files = changed
    result.baseline_source = source
    if source == "none":
        result.passed = False
        result.fatal = True
        result.reasons.append("baseline_missing:无法确定改动文件（既无基线快照，也不是 git 仓库）")
        return _finish(task, result)

    forbidden = parse_patterns(task.get("forbidden_files"))
    allowed = parse_patterns(task.get("allowed_files"))
    touched_forbidden, outside_allowed = evaluate_files(changed, allowed, forbidden)
    result.forbidden_touched = touched_forbidden
    result.outside_allowed = outside_allowed

    verify_cmd = str(task.get("verify_cmd") or "").strip()
    if verify_cmd:
        exit_code, output = run_command(verify_cmd, workspace, timeout=timeout)
        result.exit_code = exit_code
        result.output_tail = truncate_tail(output)
        if exit_code != 0:
            result.passed = False
            result.reasons.append(f"verify_cmd_failed:exit_code={exit_code}")
    else:
        result.passed = False
        result.reasons.append("verify_cmd_missing:任务未声明机器门命令")

    if touched_forbidden:
        result.passed = False
        result.reasons.append("forbidden_files_touched:" + ",".join(touched_forbidden))
    if outside_allowed:
        result.passed = False
        result.reasons.append("outside_allowed_files:" + ",".join(outside_allowed))

    # 路径污染守卫：压扁形态目录 = 执行体把绝对/多级相对路径当单层目录创建（实测事故形态）。
    # 只检新增目录形态，不惩罚合法产物；结果附 reasons，任务转 REWORK 修复。
    polluted = flattened_path_dirs(workspace)
    if polluted:
        result.passed = False
        result.reasons.append("flattened_path_dirs:" + ",".join(polluted[:10]))

    missing = check_evidence(task)
    if missing:
        result.passed = False
        result.missing_evidence = missing
        result.reasons.extend(f"evidence_{item}" for item in missing)

    return _finish(task, result)


def _finish(task: dict[str, Any], result: GateResult) -> GateResult:
    """落盘证据并返回结果。落盘失败不影响判定（只记一笔原因）。"""
    try:
        if task.get("project_id") and task.get("task_id"):
            result.evidence_dir = str(write_evidence(str(task["project_id"]), str(task["task_id"]), result))
    except OSError as error:
        result.reasons.append(f"evidence_write_failed:{error}")
    return result


def write_evidence(project_id: str, task_id: str, result: GateResult, extra: dict[str, Any] | None = None) -> Path:
    """把机器门证据写到 data/projects/<pid>/evidence/<tid>/（gate.json 等三份文件）。"""
    target = paths().evidence_dir(project_id, task_id)
    target.mkdir(parents=True, exist_ok=True)
    # 先设 evidence_dir 再 to_dict()，否则序列化时该字段恒为 None（P-008 实测 bug）
    result.evidence_dir = str(target)
    payload = result.to_dict()
    if extra:
        payload["extra"] = extra
    (target / "gate.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (target / "verify_output.txt").write_text(result.output_tail or "", encoding="utf-8")
    (target / "changed_files.json").write_text(
        json.dumps(
            {"changed": result.changed_files, "source": result.baseline_source},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return target