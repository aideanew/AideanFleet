"""这是什么：模型调用失败的重试口径（本项目标准，硬编码 + 可被 .env 覆盖数值）。
怎么用：from fleet.models import retry;  p = retry.policy();  retry.classify("429") -> "TRANSIENT"
口径（工作包 §9.4-2，与 docs/启动Hermes派工3(中文版).txt T7 一致）：
  · 429 / 超时 / 5xx：等 10 秒重试，最多 10 次；10 次仍败 → 切换下一候选模型；
  · 401/402/403/quota_exhausted/model_not_found：硬失败，立即切换，不空耗 10 次；
  · 全部候选耗尽 → 返回 BLOCKED（由 router 附加每家失败原因）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable

#: 硬失败信号：出现即立刻换模型
HARD_SIGNALS: tuple[str, ...] = ("401", "402", "403", "quota_exhausted", "model_not_found")

#: 软失败信号：先重试，重试耗尽才换模型
TRANSIENT_SIGNALS: tuple[str, ...] = ("429", "timeout", "timed_out", "read_timeout", "network", "connection_reset")

_SERVER_ERROR_RE = re.compile(r"\b5\d\d\b")
_RATE_LIMIT_RE = re.compile(r"\b429\b")

TRANSIENT = "TRANSIENT"
HARD = "HARD"
UNKNOWN = "UNKNOWN"

#: 给"未知错误"的默认策略：按软失败处理（重试后再切）。口径见文件头。
_UNKNOWN_IS_TRANSIENT = True


@dataclass
class RetryPolicy:
    """重试参数。默认值即项目标准口径；数值可由 .env 的 request 段覆盖。"""

    max_attempts: int = 10
    delay_seconds: float = 10.0
    timeout_seconds: int = 600
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)

    def attempts_for(self, kind: str) -> int:
        """该类错误最多尝试几次：硬失败 1 次（立即切换），软失败 max_attempts 次。"""
        return 1 if kind == HARD else max(1, int(self.max_attempts))

    def should_retry(self, kind: str, attempts_done: int) -> bool:
        """已试 attempts_done 次后，是否还要再试一次。"""
        return attempts_done < self.attempts_for(kind)

    def wait(self) -> None:
        """重试前的等待（测试里注入 sleep 为假函数，即可零耗时验证 10 次）。"""
        self.sleep(self.delay_seconds)


def policy(
    max_attempts: int | None = None,
    delay_seconds: float | None = None,
    timeout_seconds: int | None = None,
    sleep: Callable[[float], None] | None = None,
) -> RetryPolicy:
    """取策略：显式参数 > .env request 段 > 项目标准默认（10 次 / 10 秒）。"""
    from fleet.core import config

    base = RetryPolicy()
    try:
        section = config.load("request")
    except Exception:  # 配置不可读时退回硬编码默认，不能因此让引擎停摆
        section = {}
    result = RetryPolicy(
        max_attempts=int(max_attempts if max_attempts is not None else section.get("retry_max", base.max_attempts)),
        delay_seconds=float(
            delay_seconds if delay_seconds is not None else section.get("retry_delay", base.delay_seconds)
        ),
        timeout_seconds=int(
            timeout_seconds if timeout_seconds is not None else section.get("timeout", base.timeout_seconds)
        ),
        sleep=sleep or time.sleep,
    )
    return result


def classify(error_code: str | int | None, detail: str = "") -> str:
    """把一次失败的信号分成 TRANSIENT / HARD。

    优先看结构化 error_code，其次在 detail 文本里找 429 / 5xx / 超时字样。
    未知错误按 `_UNKNOWN_IS_TRANSIENT` 处理（默认软失败）。
    """
    code = "" if error_code is None else str(error_code).strip().lower()
    text = f"{code} {detail}".lower()

    if code in HARD_SIGNALS or any(signal in code for signal in HARD_SIGNALS):
        return HARD
    if any(signal in text for signal in ("quota_exhausted", "model_not_found")):
        return HARD
    if _SERVER_ERROR_RE.search(code):
        return TRANSIENT
    if code in TRANSIENT_SIGNALS or _RATE_LIMIT_RE.search(code):
        return TRANSIENT
    if _RATE_LIMIT_RE.search(text) or _SERVER_ERROR_RE.search(text):
        return TRANSIENT
    if any(signal in text for signal in ("timeout", "timed out", "超时")):
        return TRANSIENT
    return TRANSIENT if _UNKNOWN_IS_TRANSIENT else UNKNOWN


def is_hard(error_code: str | int | None, detail: str = "") -> bool:
    """是否属于"立即换模型、不重试"的硬失败。"""
    return classify(error_code, detail) == HARD


def quota_exhausted(error_code: str | int | None, detail: str = "") -> bool:
    """是否属于额度不足（用于决定是否触发"额度不足提醒"开关）。"""
    text = f"{error_code or ''} {detail}".lower()
    return "402" in text or "quota" in text or "额度" in text or "insufficient" in text