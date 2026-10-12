"""SMTP邮件发送"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from pathlib import Path
from typing import Optional


def load_env_config() -> dict:
    """从.env加载配置
    
    Returns:
        dict: 配置字典
    """
    config = {}
    env_file = Path(".env")
    
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                config[key.strip()] = value.strip().strip('"').strip("'")
    
    return config


def send_email(
    subject: str,
    body: str,
    receiver: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    sender: Optional[str] = None,
    password: Optional[str] = None,
    html: Optional[str] = None,
) -> tuple[bool, str]:
    """发送邮件
    
    Args:
        subject: 邮件主题
        body: 纯文本正文（始终作为 multipart/alternative 的回退版本）
        receiver: 收件人（可选，从.env读取）
        smtp_host: SMTP主机（可选，从.env读取）
        smtp_port: SMTP端口（可选，从.env读取）
        sender: 发件人（可选，从.env读取）
        password: 授权码（可选，从.env读取）
        html: HTML 正文（可选；提供时以 multipart/alternative 发送，客户端优先渲染 HTML，
              不支持 HTML 的客户端自动回退纯文本 body）
        
    Returns:
        tuple[bool, str]: (是否成功, 消息)
    """
    # 加载配置
    env_config = load_env_config()
    
    # 使用参数或环境变量
    smtp_host = smtp_host or env_config.get("SMTP_HOST", "smtp.163.com")
    smtp_port = smtp_port or int(env_config.get("SMTP_PORT", "465"))
    sender = sender or env_config.get("SMTP_SENDER", "")
    password = password or env_config.get("SMTP_PASSWORD", "")
    receiver = receiver or env_config.get("SMTP_RECEIVER", "")
    
    # 验证配置
    if not all([sender, password, receiver]):
        return False, "邮件配置不完整（需要sender/password/receiver）"
    
    try:
        # 创建邮件
        message = MIMEMultipart()
        message["From"] = sender
        message["To"] = receiver
        message["Subject"] = Header(subject, "utf-8")
        
        # 正文：multipart/alternative（纯文本在前为回退，HTML 在后供客户端优先渲染）
        if html:
            message.attach(MIMEText(body, _subtype="plain", _charset="utf-8"))
            message.attach(MIMEText(html, _subtype="html", _charset="utf-8"))
        else:
            message.attach(MIMEText(body, _subtype="plain", _charset="utf-8"))
        
        # 发送
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(sender, password)
            server.sendmail(sender, receiver, message.as_string())
        
        return True, "邮件发送成功"
        
    except smtplib.SMTPAuthenticationError:
        return False, "SMTP认证失败（授权码错误）"
    except smtplib.SMTPException as e:
        return False, f"SMTP错误: {str(e)}"
    except Exception as e:
        return False, f"发送失败: {str(e)}"


def test_email_config() -> tuple[bool, str]:
    """测试邮件配置
    
    Returns:
        tuple[bool, str]: (是否成功, 消息)
    """
    return send_email(
        subject="Fleet邮件测试",
        body="这是一封测试邮件，说明邮件配置正确。\n\n发送时间: Fleet系统测试"
    )
