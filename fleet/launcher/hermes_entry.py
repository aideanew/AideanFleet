"""Hermes直启入口

使用 launch_core 统一启动流程，修复原有缺陷：
1. 解析器改为逐行状态机，避免空行截断
2. mode 白名单增加 plan
3. allowed_roots 从 .env 读取（通过 launch_core）
"""

import sys
from dataclasses import dataclass
from typing import Optional

from .launch_core import LaunchRequest, launch_core


@dataclass
class FleetLaunchConfig:
    """Fleet启动配置"""
    project: str
    mode: str  # run | intake | audit | discuss | plan
    tasks: str = "all"
    requirements: str = ""
    port: int = 5000
    notes: str = ""
    model: str = "auto"
    seats: str = ""


# 合法的 mode 值
VALID_MODES = {"run", "intake", "audit", "discuss", "plan"}


def parse_fleet_launch_block(text: str) -> Optional[FleetLaunchConfig]:
    """解析[fleet-launch]块（逐行状态机，支持空行）

    Args:
        text: 包含[fleet-launch]块的文本

    Returns:
        Optional[FleetLaunchConfig]: 解析成功返回配置，失败返回None
    """
    lines = text.split("\n")
    in_block = False
    config = {}

    for line in lines:
        stripped = line.strip()

        # 检测块开始
        if stripped == "[fleet-launch]":
            in_block = True
            continue

        # 检测块结束（遇到下一个 [ 开头的块）
        if in_block and stripped.startswith("[") and stripped.endswith("]"):
            break

        # 在块内，解析键值对
        if in_block and ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip().lower()
            value = value.strip()

            if key == "project":
                config["project"] = value
            elif key == "mode":
                if value in VALID_MODES:
                    config["mode"] = value
                else:
                    print(f"✗ 无效的mode: {value}")
                    print(f"  允许的值: {', '.join(sorted(VALID_MODES))}")
                    return None
            elif key == "tasks":
                config["tasks"] = value
            elif key == "requirements":
                config["requirements"] = value
            elif key == "port":
                try:
                    config["port"] = int(value)
                except ValueError:
                    print(f"✗ 无效的port: {value}")
                    return None
            elif key == "notes":
                config["notes"] = value
            elif key == "model":
                config["model"] = value
            elif key == "seats":
                config["seats"] = value

    # 检查必需字段
    if "project" not in config:
        print("✗ 缺少必需字段: project")
        return None
    if "mode" not in config:
        print("✗ 缺少必需字段: mode")
        return None

    return FleetLaunchConfig(**config)


def map_mode_to_action(mode: str) -> str:
    """映射mode到具体动作"""
    mode_map = {
        "run": "按plan全量执行",
        "intake": "先派产品角色产PRD，再转plan",
        "audit": "只读体检，产出defects清单",
        "discuss": "多执行体圆桌（≤3轮，read-only）",
        "plan": "生成执行计划",
    }
    return mode_map.get(mode, "未知模式")


def print_config(config: FleetLaunchConfig) -> None:
    """打印配置"""
    print("\n=== Fleet Launch 配置 ===")
    print(f"  项目: {config.project}")
    print(f"  模式: {config.mode} ({map_mode_to_action(config.mode)})")
    print(f"  任务: {config.tasks}")
    print(f"  端口: {config.port}")
    if config.requirements:
        req_display = config.requirements[:50] + "..." if len(config.requirements) > 50 else config.requirements
        print(f"  需求: {req_display}")
    if config.notes:
        notes_display = config.notes[:50] + "..." if len(config.notes) > 50 else config.notes
        print(f"  备注: {notes_display}")
    if config.model:
        print(f"  模型: {config.model}")
    if config.seats:
        print(f"  席位: {config.seats}")


def print_error_and_example(error_msg: str) -> None:
    """打印错误和示例"""
    print(f"\n✗ 解析失败: {error_msg}")
    print("\n=== 期望格式 ===")
    print("""
[fleet-launch]
project: 项目名或路径
mode: run|intake|audit|discuss|plan
tasks: all (可选)
requirements: 需求文档路径或描述 (可选)
port: 5000 (可选)
notes: 备注 (可选)
model: auto (可选)
seats: product=opencode,frontend=claude,backend=codex (可选，仅discuss模式)

=== 示例 ===
[fleet-launch]
project: AideanBot
mode: run
tasks: all
requirements: @E:/Code/AideanBot/.docs/PRD.md
port: 5000
notes: PRD已备好，按plan逐一完成
""")


def main() -> None:
    """Hermes直启主流程"""
    print("=" * 60)
    print("Fleet 启动器 - Hermes直启模式")
    print("=" * 60)

    # 从命令行参数或stdin读取输入
    if len(sys.argv) > 1:
        input_text = " ".join(sys.argv[1:])
    else:
        print("请粘贴[fleet-launch]块（输入完成后按Ctrl+D或输入空行）：")
        lines = []
        while True:
            try:
                line = input()
                if not line and lines:
                    break
                lines.append(line)
            except EOFError:
                break
        input_text = "\n".join(lines)

    # 解析配置
    config = parse_fleet_launch_block(input_text)

    if not config:
        print_error_and_example("无法解析[fleet-launch]块")
        sys.exit(1)

    # 打印配置
    print_config(config)

    # 构建 LaunchRequest
    request = LaunchRequest(
        project=config.project,
        mode=config.mode,
        tasks=config.tasks,
        requirements=config.requirements,
        port=config.port,
        notes=config.notes,
        model=config.model,
        seats=config.seats,
        source="hermes",
    )

    # 执行统一流程
    result = launch_core(request)

    if not result["ok"]:
        print("\n✗ 启动失败")
        sys.exit(1)

    print("\n✓ Fleet直启完成！")


if __name__ == "__main__":
    main()
