"""MockWriteAdapter — 不接真 LLM 也能走通到 DONE 的执行体（P2-C-1）

FakeAdapter 不写文件 → 机器门 verify_cmd 检查文件存在性必然失败 → 无法端到端验证。
MockWriteAdapter 解决这个问题：它从 prompt 中解析 verify_cmd 和 evidence_path，
推断目标文件并创建模板内容，使机器门检查通过。

用途：CI 端到端测试、无 API Key 环境下的流程验证。
限制：不真正"理解"需求，只创建让 verify_cmd 通过的最小文件集。
"""

import re
import time
from pathlib import Path
from typing import Callable

from .base import BaseAdapter, AgentResult, Capabilities, register_adapter


@register_adapter
class MockWriteAdapter(BaseAdapter):
    """模拟写文件的执行体适配器。

    从 prompt 中提取 verify_cmd，解析其中检查的文件路径，
    创建对应模板文件，使机器门验证通过。返回合格六节报告。
    """

    name = "mock-write"

    def __init__(self):
        self.call_count = 0
        self.last_prompt = None
        self.last_workdir = None

    def capabilities(self) -> Capabilities:
        return Capabilities(
            streaming=False,
            structured_output=False,
            resume_session=False,
            mcp=False,
            native_skills=False,
            sandbox=False,
            usage_reporting=False,
        )

    def run(
        self,
        prompt: str,
        workdir: str,
        model: str,
        timeout: int = 600,
    ) -> AgentResult:
        self.call_count += 1
        self.last_prompt = prompt
        self.last_workdir = workdir
        time.sleep(0.05)

        root = Path(workdir)
        created_files: list[str] = []

        # 1. 从 prompt 中解析 verify_cmd
        verify_cmd = _extract_field(prompt, "机器门命令：")

        if verify_cmd:
            target_files = _parse_verify_targets(verify_cmd)
            for rel_path in target_files:
                full = root / rel_path
                if not full.exists():
                    full.parent.mkdir(parents=True, exist_ok=True)
                    content = _template_for(rel_path)
                    full.write_text(content, encoding="utf-8")
                    created_files.append(rel_path)

        # 2. 从 prompt 中解析 evidence_path 并创建
        evidence_path = _extract_field(prompt, "保存到：")
        if evidence_path and evidence_path != "(见 report_path)":
            ev = Path(evidence_path)
            if not ev.is_absolute():
                ev = root / ev
            if not ev.exists():
                ev.parent.mkdir(parents=True, exist_ok=True)
                ev.write_text("# 执行报告\n\nMockWriteAdapter 生成的证据文件。\n", encoding="utf-8")
                created_files.append(str(ev.relative_to(root)) if ev.is_relative_to(root) else str(ev))

        # 3. 提取任务标题用于报告
        title = _extract_field(prompt, "标题: ") or "未知任务"

        # 4. 返回六节报告
        report = _build_report(title, created_files)

        return AgentResult(
            ok=True,
            output=report,
            error_code=None,
            error_msg="",
            usage={"prompt_tokens": 15, "completion_tokens": 30},
            duration_ms=50,
        )

    def run_stream(
        self,
        prompt: str,
        workdir: str,
        model: str,
        timeout: int = 600,
        on_chunk: Callable[[str], None] | None = None,
    ) -> AgentResult:
        """流式执行：分 2 次推送，然后创建文件并返回结果。"""
        self.call_count += 1
        self.last_prompt = prompt
        self.last_workdir = workdir

        if on_chunk:
            on_chunk("MockWrite: 分析任务要求...")
            time.sleep(0.03)
            on_chunk("MockWrite: 创建交付文件...")
            time.sleep(0.03)

        return self.run(prompt, workdir, model, timeout)


def _extract_field(prompt: str, marker: str) -> str:
    """从 prompt 文本中提取 marker 后面的值（到行尾）。"""
    idx = prompt.find(marker)
    if idx == -1:
        return ""
    start = idx + len(marker)
    end = prompt.find("\n", start)
    if end == -1:
        end = len(prompt)
    return prompt[start:end].strip()


def _parse_verify_targets(verify_cmd: str) -> list[str]:
    """从 verify_cmd 中解析被检查的文件路径。

    支持三种模式：
    - pathlib.Path('docs/design.md') → docs/design.md
    - ('index.html','src/main.ts',...) → index.html, src/main.ts, ...
    - '"{python}" -m fleet.gates.doclint docs/design.md' → docs/design.md
    - '"{python}" -m fleet.gates.project_gate' → 默认交付物对（docs/design.md + src/main.py）
    """
    targets: list[str] = []

    # 模式 1: pathlib.Path('xxx')
    for m in re.finditer(r"pathlib\.Path\(['\"]([^'\"]+)['\"]\)", verify_cmd):
        targets.append(m.group(1))

    # 模式 2: 括号内的文件列表 ('a','b','c')
    for m in re.finditer(r"for\s+p\s+in\s+\(([^)]+)\)", verify_cmd):
        for fm in re.finditer(r"['\"]([^'\"]+)['\"]", m.group(1)):
            path = fm.group(1)
            if "." in path or "/" in path:
                targets.append(path)
            else:
                targets.append(f"{path}/.gitkeep")

    # 模式 3: fleet.gates.doclint/project_gate 模块验收（A5 后的默认命令形态）
    if "fleet.gates.doclint" in verify_cmd:
        for token in verify_cmd.split():
            if "/" in token and not token.startswith("-") and "fleet.gates" not in token:
                targets.append(token.strip('"'))
        if "docs/design.md" not in targets:
            targets.append("docs/design.md")
    elif "fleet.gates.project_gate" in verify_cmd:
        targets.extend(["docs/design.md", "src/main.py"])

    # 如果没匹配到任何目标，用默认值
    if not targets:
        targets = ["docs/design.md", "src/main.py"]

    return targets


def _template_for(rel_path: str) -> str:
    """根据文件路径返回模板内容（设计文档必须通过 doclint 实质校验：≥300 有效字符、
    ≥3 个标题、覆盖 ≥3 类设计主题——A5 之后"存在即通过"不再被机器门接受）。"""
    if rel_path.endswith(".md"):
        if "design" in rel_path:
            return (
                "# 设计文档\n\n"
                "## 1. 技术选型\n"
                "语言采用 Python 3.11 标准库实现，零第三方依赖；理由是交付环境离线可运行、\n"
                "维护成本低，且当前需求不涉及高并发场景。后续如需 Web 界面再引入 FastAPI。\n\n"
                "## 2. 架构与模块划分\n"
                "采用三层结构：入口层（src/main.py 负责参数解析与调度）、\n"
                "核心引擎层（业务实体与规则，纯函数实现便于测试）、展示层（格式化输出）。\n"
                "模块之间只通过函数接口通信，禁止隐式全局状态。\n\n"
                "## 3. 目录结构\n"
                "- src/ — 全部源代码，main.py 为唯一入口\n"
                "- docs/ — 设计文档与交付说明\n"
                "- tests/ — 单元测试\n\n"
                "## 4. 数据流与依赖\n"
                "输入经入口解析后传入核心引擎处理，结果序列化后输出到标准输出；\n"
                "数据结构以 dict/dataclass 为主，无外部存储依赖。\n"
            )
        return "# 报告\n\nMockWriteAdapter 生成。\n"
    if rel_path.endswith(".py"):
        return "print('OK')\n"
    if rel_path.endswith(".ts"):
        return "console.log('OK')\n"
    if rel_path.endswith(".js"):
        return "console.log('OK')\n"
    if rel_path.endswith(".html"):
        return "<!DOCTYPE html>\n<html><body>OK</body></html>\n"
    if rel_path.endswith(".gitkeep"):
        return ""
    return f"# {rel_path}\n"


def _build_report(title: str, created_files: list[str]) -> str:
    """生成合格六节报告。"""
    files_str = "、".join(created_files) if created_files else "（无文件创建）"
    return (
        f"# 六节报告\n"
        f"## 1. 改动清单\n{files_str}\n"
        f"## 2. 命令记录\nMockWriteAdapter 自动创建模板文件\n"
        f"## 3. 证据链\n工作区文件实际存在\n"
        f"## 4. 四要素\n目标：{title}\n范围：工作区内\n交付：{files_str}\n验收：verify_cmd 通过\n"
        f"## 5. 未完成事项\n无\n"
        f"## 6. 模型自述\nMockWriteAdapter（无 LLM 调用）\n"
    )
