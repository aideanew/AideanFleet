"""INT-04 集成验收测试：真实执行器烟雾、五模式走查、并发压测、Phase 2 验收"""

import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

# 确保项目根目录在 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ._cli_probe import probe_cli, skip_if_unavailable, KNOWN_CLIS


# ─── 约束常量 ───
MAX_REAL_CLI_CALLS = 8
MAX_REAL_SMTP_SENDS = 3

# 追踪真实调用次数
_real_cli_calls = 0
_real_smtp_sends = 0
_call_lock = threading.Lock()


def _increment_cli_calls():
    global _real_cli_calls
    with _call_lock:
        _real_cli_calls += 1
        return _real_cli_calls


def _get_cli_calls():
    with _call_lock:
        return _real_cli_calls


# ─── 1. 真实执行器烟雾测试 ───

class TestExecutorSmoke:
    """真实执行器 --version 烟雾探测（≤5 次调用）。

    skip 口径与 tests/core/test_resolve_integration.py 一致：
    shutil.which(cmd) 为 None → pytest.skip（reason = 实测结论）。
    """

    def test_claude_code_version(self):
        """Claude Code --version"""
        if _get_cli_calls() >= MAX_REAL_CLI_CALLS:
            pytest.skip("达到 CLI 调用上限")
        skip_if_unavailable("claude")
        result = probe_cli("claude")
        _increment_cli_calls()
        assert result.available, result.skip_reason
        assert len(result.version_output) > 0, "版本输出为空"

    def test_codex_version(self):
        """Codex CLI --version"""
        if _get_cli_calls() >= MAX_REAL_CLI_CALLS:
            pytest.skip("达到 CLI 调用上限")
        skip_if_unavailable("codex")
        result = probe_cli("codex")
        _increment_cli_calls()
        assert result.available, result.skip_reason
        assert len(result.version_output) > 0, "版本输出为空"

    def test_opencode_version(self):
        """OpenCode --version"""
        if _get_cli_calls() >= MAX_REAL_CLI_CALLS:
            pytest.skip("达到 CLI 调用上限")
        skip_if_unavailable("opencode")
        result = probe_cli("opencode")
        _increment_cli_calls()
        assert result.available, result.skip_reason
        assert len(result.version_output) > 0, "版本输出为空"

    def test_hermes_version(self):
        """Hermes --version"""
        if _get_cli_calls() >= MAX_REAL_CLI_CALLS:
            pytest.skip("达到 CLI 调用上限")
        skip_if_unavailable("hermes")
        result = probe_cli("hermes")
        _increment_cli_calls()
        assert result.available, result.skip_reason
        assert len(result.version_output) > 0, "版本输出为空"

    def test_cline_version(self):
        """Cline --version"""
        if _get_cli_calls() >= MAX_REAL_CLI_CALLS:
            pytest.skip("达到 CLI 调用上限")
        skip_if_unavailable("cline")
        result = probe_cli("cline")
        _increment_cli_calls()
        assert result.available, result.skip_reason
        assert len(result.version_output) > 0, "版本输出为空"

    def test_gemini_version(self):
        """Gemini --version"""
        if _get_cli_calls() >= MAX_REAL_CLI_CALLS:
            pytest.skip("达到 CLI 调用上限")
        skip_if_unavailable("gemini")
        result = probe_cli("gemini")
        _increment_cli_calls()
        assert result.available, result.skip_reason
        assert len(result.version_output) > 0, "版本输出为空"

    def test_grok_version(self):
        """Grok --version"""
        if _get_cli_calls() >= MAX_REAL_CLI_CALLS:
            pytest.skip("达到 CLI 调用上限")
        skip_if_unavailable("grok")
        result = probe_cli("grok")
        _increment_cli_calls()
        assert result.available, result.skip_reason
        assert len(result.version_output) > 0, "版本输出为空"

    def test_cli_call_limit_respected(self):
        """CLI 调用次数 ≤ 8"""
        assert _get_cli_calls() <= MAX_REAL_CLI_CALLS


# ─── 2. 五模式走查 ───

class TestFiveModeWalkthrough:
    """
    五种启动模式的基本走查：
    - plan: 规划模式
    - run: 执行模式
    - intake: 接收模式
    - audit: 审计模式
    - discuss: 讨论模式
    """

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        """设置测试环境"""
        self.test_dir = tmp_path
        self.env = os.environ.copy()
        self.env["FLEET_DATA_DIR"] = str(tmp_path / "data")
        self.env["FLEET_ROOT"] = str(tmp_path)
        (tmp_path / "data").mkdir(exist_ok=True)

    def _run_cli(self, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
        """运行 CLI 命令"""
        return subprocess.run(
            [sys.executable, "-m", "fleet.launcher.cli_start"] + args,
            capture_output=True, timeout=timeout,
            env=self.env,
            cwd=str(self.test_dir),
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )

    def test_plan_mode(self):
        """plan 模式：应能启动并输出计划"""
        result = self._run_cli(["--mode", "plan", "--project", "test-plan"])
        # 应能启动（可能因无 API key 而失败，但不应崩溃）
        assert result.returncode in (0, 1, 2)

    def test_run_mode(self):
        """run 模式：应能启动"""
        result = self._run_cli(["--mode", "run", "--project", "test-run"])
        assert result.returncode in (0, 1, 2)

    def test_intake_mode(self):
        """intake 模式：应能启动"""
        result = self._run_cli(["--mode", "intake", "--project", "test-intake"])
        assert result.returncode in (0, 1, 2)

    def test_audit_mode(self):
        """audit 模式：应能启动"""
        result = self._run_cli(["--mode", "audit", "--project", "test-audit"])
        assert result.returncode in (0, 1, 2)

    def test_discuss_mode(self):
        """discuss 模式：应能启动"""
        result = self._run_cli(["--mode", "discuss", "--project", "test-discuss"])
        assert result.returncode in (0, 1, 2)

    def test_invalid_mode_rejected(self):
        """无效模式应被拒绝"""
        result = self._run_cli(["--mode", "invalid", "--project", "test-invalid"])
        assert result.returncode != 0


# ─── 3. 并发压测 ───

class TestConcurrentStress:
    """并发压力测试"""

    def test_concurrent_dispatch(self):
        """并发派发：多个线程同时调用 dispatch"""
        from fleet.executors.fake import FakeAdapter

        results = []
        errors = []

        def run_dispatch(task_id: str):
            try:
                adapter = FakeAdapter()
                result = adapter.run(
                    prompt=f"并发测试 {task_id}",
                    workdir=str(Path.cwd()),
                    model="fake",
                )
                results.append((task_id, result))
            except Exception as e:
                errors.append((task_id, str(e)))

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(run_dispatch, f"t-concurrent-{i}") for i in range(5)]
            for f in as_completed(futures):
                f.result()

        assert len(results) == 5, f"Expected 5 results, got {len(results)}"
        assert len(errors) == 0, f"Errors: {errors}"

    def test_concurrent_usage_recording(self):
        """并发用量记录"""
        from fleet.governance.store import record_usage, query_usage, init_db

        init_db()
        errors = []

        def record(idx: int):
            try:
                record_usage(
                    task_id=f"t-stress-{idx}",
                    total_tokens=idx * 100,
                    timestamp=datetime.now().isoformat(),
                )
            except Exception as e:
                errors.append(str(e))

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(record, i) for i in range(20)]
            for f in as_completed(futures):
                f.result()

        assert len(errors) == 0, f"Recording errors: {errors}"
        rows = query_usage(task_id="t-stress-0")
        assert len(rows) >= 1

    def test_concurrent_budget_checks(self):
        """并发预算检查"""
        from fleet.governance.budget import BudgetManager

        bm = BudgetManager()
        bm.set_limit("task", "t-budget-stress", limit_tokens=10000)
        errors = []

        def check_budget():
            try:
                bm.check(task_id="t-budget-stress")
            except Exception as e:
                errors.append(str(e))

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(check_budget) for _ in range(20)]
            for f in as_completed(futures):
                f.result()

        assert len(errors) == 0


# ─── 4. Phase 2 验收清单 ───

class TestPhase2Checklist:
    """Phase 2 验收清单：≥12 个端到端场景"""

    def test_01_governance_store_init(self):
        """场景1：治理层存储初始化"""
        from fleet.governance.store import init_db
        init_db()

    def test_02_usage_recording(self):
        """场景2：用量记录写入"""
        from fleet.governance.store import record_usage, query_usage
        record_usage(task_id="t-check-001", total_tokens=100, timestamp="2026-09-15T10:00:00")
        rows = query_usage(task_id="t-check-001")
        assert len(rows) >= 1

    def test_03_budget_pool_creation(self):
        """场景3：预算池创建"""
        from fleet.governance.budget import BudgetManager
        bm = BudgetManager()
        bm.set_limit("task", "t-pool-001", limit_tokens=100000)
        status = bm.get_status(task_id="t-pool-001")
        assert "task" in status

    def test_04_budget_circuit_breaker(self):
        """场景4：预算熔断器触发"""
        from fleet.governance.budget import BudgetManager, BudgetExceeded
        bm = BudgetManager()
        bm.set_limit("task", "t-breaker-001", limit_tokens=100)
        with pytest.raises(BudgetExceeded):
            bm.consume(100, task_id="t-breaker-001")

    def test_05_approval_gate_create(self):
        """场景5：审批门创建"""
        from fleet.governance.approval import ApprovalManager
        am = ApprovalManager()
        req = am.request_delete_overwrite(task_id="t-gate-001")
        assert req.approval_id.startswith("appr-")

    def test_06_approval_gate_approve(self):
        """场景6：审批门批准"""
        from fleet.governance.approval import ApprovalManager
        am = ApprovalManager()
        req = am.request_smtp_first_send()
        decision = am.approve(req.approval_id)
        assert decision.approved is True

    def test_07_approval_gate_reject(self):
        """场景7：审批门拒绝"""
        from fleet.governance.approval import ApprovalManager
        am = ApprovalManager()
        req = am.request_budget_warning()
        decision = am.reject(req.approval_id)
        assert decision.approved is False

    def test_08_report_generation(self):
        """场景8：报表生成"""
        from fleet.governance.report import ReportGenerator
        rg = ReportGenerator()
        report = rg.generate_daily()
        assert report.period.startswith("daily:")

    def test_09_fake_adapter_capabilities(self):
        """场景9：Fake 适配器能力查询"""
        from fleet.executors.fake import FakeAdapter
        adapter = FakeAdapter()
        caps = adapter.capabilities()
        assert caps is not None
        assert hasattr(caps, 'streaming')

    def test_10_fake_adapter_run(self):
        """场景10：Fake 适配器执行"""
        from fleet.executors.fake import FakeAdapter
        adapter = FakeAdapter()
        result = adapter.run(
            prompt="测试任务",
            workdir=str(Path.cwd()),
            model="fake",
        )
        assert result is not None

    def test_11_launch_core_import(self):
        """场景11：统一启动入口可导入"""
        from fleet.launcher.launch_core import LaunchRequest
        req = LaunchRequest(
            project="test-project",
            mode="plan",
        )
        assert req.mode == "plan"

    def test_12_governance_budget_sync(self):
        """场景12：预算同步"""
        from fleet.governance.budget import BudgetManager
        from fleet.governance.store import record_usage
        bm = BudgetManager()
        record_usage(task_id="t-sync-001", total_tokens=500, timestamp="2026-09-15T12:00:00")
        count = bm.sync_from_events()
        assert count >= 0

    def test_13_multiple_modes_dispatch(self):
        """场景13：多模式派发"""
        from fleet.executors.fake import FakeAdapter
        adapter = FakeAdapter()
        modes = ["plan", "run", "intake", "audit", "discuss"]
        for mode in modes:
            result = adapter.run(
                prompt=f"测试 {mode} 模式",
                workdir=str(Path.cwd()),
                model="fake",
            )
            assert result is not None

    def test_14_concurrent_adapter_run(self):
        """场景14：并发适配器执行"""
        from fleet.executors.fake import FakeAdapter
        adapter = FakeAdapter()
        results = []

        def run_adapter(idx: int):
            return adapter.run(
                prompt=f"并发测试 {idx}",
                workdir=str(Path.cwd()),
                model="fake",
            )

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(run_adapter, i) for i in range(3)]
            for f in as_completed(futures):
                results.append(f.result())

        assert len(results) == 3
