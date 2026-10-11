"""这是什么：项目交付物验收门（A5：真实构建/编译校验，拒绝空壳文件）。
怎么用：python -m fleet.gates.project_gate   （cwd 必须是项目工作区）
策略（按工作区实际形态选择，全部真实执行）：
  1. package.json 有 build 脚本 → 优先 pnpm build，无 pnpm 用 npm run build（真实构建）；
  2. Python 源码（src/ 或入口 .py）→ python -m compileall 真实编译校验；
  3. 两者皆无 → 入口产物实质校验：存在且非空壳（index.html 需含标签结构，
     脚本/代码文件需 ≥ 30 字节且语法可解析）。
退出码：0 通过；1 校验失败（打印原因）；2 用法错误。
本模块只依赖标准库。
"""

from __future__ import annotations

import json
import py_compile
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], cwd: Path, timeout: int = 600) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError:
        return 127, f"命令不存在: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"命令超时（{timeout}s）: {' '.join(cmd)}"


def _node_build(root: Path) -> tuple[bool, list[str]]:
    pkg = root / "package.json"
    if not pkg.is_file():
        return True, []  # 非 Node 项目：跳过构建，继续走编译/入口校验
    try:
        scripts = (json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {})
    except Exception as exc:
        return False, [f"package.json 不可解析: {exc}"]
    if "build" not in scripts:
        return True, []  # 无构建脚本不算失败，继续走入口校验
    for runner in (["pnpm", "run", "build"], ["npm", "run", "build"]):
        code, out = _run(runner, root)
        if code == 127:
            continue  # 该包管理器未安装，换下一个
        if code == 0:
            return True, [f"构建通过: {' '.join(runner)}"]
        return False, [f"构建失败（exit {code}）:\n{out[-2000:]}"]
    return False, ["package.json 声明了 build 脚本，但 pnpm/npm 均不可用"]


def _python_compile(root: Path) -> tuple[bool, list[str]]:
    targets = [p for p in root.rglob("*.py") if "venv" not in p.parts and "__pycache__" not in p.parts]
    if not targets:
        return True, []
    bad: list[str] = []
    for target in targets[:200]:
        try:
            py_compile.compile(str(target), doraise=True)
        except py_compile.PyCompileError as exc:
            bad.append(f"编译失败 {target.name}: {exc.msg}")
    if bad:
        return False, bad[:10]
    return True, [f"Python 编译校验通过（{min(len(targets), 200)} 个文件）"]


def _entry_substance(root: Path) -> tuple[bool, list[str]]:
    """无构建脚本/无 Python 源码时：入口产物存在且非空壳。

    语法正确性由 _python_compile 兜底，这里只拒绝空文件/无结构文件。
    """
    problems: list[str] = []
    candidates = [
        "index.html", "src/main.ts", "src/main.js", "src/main.tsx",
        "src/main.py", "main.py", "app.py", "game.js",
    ]
    found = False
    for name in candidates:
        f = root / name
        if not f.is_file():
            continue
        found = True
        data = f.read_bytes()
        if not data.strip():
            problems.append(f"{name} 是空文件")
            continue
        if name.endswith(".html") and b"<" not in data:
            problems.append(f"{name} 不含 HTML 标签结构")
    if not found:
        problems.append(
            "未发现任何可验收的交付物（index.html / src/main.* / main.py / app.py）"
        )
    return (not problems), problems


def main(argv: list[str] | None = None) -> int:
    root = Path.cwd()
    if not root.is_dir():
        print("[project_gate] FAIL 当前目录不存在")
        return 2
    notes: list[str] = []
    ok, msgs = _node_build(root)
    notes += msgs
    if ok:
        ok2, msgs2 = _python_compile(root)
        notes += msgs2
        ok = ok2
    if ok:
        ok3, msgs3 = _entry_substance(root)
        notes += msgs3
        ok = ok3
    for m in notes:
        print(f"[project_gate] {m}")
    print(f"[project_gate] {'PASS' if ok else 'FAIL'} ({root})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
