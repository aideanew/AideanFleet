"""Hermes直启解析测试（pytest 形式：return → assert，消除 PytestReturnNotNoneWarning）"""

from fleet.launcher.hermes_entry import parse_fleet_launch_block


def test_parse_basic():
    text = """[fleet-launch]
project: AideanBot
mode: run
tasks: all
requirements: @E:/Code/AideanBot/.docs/PRD.md
port: 3333
notes: PRD已备好"""

    config = parse_fleet_launch_block(text)
    assert config is not None, "解析失败：返回 None"
    assert config.project == "AideanBot"
    assert config.mode == "run"
    assert config.tasks == "all"
    assert config.requirements == "@E:/Code/AideanBot/.docs/PRD.md"
    assert config.port == 3333
    assert config.notes == "PRD已备好"


def test_parse_all_modes():
    for mode in ("run", "intake", "audit", "discuss"):
        text = f"""[fleet-launch]
project: TestProject
mode: {mode}"""
        config = parse_fleet_launch_block(text)
        assert config is not None, f"模式 {mode} 解析失败"
        assert config.mode == mode, f"模式 {mode} 解析结果错误：{config.mode}"


def test_parse_minimal():
    text = """[fleet-launch]
project: MinimalProject
mode: audit"""

    config = parse_fleet_launch_block(text)
    assert config is not None, "最小配置解析失败"
    assert config.project == "MinimalProject"
    assert config.mode == "audit"
    assert config.tasks == "all", "默认 tasks 应为 all"
    assert config.port == 5000, "默认 port 应为 5000（FleetLaunchConfig.port 默认值）"
    assert config.model == "auto", "默认 model 应为 auto"


def test_parse_invalid_mode():
    text = """[fleet-launch]
project: TestProject
mode: invalid_mode"""
    assert parse_fleet_launch_block(text) is None, "无效模式未被拒绝"


def test_parse_missing_project():
    text = """[fleet-launch]
mode: run"""
    assert parse_fleet_launch_block(text) is None, "缺少 project 未被拒绝"


def test_parse_missing_mode():
    text = """[fleet-launch]
project: TestProject"""
    assert parse_fleet_launch_block(text) is None, "缺少 mode 未被拒绝"


def test_parse_discuss_with_seats():
    text = """[fleet-launch]
project: DiscussProject
mode: discuss
seats: product=opencode/modelscope/ZhipuAI/GLM-5.2,frontend=claude,backend=codex
notes: 回合制开会"""

    config = parse_fleet_launch_block(text)
    assert config is not None, "discuss 模式解析失败"
    assert config.project == "DiscussProject"
    assert config.mode == "discuss"
    assert config.seats == "product=opencode/modelscope/ZhipuAI/GLM-5.2,frontend=claude,backend=codex"
    assert config.notes == "回合制开会"
