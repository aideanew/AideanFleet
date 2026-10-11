"""守门：全量测试运行不得改写任何已跟踪文件（REQ-NF-07，F-11 已由 TASK-007 修复）。

快照在 tests/conftest.py 收集阶段取（任何测试运行前），本测试执行时比对：
- 已跟踪文件的修改/删除（porcelain 首列为 M/D/R 等）→ 失败；
- 未跟踪新文件（?? 开头）不计入（test_notify 等已改为 tmp_path，不再产生）。
"""

from __future__ import annotations

from tests.conftest import PORCELAIN_AT_START, git_porcelain


def _tracked_mutations(porcelain: str) -> list[str]:
    lines = []
    for line in porcelain.splitlines():
        if not line.strip():
            continue
        status = line[:2]
        if status.strip() in ("", "?"):
            continue  # 未跟踪不算改写
        lines.append(line)
    return lines


def test_tests_do_not_mutate_tracked_files():
    assert PORCELAIN_AT_START is not None, "git 不可用，无法守门（CI 必有 git）"
    after = git_porcelain()
    assert after is not None, "测试运行后 git status 不可用"
    before_mutations = _tracked_mutations(PORCELAIN_AT_START)
    after_mutations = _tracked_mutations(after)
    new_mutations = [line for line in after_mutations if line not in before_mutations]
    assert not new_mutations, f"测试改写了已跟踪文件: {new_mutations}"
