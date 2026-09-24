"""CLI引导启动

使用 launch_core 统一启动流程，修复原有6个缺陷。
"""

import os
import sys
from typing import Optional

from .launch_core import LaunchRequest, launch_core, _configure_stdio

#: 项目路径缺省时的默认项目名（保持旧行为）
_FALLBACK_PROJECT_NAME = "AideanFleet"


def default_project_name(project_path: str) -> str:
    """默认项目名 = 项目路径 basename；路径为空回退 AideanFleet。

    在 AideanFleet 目录启动其他项目时，项目名应与实际开发目录一致（用户验收项）。
    跨平台：同时处理 / 和 \\ 作为路径分隔符。
    """
    if not project_path or not project_path.strip():
        return _FALLBACK_PROJECT_NAME
    # 统一替换反斜杠为正斜杠，再 strip 尾部斜杠，取最后一段
    cleaned = project_path.strip().strip('"').replace("\\", "/").rstrip("/")
    name = cleaned.rsplit("/", 1)[-1] if "/" in cleaned else cleaned
    return name or _FALLBACK_PROJECT_NAME


def get_user_input(prompt: str, default: str = "") -> str:
    """获取用户输入，支持默认值"""
    user_input = input(f"{prompt} [{default}]: ").strip()
    return user_input if user_input else default


def main() -> None:
    """CLI引导启动主流程"""
    _configure_stdio()
    print("=" * 60)
    print("Fleet 启动器 - CLI引导模式")
    print("=" * 60)

    # 1. 获取项目信息
    print("\n=== 项目配置 ===")
    project_path = get_user_input("项目路径", "E:/Code/AideanFleet")
    project_name = get_user_input("项目名称", default_project_name(project_path))
    port = int(get_user_input("控制台端口", "5000"))
    mode = get_user_input("启动模式", "run")

    # 构建 LaunchRequest
    request = LaunchRequest(
        project=project_name,
        mode=mode,
        port=port,
        source="cli",
        project_path=project_path,
    )

    # 2. 执行统一流程
    result = launch_core(request)

    if not result["ok"]:
        print("\n✗ 启动失败")
        sys.exit(1)

    print("\n✓ Fleet CLI启动完成！")


if __name__ == "__main__":
    main()
