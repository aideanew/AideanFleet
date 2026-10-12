"""进程开关必须能关闭 .env 中启用的全局调度。"""
import os
import subprocess
import sys


def test_process_can_disable_global_scheduler():
    code = (
        "from fleet.core import config; "
        "config.env_setting=lambda key, default='': "
        "'1' if key=='FLEET_SCHEDULER' else 'auto'; "
        "from fleet.console import server; "
        "assert server._SCHEDULER_ENABLED is False"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "FLEET_SCHEDULER": "0"},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
