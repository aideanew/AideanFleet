"""架构守门：import 边界测试（P5：用测试取代"契约 FROZEN"和"≤200 行"的文字约束）。

分层规则（自底向上）：
  L0 fleet.kernel           只依赖标准库（不 import 任何 fleet 模块）
  L1 fleet.planner          可依赖 fleet.kernel
  L1 fleet.harness          可依赖 fleet.executors / fleet.core.fleet_toml
  L2 fleet.runner           可依赖 kernel / harness / planner / core.fleet_toml
  未列出的包（console/manager/launcher 等旧链路）暂不受限，逐步并入。
  禁止：上述受控包直接 import fleet.console/manager/launcher/governance/runner 等。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ALLOWED: dict[str, set[str]] = {
    "fleet.kernel": set(),
    "fleet.planner": {"fleet.kernel"},
    "fleet.harness": {"fleet.executors", "fleet.core.fleet_toml"},
    "fleet.runner": {"fleet.kernel", "fleet.harness", "fleet.planner", "fleet.core.fleet_toml"},
}

#: 任何受控包都不得 import 这些上层/平级模块
NEVER_FOR_CONTROLLED = (
    "fleet.console", "fleet.manager", "fleet.launcher", "fleet.governance",
    "fleet.api", "fleet.runner", "fleet.notify", "fleet.rel",
)


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # level>0 是包内相对导入，天然合法；只看绝对导入
            if node.level == 0 and node.module:
                found.add(node.module)
    return found


def _controlled_modules() -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    for pkg in ALLOWED:
        pkg_dir = ROOT / "fleet" / pkg.removeprefix("fleet.")
        out[pkg] = list(pkg_dir.rglob("*.py"))
    return out


def _matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def test_kernel_depends_only_on_stdlib():
    for path in _controlled_modules()["fleet.kernel"]:
        for module in _imports_of(path):
            assert not module.startswith("fleet"), (
                f"kernel 不得 import 任何 fleet 模块：{path.name} -> {module}"
            )


def test_controlled_packages_import_within_boundary():
    for pkg, files in _controlled_modules().items():
        for path in files:
            for module in _imports_of(path):
                if not module.startswith("fleet"):
                    continue
                if any(_matches(module, p) for p in ALLOWED[pkg]):
                    continue
                raise AssertionError(
                    f"{pkg} 违反 import 边界：{path.relative_to(ROOT)} -> {module}"
                )


def test_lower_layers_never_import_upper_layers():
    for pkg, files in _controlled_modules().items():
        for path in files:
            for module in _imports_of(path):
                for forbidden in NEVER_FOR_CONTROLLED:
                    assert not _matches(module, forbidden), (
                        f"受控包 {pkg} 不得 import {forbidden}：{path.relative_to(ROOT)}"
                    )
