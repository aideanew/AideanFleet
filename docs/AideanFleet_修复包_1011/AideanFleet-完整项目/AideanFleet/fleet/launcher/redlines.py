"""启动器红线机制"""

import re
from pathlib import Path
from dataclasses import dataclass
import json
from datetime import datetime


# 危险命令正则清单
DENY_RE: list[str] = [
    r"rm\s+-rf\s+/",           # rm -rf /
    r"rm\s+-rf\s+\*",          # rm -rf *
    r"rm\s+-rf\s+~",           # rm -rf ~
    r"format\s+[a-zA-Z]:",     # format C:
    r"del\s+/[sS]\s+/[qQ]",   # del /s /q
    r"rmdir\s+/s\s+/q",       # rmdir /s /q
    r"rd\s+/s\s+/q",          # rd /s /q
    r"remove\s+item\s+.*-recurse",  # PowerShell Remove-Item -Recurse
    r"regedit",                # 注册表编辑器
    r"reg\s+delete",           # 注册表删除
    r"delete\s+.*database",    # 删除数据库
    r"drop\s+database",        # 删除数据库
    r"drop\s+table",           # 删除表
    r"truncate\s+table",       # 截断表
    r"delete\s+from",          # 删除数据
    r"grant\s+",               # 授权
    r"revoke\s+",              # 撤销授权
    r"create\s+user",          # 创建用户
    r"alter\s+user",           # 修改用户
    r"drop\s+user",            # 删除用户
    r"shutdown",               # 关机
    r"reboot",                 # 重启
    r"init\s+0",               # 关机
    r"init\s+6",               # 重启
]


@dataclass
class RedlineResult:
    """红线检查结果"""
    allowed: bool
    reason: str = ""
    matched_pattern: str = ""


def check_command(command: str) -> RedlineResult:
    """检查命令是否触发红线
    
    Args:
        command: 要检查的命令
        
    Returns:
        RedlineResult: 检查结果
    """
    command_lower = command.lower()
    
    for pattern in DENY_RE:
        if re.search(pattern, command_lower):
            return RedlineResult(
                allowed=False,
                reason="触发危险命令拦截",
                matched_pattern=pattern
            )
    
    return RedlineResult(allowed=True)


def log_redline_event(
    command: str, 
    result: RedlineResult, 
    audit_log: str = "data/audit/redline.jsonl"
) -> None:
    """记录红线事件
    
    Args:
        command: 命令
        result: 检查结果
        audit_log: 审计日志路径
    """
    log_path = Path(audit_log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    event = {
        "timestamp": datetime.now().isoformat(),
        "command": command,
        "allowed": result.allowed,
        "reason": result.reason,
        "matched_pattern": result.matched_pattern
    }
    
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def get_deny_re_list() -> str:
    """获取危险命令列表（用于提示词）
    
    Returns:
        str: 格式化的危险命令列表
    """
    return "\n".join([f"- `{p}`" for p in DENY_RE])


def get_launcher_prompt_template() -> str:
    """获取启动器提示词模板
    
    Returns:
        str: 提示词模板
    """
    return f"""# Fleet启动器提示词

## 角色
Fleet启动器 - 只启动/传话/监督，不开发

## 红线（不可违反）
1. 禁止写业务代码
2. 禁止 commit/push
3. 禁止删除任务/改state/audit.log
4. 派工只经Manager
5. 危险命令拦截：
{get_deny_re_list()}

## 资源占用处理
- 只允许Y/N问答确认
- 不擅自杀进程
- 用户确认后方可清理

## 执行流程
1. 版本探测
2. 端口检查
3. 服务启动
4. 健康检查
5. 项目注册
6. 打开浏览器
"""
