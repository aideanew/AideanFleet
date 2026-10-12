"""runtime.lease_minutes（设置页 UI 旋钮）必须真正接入内核租约（断链9 回归）。

背景：此前 5 处 Kernel 构造点（cli/main ×3、console/kernel_api、console/server）
全部不传 lease_seconds，内核恒用 DEFAULT_LEASE_SECONDS（900s），
设置页的 lease_minutes 旋钮空转。
"""

from fleet.core import fleet_toml
from fleet.kernel.kernel import DEFAULT_LEASE_SECONDS


def test_default_equals_kernel_default(fleet_env):
    """无 fleet.toml → 默认 15min = 900s，必须与内核默认一致。"""
    assert fleet_toml.lease_seconds_or_default() == DEFAULT_LEASE_SECONDS == 900


def test_configured_lease_honored(fleet_env):
    """fleet.toml lease_minutes=30 → 1800s。"""
    (fleet_env["root"] / "fleet.toml").write_text(
        "[runtime]\nlease_minutes = 30\n", encoding="utf-8"
    )
    assert fleet_toml.lease_seconds_or_default() == 1800


def test_kernel_api_wires_lease(fleet_env):
    """kernel_api._kernel() 构造的内核租约来自配置而非硬编码。"""
    from fleet.console import kernel_api

    (fleet_env["root"] / "fleet.toml").write_text(
        "[runtime]\nlease_minutes = 45\n", encoding="utf-8"
    )
    kernel = kernel_api._kernel()
    assert kernel.lease_seconds == 45 * 60
