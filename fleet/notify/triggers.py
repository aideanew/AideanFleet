"""事件触发器"""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional
from datetime import datetime
import json
import time
from pathlib import Path

from .smtp import send_email


class EventType(str, Enum):
    """事件类型"""
    TASK_STARTED = "task_started"              # 任务开始（默认关）
    TASK_COMPLETED = "task_completed"          # 任务结束（默认开）
    MANAGER_QUOTA_LOW = "manager_quota_low"    # Manager额度不足（默认开）
    WORKER_QUOTA_LOW = "worker_quota_low"      # 执行角色额度不足（默认开）
    TASK_ESCALATED = "task_escalated"          # 任务ESCALATED（默认开）
    DAILY_SUMMARY = "daily_summary"            # 每日20:00汇总（默认关）
    TASK_FAILED = "task_failed"                # 任务失败（默认开）


@dataclass
class NotificationConfig:
    """通知配置"""
    enabled: bool
    default_enabled: bool


# 默认开关配置
DEFAULT_CONFIG: dict[EventType, NotificationConfig] = {
    EventType.TASK_STARTED: NotificationConfig(enabled=False, default_enabled=False),
    EventType.TASK_COMPLETED: NotificationConfig(enabled=True, default_enabled=True),
    EventType.MANAGER_QUOTA_LOW: NotificationConfig(enabled=True, default_enabled=True),
    EventType.WORKER_QUOTA_LOW: NotificationConfig(enabled=True, default_enabled=True),
    EventType.TASK_ESCALATED: NotificationConfig(enabled=True, default_enabled=True),
    EventType.DAILY_SUMMARY: NotificationConfig(enabled=False, default_enabled=False),
    EventType.TASK_FAILED: NotificationConfig(enabled=True, default_enabled=True),
}


class NotificationTrigger:
    """通知触发器"""
    
    def __init__(self, config_file: str = "config/notifications.json"):
        """初始化通知触发器
        
        Args:
            config_file: 配置文件路径
        """
        self.config_file = Path(config_file)
        self.config = self._load_config()
        self.send_callback: Optional[Callable] = send_email
        self.max_retries = 3
    
    def _load_config(self) -> dict[EventType, NotificationConfig]:
        """加载配置
        
        Returns:
            dict: 配置字典
        """
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    # 合并默认配置
                    config = DEFAULT_CONFIG.copy()
                    for event_type_str, settings in saved.items():
                        try:
                            event_type = EventType(event_type_str)
                            config[event_type] = NotificationConfig(**settings)
                        except (ValueError, KeyError):
                            continue
                    return config
            except Exception:
                pass
        return DEFAULT_CONFIG.copy()
    
    def _save_config(self) -> None:
        """保存配置"""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            event_type.value: {
                "enabled": config.enabled,
                "default_enabled": config.default_enabled
            }
            for event_type, config in self.config.items()
        }
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def set_enabled(self, event_type: EventType, enabled: bool) -> None:
        """设置事件开关
        
        Args:
            event_type: 事件类型
            enabled: 是否启用
        """
        if event_type in self.config:
            self.config[event_type].enabled = enabled
            self._save_config()
    
    def is_enabled(self, event_type: EventType) -> bool:
        """检查事件是否启用
        
        Args:
            event_type: 事件类型
            
        Returns:
            bool: 是否启用
        """
        return self.config.get(
            event_type, 
            NotificationConfig(enabled=False, default_enabled=False)
        ).enabled
    
    def register_sender(self, callback: Callable) -> None:
        """注册发送回调
        
        Args:
            callback: 发送回调函数
        """
        self.send_callback = callback
    
    def trigger(self, event_type: EventType, subject: str, body: str,
                html: Optional[str] = None) -> tuple[bool, str]:
        """触发通知
        
        Args:
            event_type: 事件类型
            subject: 邮件主题
            body: 纯文本正文（回退版本）
            html: HTML 正文（可选，移动端友好模板；回调不支持时自动降级纯文本）
            
        Returns:
            tuple[bool, str]: (是否发送成功, 消息)
        """
        # 检查是否启用
        if not self.is_enabled(event_type):
            return False, f"事件 {event_type.value} 未启用"
        
        # 检查回调
        if not self.send_callback:
            return False, "未注册发送回调"
        
        # 尝试发送（带重试）
        last_error = ""
        for attempt in range(self.max_retries):
            try:
                success, message = self._invoke_callback(subject, body, html)
                
                if success:
                    self._log_event(event_type, "sent", subject)
                    return True, message
                
                last_error = message
            except Exception as e:
                last_error = str(e)
        
        # 超过重试次数
        self._log_event(event_type, "failed", subject)
        return False, f"发送失败（重试{self.max_retries}次后）: {last_error}"
    
    def _invoke_callback(self, subject: str, body: str, html: Optional[str] = None) -> tuple[bool, str]:
        """调用发送回调；仅当提供 html 且回调签名支持第三参时才传（外部旧回调双参兼容）。"""
        if html:
            try:
                import inspect

                takes_html = "html" in inspect.signature(self.send_callback).parameters
            except (TypeError, ValueError):
                takes_html = False
            if takes_html:
                return self.send_callback(subject, body, html)
        return self.send_callback(subject, body)

    def _log_event(self, event_type: EventType, status: str, subject: str) -> None:
        """记录事件
        
        Args:
            event_type: 事件类型
            status: 状态
            subject: 主题
        """
        log_file = Path("data/events/notifications.jsonl")
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type.value,
            "status": status,
            "subject": subject
        }
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


# 全局触发器实例
_trigger: Optional[NotificationTrigger] = None


def get_trigger() -> NotificationTrigger:
    """获取全局触发器实例
    
    Returns:
        NotificationTrigger: 触发器实例
    """
    global _trigger
    if _trigger is None:
        _trigger = NotificationTrigger()
    return _trigger


def notify_task_completed(subject: str, body: str) -> tuple[bool, str]:
    """通知任务完成
    
    Args:
        subject: 主题
        body: 正文
        
    Returns:
        tuple[bool, str]: (是否成功, 消息)
    """
    return get_trigger().trigger(EventType.TASK_COMPLETED, subject, body)


def notify_manager_quota_low(subject: str, body: str) -> tuple[bool, str]:
    """通知Manager额度不足
    
    Args:
        subject: 主题
        body: 正文
        
    Returns:
        tuple[bool, str]: (是否成功, 消息)
    """
    return get_trigger().trigger(EventType.MANAGER_QUOTA_LOW, subject, body)


def notify_worker_quota_low(subject: str, body: str) -> tuple[bool, str]:
    """通知执行角色额度不足
    
    Args:
        subject: 主题
        body: 正文
        
    Returns:
        tuple[bool, str]: (是否成功, 消息)
    """
    return get_trigger().trigger(EventType.WORKER_QUOTA_LOW, subject, body)


def notify_task_escalated(subject: str, body: str) -> tuple[bool, str]:
    """通知任务ESCALATED
    
    Args:
        subject: 主题
        body: 正文
        
    Returns:
        tuple[bool, str]: (是否成功, 消息)
    """
    return get_trigger().trigger(EventType.TASK_ESCALATED, subject, body)


def notify_task_failed(subject: str, body: str) -> tuple[bool, str]:
    """通知任务失败
    
    Args:
        subject: 主题
        body: 正文
        
    Returns:
        tuple[bool, str]: (是否成功, 消息)
    """
    return get_trigger().trigger(EventType.TASK_FAILED, subject, body)


#: 真实事件流 action（core/events 契约）→ 通知事件类型
ACTION_TO_EVENT = {
    "task:started": EventType.TASK_STARTED,
    "task:done": EventType.TASK_COMPLETED,
    "model:quota_exhausted": EventType.MANAGER_QUOTA_LOW,
    "model:role_quota": EventType.WORKER_QUOTA_LOW,
    "task:escalated": EventType.TASK_ESCALATED,
    "task:failed": EventType.TASK_FAILED,
}

EVENT_LABELS = {
    EventType.TASK_STARTED: "任务已开始",
    EventType.TASK_COMPLETED: "任务已完成",
    EventType.MANAGER_QUOTA_LOW: "Manager 模型额度不足",
    EventType.WORKER_QUOTA_LOW: "执行角色模型额度不足",
    EventType.TASK_ESCALATED: "任务升级需人工干预",
    EventType.TASK_FAILED: "任务失败",
}


def watch_events_loop(project_id: str, trigger_svc: NotificationTrigger) -> None:
    """监控事件流并触发通知
    
    轮询 events.jsonl 文件，处理事件并发送通知。
    每秒轮询一次，确保幂等性。
    
    Args:
        project_id: 项目ID
        trigger_svc: 通知触发器服务实例
    """
    import json
    import os
    import time
    from pathlib import Path

    # 加载 secrets/.env 真值到环境变量（${VAR} 解析数据源；幂等 setdefault，不覆盖已有）
    _secrets = Path("secrets/.env")
    if _secrets.exists():
        for _line in _secrets.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

    # 对齐 core/events.py 权威全局流（data/events.jsonl），不再按项目分目录
    from fleet.core.events import events_file as _core_events_file
    events_file = _core_events_file()
    last_seq_file = Path(f"data/notify/{project_id}.last_seq")
    last_seq_file.parent.mkdir(parents=True, exist_ok=True)

    # 注册 SMTP 发送回调（仅覆盖预绑的 send_email：
    #   预绑回调走 smtp.load_env_config 的平铺键 SMTP_*，与 .env 契约键 FLEET_SMTP_* 不一致，
    #   必须经 core/config 解析 ${VAR} 后显式传参；外部已注册回调（测试/自定义）保留）
    from fleet.notify.smtp import send_email
    from fleet.core import config as _fleet_config
    if trigger_svc.send_callback is send_email:
        email_cfg = _fleet_config.load("email") or {}
        _sender = email_cfg.get("sender", "")
        _auth = email_cfg.get("auth_code", "")
        if _auth.startswith("${") and _auth.endswith("}"):
            # ${VAR} 显式解析（secrets/.env 真值已在上方注入 os.environ）
            _auth = os.environ.get(_auth[2:-1], "")
        _receiver = email_cfg.get("receiver", "")
        _host = email_cfg.get("host", "smtp.163.com")
        try:
            _port = int(email_cfg.get("port", "465") or 465)
        except (TypeError, ValueError):
            _port = 465
        if _sender and _auth and _receiver:
            trigger_svc.send_callback = lambda s, b: send_email(
                s, b, receiver=_receiver, smtp_host=_host, smtp_port=_port,
                sender=_sender, password=_auth,
            )
            print(f"[watch_events_loop] SMTP 回调已注册（{_host}:{_port}）")
        else:
            print("[watch_events_loop] SMTP 配置不完整（sender/auth_code/receiver 有空值），通知保持静默")
    
    # 加载上次处理的序列号（首次运行从当前尾部起，只处理新事件）
    last_seq = 0
    if last_seq_file.exists():
        try:
            last_seq = int(last_seq_file.read_text(encoding="utf-8").strip())
        except (ValueError, TypeError):
            last_seq = 0
    elif events_file.exists():
        with open(events_file, "r", encoding="utf-8") as _f:
            last_seq = sum(1 for _ in _f)
    
    print(f"[watch_events_loop] 开始监控项目 {project_id} 的事件流")
    print(f"[watch_events_loop] 上次处理序列号: {last_seq}")
    
    while True:
        try:
            # 检查事件文件是否存在
            if not events_file.exists():
                time.sleep(1)
                continue
            
            # 读取事件
            with open(events_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            # 处理新事件
            processed_any = False
            for i, line in enumerate(lines):
                seq = i + 1
                if seq <= last_seq:
                    continue  # 跳过已处理的事件
                
                try:
                    event = json.loads(line.strip())
                    # 项目过滤（根修重复刷屏）：事件流是全局单文件，本线程只发送归属本项目的
                    # 通知类事件；否则 N 个项目的 watch 线程会把同一事件各发一次（N 倍重复），
                    # 且各项目 last_seq 落后时重启还会成段重放历史。
                    if str(event.get("project") or "") != project_id:
                        last_seq = seq
                        continue
                    action = str(event.get("action") or "")
                    et = ACTION_TO_EVENT.get(action)
                    if et is None:
                        # 非通知类事件：推进 seq，静默跳过
                        last_seq = seq
                        continue
                    task_id = str(event.get("taskId") or event.get("task_id") or "")
                    label = EVENT_LABELS.get(et, et.value)
                    # 进度 + ETA + 移动端 HTML 模板（notify 模块异常时降级纯文本，不阻塞事件处理）
                    html: Optional[str] = None
                    try:
                        from fleet.notify import progress as _progress, templates as _templates

                        prog = _progress.compute_project_progress(project_id)
                        html, plain = _templates.render_status_email(
                            project=project_id,
                            event_label=label,
                            task_id=task_id,
                            summary=str(event.get("summary") or ""),
                            occurred_at=str(event.get("timestamp") or ""),
                            progress=prog,
                            tasks=prog.get("tasks") or [],
                        )
                        subject = f"[AideanFleet][{project_id}] {label} · 进度 {prog['percent']}%"
                        body = plain
                    except Exception as _exc:  # 模板/进度计算失败不阻塞通知本身
                        print(f"[watch_events_loop] HTML 模板渲染失败，降级纯文本: {_exc}")
                        subject = f"[AideanFleet][{project_id}] {label}"
                    if html is None:
                        subject = f"[AideanFleet][{project_id}] {label}"
                        body = (
                            f"事件：{action}\n"
                            f"任务ID：{task_id or 'N/A'}\n"
                            f"摘要：{event.get('summary', '')}\n"
                            f"时间：{event.get('timestamp', '')}"
                        )
                    # 触发通知
                    success, message = trigger_svc.trigger(et, subject, body)
                    print(f"[watch_events_loop] 事件 {seq}: {action} - {'成功' if success else '失败'}: {message}")
                    processed_any = True
                    
                    # 更新序列号
                    last_seq = seq
                    
                except json.JSONDecodeError as e:
                    print(f"[watch_events_loop] 事件 {seq}: JSON解析错误: {e}")
                    last_seq = seq  # 跳过格式错误的事件
                except Exception as e:
                    print(f"[watch_events_loop] 事件 {seq}: 处理错误: {e}")
                    last_seq = seq
            
            # 保存序列号（每轮写一次，避免重启后重扫跳过段）
            last_seq_file.write_text(str(last_seq), encoding="utf-8")
            
            # 等待1秒
            time.sleep(1)
            
        except KeyboardInterrupt:
            print(f"[watch_events_loop] 收到中断信号，停止监控")
            break
        except Exception as e:
            print(f"[watch_events_loop] 主循环错误: {e}")
            time.sleep(1)  # 出错后等待1秒再重试
