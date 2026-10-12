"""这是什么：直连模型执行体（C2 修复：manager/reviewer 改绑直连模型 + 全链降级终点）。
怎么用：角色 adapter 填 "direct"，或作为 dispatcher 适配器链的兜底候选。
要点：
- 不驱动任何 CLI：直接走模型池 router.call（OpenAI 兼容端点），角色取线程上下文的 role；
- 输出即六节报告文本，由控制面落盘证据目录（与 CLI 执行体一致，不越界写文件）；
- 适合 manager/reviewer 这类"产出=文本报告"的角色；开发角色的产出需要落盘文件，
  直连模型无法操作工作区，因此只作最后兜底（由机器门判定其是否真正交付）。
"""

from __future__ import annotations

from .base import BaseAdapter, register_adapter
from . import registry


@register_adapter
class DirectModelAdapter(BaseAdapter):
    """直连模型池的执行体：run() = router.call(当前角色, prompt)。"""

    name = "direct"

    def run(self, prompt: str, workdir: str, model: str, timeout: int = 600):
        from ..manager.contracts import AgentResult
        from ..models import router

        role = str(registry.get_run_context().get("role") or "").strip() or "manager"
        try:
            route = router.call(role, prompt)
        except Exception as exc:  # 防御：router 理论上不抛，这里兜底转失败
            return AgentResult(ok=False, error_code="direct_model_unavailable", error_msg=str(exc))
        if route.status != router.STATUS_OK:
            codes = "/".join(sorted({str(f.get("error_code")) for f in (route.failures or []) if f.get("error_code")}))
            return AgentResult(
                ok=False,
                error_code="direct_model_unavailable" + (f":{codes}" if codes else ""),
                error_msg="；".join(str(f.get("error") or f.get("error_code")) for f in (route.failures or []))[:500],
                usage=None,
            )
        return AgentResult(
            ok=True,
            output=route.output or "",
            usage=route.usage if isinstance(route.usage, dict) else None,
        )

    def capabilities(self):
        from ..manager.contracts import Capabilities

        return Capabilities(usage_reporting=True)


Adapter = DirectModelAdapter()
