"""这是什么：邮件 HTML 模板（移动端优先）。遵循 Cerberus 响应式邮件模式（github.com/TedGoas/Cerberus，
5.1k stars，Outlook/Gmail/iOS Mail 实测兼容的成功案例）：
  · 外层 100% 流式 + 内层 max-width:600px，小屏自动收缩；
  · 全内联 CSS（Gmail/Outlook 会剥离 <style>），<style> 仅做渐进增强的媒体查询；
  · 表格布局（Outlook Word 渲染引擎只认 table）；
  · <meta name="color-scheme" content="light"> 锁定浅色，避免手机深色模式反色毁版式；
  · 隐藏 preheader（邮件列表摘要行）。
怎么用：from fleet.notify import templates
        html, plain = templates.render_status_email(project="P-001", event_label="任务已完成",
                                                    task_id="T01", summary="...", occurred_at="...",
                                                    progress=progress.compute_project_progress("P-001"))
注意：模板无任何外部图片/字体/远程 CSS，零依赖、离线可渲染；emoji 仅用系统自带字符。
"""

from __future__ import annotations

from html import escape
from typing import Any

#: 状态 -> (展示名, 徽标前景色, 徽标背景色)
_STATUS_STYLE: dict[str, tuple[str, str, str]] = {
    "DONE": ("完成", "#065f46", "#d1fae5"),
    "PARTIAL": ("部分完成", "#92400e", "#fef3c7"),
    "ESCALATED": ("需人工", "#991b1b", "#fee2e2"),
    "BLOCKED": ("阻塞", "#991b1b", "#fee2e2"),
    "REWORK": ("返工中", "#92400e", "#fef3c7"),
    "DOING": ("执行中", "#1e40af", "#dbeafe"),
    "SUBMITTED": ("待审查", "#1e40af", "#dbeafe"),
    "REVIEWING": ("审查中", "#1e40af", "#dbeafe"),
    "ASSIGNED": ("待派工", "#374151", "#e5e7eb"),
    "DRAFT": ("草稿", "#374151", "#e5e7eb"),
}

#: 任务清单最多展示行数（移动端一屏友好）
_MAX_TASK_ROWS = 8

_BRAND = "#4f46e5"
_BRAND_DARK = "#3730a3"


def _chip(status: str) -> str:
    label, fg, bg = _STATUS_STYLE.get(status, (status or "未知", "#374151", "#e5e7eb"))
    return (
        f'<span style="display:inline-block;padding:3px 10px;border-radius:999px;'
        f'font-size:12px;line-height:16px;color:{fg};background:{bg};'
        f'font-weight:600;white-space:nowrap;">{escape(label)}</span>'
    )


def _progress_bar(percent: int) -> str:
    """纯表格实现的进度条（Outlook 兼容；0% 时给 2% 最小可见宽度）。"""
    pct = max(0, min(100, int(percent)))
    inner_w = pct if pct > 0 else 2
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="background:#e9ecf3;border-radius:999px;">'
        "<tr><td style=\"height:14px;border-radius:999px;font-size:0;line-height:0;\">"
        f'<table role="presentation" width="{inner_w}%" cellpadding="0" cellspacing="0" border="0">'
        "<tr><td"
        f' height="14" bgcolor="{_BRAND}"'
        ' style="border-radius:999px;font-size:0;line-height:0;">&nbsp;</td></tr>'
        "</table></td></tr></table>"
    )


def _task_rows(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return ""
    shown = tasks[:_MAX_TASK_ROWS]
    rows: list[str] = []
    for t in shown:
        status = str(t.get("exec_status") or "")
        title = str(t.get("title") or t.get("task_id") or "")
        title = (title[:30] + "…") if len(title) > 30 else title
        rows.append(
            "<tr>"
            '<td style="padding:9px 16px;border-bottom:1px solid #f0f2f7;font-size:13px;'
            f'color:#1f2937;line-height:20px;">{escape(title)}'
            f'<span style="color:#9aa3b2;font-size:11px;">&nbsp;{escape(str(t.get("task_id") or ""))}</span></td>'
            '<td align="right" style="padding:9px 16px;border-bottom:1px solid #f0f2f7;'
            f'white-space:nowrap;">{_chip(status)}</td>'
            "</tr>"
        )
    more = len(tasks) - len(shown)
    if more > 0:
        rows.append(
            '<tr><td colspan="2" style="padding:8px 16px;font-size:12px;color:#9aa3b2;">'
            f"…另有 {more} 个任务未列出</td></tr>"
        )
    return "".join(rows)


def render_status_email(
    *,
    project: str,
    event_label: str,
    task_id: str = "",
    summary: str = "",
    occurred_at: str = "",
    progress: dict[str, Any] | None = None,
    tasks: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """渲染（HTML, 纯文本）双版本邮件正文。progress 传 None 时仅展示事件信息。"""
    p = progress or {}
    percent = int(p.get("percent") or 0)
    eta_text = str(p.get("eta_text") or "")
    eta_basis = str(p.get("eta_basis") or "")
    task_list = tasks or []
    summary = str(summary or "")
    occurred_at = str(occurred_at or "")
    task_line = f" · {task_id}" if task_id else ""

    # ---- 纯文本版本（不支持 HTML 的客户端回退）----
    lines = [
        f"【AideanFleet】{event_label}{task_line}",
        f"项目：{project}",
    ]
    if progress:
        lines.append(f"当前进度：{percent}%（{p.get('done')}/{p.get('total')} 个任务已完成）")
        lines.append(f"预计完成：{eta_text}")
        if eta_basis:
            lines.append(f"预估依据：{eta_basis}")
    if summary:
        lines.append(f"摘要：{summary}")
    if occurred_at:
        lines.append(f"时间：{occurred_at}")
    plain = "\n".join(lines)

    # ---- HTML 版本 ----
    progress_block = ""
    if progress:
        progress_block = f"""
              <tr><td style="padding:0 24px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                  style="background:#eef2ff;border-radius:12px;">
                  <tr><td style="padding:18px 20px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                      <tr>
                        <td style="font-size:34px;font-weight:700;color:{_BRAND_DARK};
                          line-height:40px;font-family:-apple-system,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif;">
                          {percent}%</td>
                        <td align="right" style="font-size:13px;color:#4b5563;line-height:20px;">
                          {p.get("done")}/{p.get("total")} 任务已完成
                          {" · " + str(p.get("in_flight")) + " 个进行中" if p.get("in_flight") else ""}
                        </td>
                      </tr>
                    </table>
                    <div style="height:10px;line-height:10px;font-size:0;">&nbsp;</div>
                    {_progress_bar(percent)}
                    <div style="height:12px;line-height:12px;font-size:0;">&nbsp;</div>
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                      <tr>
                        <td style="font-size:13px;color:#1f2937;line-height:20px;">
                          <strong style="color:{_BRAND_DARK};">预计完成时间：</strong>{escape(eta_text)}</td>
                      </tr>
                      <tr><td style="font-size:11px;color:#8a93a6;line-height:16px;padding-top:3px;">
                        {escape(eta_basis) if eta_basis else "（尚无足够历史数据估算）"}</td></tr>
                    </table>
                  </td></tr>
                </table>
              </td></tr>
              <tr><td style="height:16px;line-height:16px;font-size:0;">&nbsp;</td></tr>"""

    tasks_block = ""
    if task_list:
        tasks_block = f"""
              <tr><td style="padding:0 24px 6px 24px;font-size:14px;font-weight:600;color:#111827;">
                任务清单</td></tr>
              <tr><td style="padding:0 12px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                  {_task_rows(task_list)}
                </table>
              </td></tr>
              <tr><td style="height:16px;line-height:16px;font-size:0;">&nbsp;</td></tr>"""

    summary_block = ""
    if summary:
        summary_block = f"""
              <tr><td style="padding:0 24px;">
                <div style="font-size:13px;color:#4b5563;line-height:20px;background:#f7f8fb;
                  border-radius:8px;padding:12px 14px;">{escape(summary)}</div>
              </td></tr>
              <tr><td style="height:16px;line-height:16px;font-size:0;">&nbsp;</td></tr>"""

    html = f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <meta name="x-apple-disable-message-reformatting" />
  <meta name="color-scheme" content="light" />
  <meta name="supported-color-schemes" content="light" />
  <title>AideanFleet 通知</title>
  <style type="text/css">
    @media only screen and (max-width:620px) {{
      .sm-px {{ padding-left:14px !important; padding-right:14px !important; }}
      .sm-hero {{ font-size:28px !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background:#f1f3f8;-webkit-text-size-adjust:100%;">
  <div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">
    {escape(event_label)} · 进度 {percent}% · 预计完成 {escape(eta_text)}</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#f1f3f8">
    <tr><td align="center" style="padding:16px 8px;">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
        style="width:100%;max-width:600px;background:#ffffff;border-radius:14px;
          box-shadow:0 1px 4px rgba(15,23,42,0.08);">
        <tr><td bgcolor="{_BRAND}" class="sm-px"
          style="padding:20px 24px;border-radius:14px 14px 0 0;">
          <div style="font-size:12px;letter-spacing:2px;color:#c7d2fe;line-height:16px;">AIDEANFLEET</div>
          <div style="font-size:19px;font-weight:700;color:#ffffff;line-height:28px;
            font-family:-apple-system,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif;">
            {escape(event_label)}{escape(task_line)}</div>
        </td></tr>
        <tr><td style="height:18px;line-height:18px;font-size:0;">&nbsp;</td></tr>{progress_block}{tasks_block}{summary_block}
        <tr><td style="padding:0 24px 18px 24px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
            style="border-top:1px solid #f0f2f7;">
            <tr><td style="padding-top:12px;font-size:11px;color:#9aa3b2;line-height:17px;">
              项目：{escape(project)}{("<br />时间：" + escape(occurred_at)) if occurred_at else ""}<br />
              本邮件由 AideanFleet 自动发送 · 进度与时间为基于任务数据的估算</td></tr>
          </table>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
    return html, plain
