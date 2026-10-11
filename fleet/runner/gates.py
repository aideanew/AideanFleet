"""这是什么：Runner 的机器门（P1）：真实执行 verify 命令，证据落盘，拒绝"自称完成"。
与 fleet/gates/verify.py（旧链路，面向 TaskPack）并存；本模块面向 kernel todo。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TIMEOUT_S = 600


@dataclass
class GateReport:
    ok: bool
    commands: list[dict] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"  {'PASS' if c['ok'] else 'FAIL'}: {c['command']}"
                 f"（exit {c['exit_code']}）" for c in self.commands]
        for c in self.commands:
            if not c["ok"] and c.get("output"):
                lines.append(f"    输出末尾: {c['output'][-300:]}")
        return "\n".join(lines) or "  （无验收命令）"


def run_verify(commands: list[str], workspace: str, *,
               timeout_s: int = DEFAULT_TIMEOUT_S) -> GateReport:
    """逐条真实执行 verify 命令（cwd=工作区），全部通过才算门通过。"""
    report = GateReport(ok=True)
    if not commands:
        report.ok = False
        return report
    cwd = Path(workspace) if workspace else Path.cwd()
    cwd.mkdir(parents=True, exist_ok=True)
    for command in commands:
        try:
            proc = subprocess.run(
                command, shell=True, cwd=str(cwd), capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=timeout_s,
            )
            entry = {
                "command": command,
                "exit_code": proc.returncode,
                "ok": proc.returncode == 0,
                "output": ((proc.stdout or "") + (proc.stderr or ""))[-4000:],
            }
        except subprocess.TimeoutExpired:
            entry = {"command": command, "exit_code": 124, "ok": False,
                     "output": f"超时（{timeout_s}s）"}
        except Exception as exc:  # shell 缺失等极端情况
            entry = {"command": command, "exit_code": 127, "ok": False, "output": str(exc)}
        report.commands.append(entry)
        if not entry["ok"]:
            report.ok = False
    return report


def save_evidence(evidence_dir: str | Path, report: GateReport, harness_output: str) -> Path:
    """机器门证据落盘：gate.json + harness_output.txt（A5：验证后写回才有证据）。"""
    directory = Path(evidence_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "gate.json").write_text(
        json.dumps({"ok": report.ok, "commands": report.commands},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    output_path = directory / "harness_output.txt"
    output_path.write_text(harness_output or "", encoding="utf-8")
    return directory
