# [DEPRECATED · CORE-03] 本模块已废弃：实现已迁移到 fleet/core/config.py 与 SQLite。
# 归档于此仅供历史追溯，任何代码不得 import；确认全仓零引用后移入本目录。
# -*- coding: utf-8 -*-
"""
envstore.py —— AideanFleet 控制台的 .env 配置读写模块（角色B · FLEET-FE-01）

职责：
  1. 读取/解析带 [段落] 的 .env 文件（settings/models/roles/executors/extensions/message）。
  2. 原子写回（先写临时文件，再 os.replace，避免写一半断电损坏）。
  3. 密钥掩码：api_key/password 一律以 ${VAR} 占位符形式存入 .env，
     真值只写入 secrets/.env（本模块提供写入函数，但从不读取回显真值）。

本模块不依赖任何第三方库，只用 Python 标准库。
"""

import json
import os
import re
import threading

# 工作区根目录（fleet/console/envstore.py 的上两级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ENV_PATH = os.environ.get("FLEET_ENV_PATH", os.path.join(BASE_DIR, ".env"))
SECRETS_PATH = os.environ.get(
    "FLEET_SECRETS_PATH", os.path.join(BASE_DIR, "secrets", ".env")
)

# 视为敏感的字段名（值必须掩码，永不明文回显）
SECRET_FIELDS = {"api_key", "password", "smtp_password"}

# 掩码显示占位（前端展示用，提交此值表示“未修改”）
MASK_DISPLAY = "********"

_write_lock = threading.Lock()


def _var_name(field, record_name=""):
    """敏感字段名 -> 变量名，例如 "api_key" + 记录名 "agnes3" -> AGNES3_API_KEY。"""
    base = re.sub(r"[^A-Za-z0-9]", "_", (record_name or field)).upper().strip("_")
    return base + "_" + field.upper()


def _is_placeholder(value):
    """值本身就是 ${VAR} 占位符，或为空，或为掩码显示值 —— 都视为“未提供真值”。"""
    v = (value or "").strip()
    return v == "" or v == MASK_DISPLAY or v.startswith("${")


def ensure_default_env():
    """若 .env 不存在，则按默认模板创建（模拟“初始化时从 .env.example 复制”）。"""
    if os.path.exists(ENV_PATH):
        return False
    default = """# AideanFleet 控制台配置（由控制台初始化生成，可读可写，实时读取无缓存）
# 说明：api_key 一律使用 ${VAR} 占位符；真值只允许写入 secrets/.env

[settings]
request_timeout = 30
retry_count = 10
lock_screen_seconds = 3600

[models]
agnes3 = {"level": 5, "base_url": "https://apihub.agnes-ai.com/v1", "model_id": "agnes-3.0-flash", "api_key": "${AGNES3_API_KEY}", "http_proxy": "", "https_proxy": ""}
bai1 = {"level": 1, "base_url": "https://api.b.ai/v1", "model_id": "qwen3.8-flash", "api_key": "${BAI1_API_KEY}", "http_proxy": "http://127.0.0.1:10808", "https_proxy": "http://127.0.0.1:10808"}

[roles]
产品 = {"system_prompt": "你是产品经理，负责需求分析与任务拆解。", "bind_model_name": ["agnes3", "bai1"]}
前端 = {"system_prompt": "你是前端工程师，负责页面实现。", "bind_model_name": ["agnes3"]}
审查 = {"system_prompt": "你是审查者，负责验收阶段性任务。", "bind_model_name": ["bai1"]}

[executors]
claudecode = {"launch_command": "claude --dangerously-skip-permissions"}
opencode = {"launch_command": "opencode"}

[extensions]
claudecode = {"skills": ["代码检索", "单元测试"], "mcp": ["filesystem", "git"]}

[message]
smtp_host = smtp.163.com
smtp_port = 465
sender_email = ""
smtp_password = ${SMTP_PASSWORD}
receiver_email = 164093410@qq.com
notify_task_start = off
notify_task_end = on
notify_manager_quota = on
notify_executor_quota = on
custom_triggers =

[notify]
enabled = false
"""
    os.makedirs(os.path.dirname(ENV_PATH), exist_ok=True)
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write(default)
    return True


def read_env():
    """解析 .env，返回 {section: {key: raw_str}}。"""
    result = {}
    current = "__base__"
    result[current] = {}
    if not os.path.exists(ENV_PATH):
        return result
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            s = line.strip()
            if not s or s.startswith("#") or s.startswith(";"):
                continue
            m = re.match(r"^\[(.+)\]$", s)
            if m:
                current = m.group(1).strip()
                result.setdefault(current, {})
                continue
            m = re.match(r"^([^=]+?)\s*=\s*(.*)$", s)
            if m:
                key = m.group(1).strip()
                val = m.group(2).strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                    val = val[1:-1]
                result.setdefault(current, {})[key] = val
    return result


def _dump_env(sections):
    """把 {section: {key: raw_str}} 序列化回文本。"""
    lines = []
    base = sections.get("__base__", {})
    for k, v in base.items():
        lines.append(f"{k} = {v}")
    for sec, kv in sections.items():
        if sec == "__base__":
            continue
        if lines:
            lines.append("")
        lines.append(f"[{sec}]")
        for k, v in kv.items():
            lines.append(f"{k} = {v}")
    return "\n".join(lines) + "\n"


def atomic_write_env(sections):
    """原子写 .env：临时文件 + os.replace，进程内加锁防并发写坏。"""
    with _write_lock:
        os.makedirs(os.path.dirname(ENV_PATH), exist_ok=True)
        tmp = ENV_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(_dump_env(sections))
        os.replace(tmp, ENV_PATH)


def write_secret(var_name, truth):
    """把密钥真值写入 secrets/.env（只增改这一个变量，不读回、不返回）。"""
    os.makedirs(os.path.dirname(SECRETS_PATH), exist_ok=True)
    with _write_lock:
        rows = []
        if os.path.exists(SECRETS_PATH):
            with open(SECRETS_PATH, "r", encoding="utf-8") as f:
                rows = [
                    ln.rstrip("\n")
                    for ln in f
                    if ln.strip() and not ln.startswith("#")
                ]
        entry = f"{var_name}={truth}"
        found = False
        for i, ln in enumerate(rows):
            if ln.split("=", 1)[0].strip() == var_name:
                rows[i] = entry
                found = True
                break
        if not found:
            rows.append(entry)
        tmp = SECRETS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("# AideanFleet 密钥真值（控制台只写不读；请勿提交到 git）\n")
            for ln in rows:
                f.write(ln + "\n")
        os.replace(tmp, SECRETS_PATH)


def get_section(section):
    """读取某一段；结构化段落（models/roles/executors/extensions）的 JSON 值解析为 dict。"""
    sections = read_env()
    kv = sections.get(section, {})
    if section in ("models", "roles", "executors", "extensions"):
        parsed = {}
        for k, v in kv.items():
            try:
                parsed[k] = json.loads(v)
            except (ValueError, TypeError):
                parsed[k] = {"_raw": v}
        return parsed
    return dict(kv)


def set_section(section, data):
    """
    原子写某一段。
    data: dict。结构化段落里每条记录为 dict（序列化为 JSON 行）；
          敏感字段（api_key/password）若提交了真值 -> 写入 secrets/.env，
          .env 中只落 ${VAR} 占位符。
    返回被掩码保存的字段列表（供响应提示）。
    """
    sections = read_env()
    masked = []
    out = {}
    if section in ("models", "roles", "executors", "extensions"):
        # 结构化段：整体替换（支持删除记录，卡片即完整记录）
        for name, rec in data.items():
            rec = dict(rec or {})
            for field in list(rec.keys()):
                if field in SECRET_FIELDS:
                    val = rec.get(field)
                    if isinstance(val, str) and not _is_placeholder(val):
                        var = _var_name(field, name)
                        write_secret(var, val.strip())
                        rec[field] = "${" + var + "}"
                        masked.append(f"{name}.{field}")
                    else:
                        # 空/占位/掩码提交 -> 尽量沿用旧占位符，否则留空
                        old = sections.get(section, {}).get(name, "")
                        old_field = ""
                        try:
                            old_field = json.loads(old).get(field, "") if old else ""
                        except (ValueError, TypeError):
                            old_field = ""
                        rec[field] = old_field or ""
            out[name] = json.dumps(rec, ensure_ascii=False)
    else:
        # 扁平段（settings/message 等）：合并更新，只覆盖提交的键，
        # 未提交的键（如 lock_screen_seconds）原样保留，防止整段替换丢键
        out = dict(sections.get(section, {}))
        for k, v in data.items():
            v = "" if v is None else str(v)
            if k in SECRET_FIELDS and not _is_placeholder(v):
                var = _var_name(k, section)
                write_secret(var, v)
                v = "${" + var + "}"
                masked.append(f"{section}.{k}")
            out[k] = v
    sections[section] = out
    atomic_write_env(sections)
    return masked
