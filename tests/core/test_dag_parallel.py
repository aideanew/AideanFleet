"""P3-A-2: intake allowed_files 并行测试

验证 P1-B-1 后，同阶段两个 allowed_files 不冲突的任务 → _ranges_conflict 返回 False。
"""
from fleet.manager import dag
from fleet.gates import verify


def test_allowed_files_no_conflict():
    """docs/** vs src/** → 无冲突（可并行）。"""
    patterns_a = verify.parse_patterns("docs/**")
    patterns_b = verify.parse_patterns("src/**")
    assert not dag._ranges_conflict(patterns_a, patterns_b), \
        "docs/** and src/** should not conflict"


def test_allowed_files_conflict():
    """src/** vs src/components/** → 有冲突（合理串行）。"""
    patterns_a = verify.parse_patterns("src/**")
    patterns_b = verify.parse_patterns("src/components/**")
    assert dag._ranges_conflict(patterns_a, patterns_b), \
        "src/** and src/components/** should conflict"


def test_empty_allowed_files_conflict():
    """空 allowed_files → ['*'] vs ['*'] → 冲突（保守串行）。"""
    patterns_a = verify.parse_patterns("") or ["*"]
    patterns_b = verify.parse_patterns("") or ["*"]
    assert dag._ranges_conflict(patterns_a, patterns_b), \
        "Two unrestricted patterns should conflict (conservative)"


def test_unrestricted_warning_not_blocking():
    """P1-B-2: 双方均 unrestricted → 不阻塞（只发警告）。"""
    unrestricted = ["*"]
    assert dag._is_unrestricted(unrestricted), "['*'] should be unrestricted"
    assert not dag._is_unrestricted(["docs/**"]), "docs/** should not be unrestricted"
