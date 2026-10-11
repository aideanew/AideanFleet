"""fleet.setup：零基础安装/首次配置（TASK-202）。入口见 __main__.py 与 `fleet setup`。"""

from .core import (
    detect_all,
    detect_named,
    install_components,
    InstallInProgress,
    load_manifest,
    manifest_path,
    read_job,
    runtime_dir,
    status,
)

__all__ = [
    "detect_all", "detect_named", "install_components", "InstallInProgress",
    "load_manifest", "manifest_path", "read_job", "runtime_dir", "status",
]
