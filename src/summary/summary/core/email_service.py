"""Email delivery for completed meeting transcripts and summaries."""

import logging
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage
from html import escape
from zoneinfo import ZoneInfo

from summary.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def _meeting_name(title: str, summary: str) -> str:
    """Return a concise meeting name suitable for subjects and filenames."""
    first_heading = next(
        (
            line.removeprefix("# ").strip()
            for line in summary.splitlines()
            if line.startswith("# ")
        ),
        "",
    )
    if first_heading:
        return first_heading.removesuffix("｜会议总结").strip()

    return title.removesuffix("的会议总结").strip() or "会议"


def _safe_filename(value: str) -> str:
    """Remove characters that are invalid or awkward in attachment filenames."""
    value = re.sub(r'[\\/:*?"<>|\r\n]+', "_", value).strip(" ._")
    return value[:80] or "会议"


def send_meeting_documents(
    *, recipients: list[str], title: str, transcript: str, summary: str
) -> None:
    """Send one message to all meeting participants."""
    recipients = list(dict.fromkeys(email.strip().lower() for email in recipients))

    if not settings.email_delivery_enabled:
        logger.info("Email delivery is disabled; skipping message to %s", recipients)
        return

    meeting_name = _meeting_name(title, summary)
    now = datetime.now(ZoneInfo(settings.document_timezone))
    generated_at = now.strftime("%Y-%m-%d %H:%M")
    date_suffix = now.strftime("%Y%m%d")
    filename_prefix = _safe_filename(meeting_name)
    transcript_filename = f"{filename_prefix}_会议转录_{date_suffix}.md"
    summary_filename = f"{filename_prefix}_会议总结_{date_suffix}.md"

    message = EmailMessage()
    message["Subject"] = (
        f"[{settings.email_brand_name}] 会议资料已生成｜{meeting_name}"
    )
    message["From"] = settings.email_from
    message["To"] = ", ".join(recipients)
    message.set_content(
        f"{meeting_name}\n"
        "会议资料已生成\n\n"
        f"{settings.email_brand_name} 已完成本次会议的语音转录和 AI 总结。\n"
        f"生成时间：{generated_at}\n\n"
        "附件：\n"
        f"1. {transcript_filename}：按时间顺序整理的会议转录。\n"
        f"2. {summary_filename}：根据转录内容生成的会议纪要与行动项。\n\n"
        "提示：AI 生成内容可能存在识别或理解偏差，重要结论、姓名、数字和日期请结合会议原始内容核对。\n\n"
        "此邮件由系统自动发送。"
    )
    message.add_alternative(
        f"""<!doctype html>
<html lang="zh-CN">
  <body style="margin:0;background:#f4f6f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',Arial,sans-serif;color:#182230;">
    <div style="max-width:640px;margin:0 auto;padding:32px 16px;">
      <div style="background:#ffffff;border:1px solid #e5e9ef;border-radius:12px;overflow:hidden;">
        <div style="padding:24px 28px;background:#102a43;color:#ffffff;">
          <div style="font-size:14px;opacity:.82;">{escape(settings.email_brand_name)}</div>
          <h1 style="margin:8px 0 0;font-size:24px;line-height:1.35;">会议资料已生成</h1>
        </div>
        <div style="padding:28px;">
          <h2 style="margin:0 0 8px;font-size:20px;line-height:1.4;">{escape(meeting_name)}</h2>
          <p style="margin:0 0 24px;color:#62748a;font-size:14px;">生成时间：{generated_at}</p>
          <p style="margin:0 0 20px;line-height:1.75;">本次会议的语音转录和 AI 总结已完成，请查看邮件附件。</p>
          <div style="border:1px solid #e5e9ef;border-radius:8px;padding:16px 18px;margin-bottom:22px;">
            <div style="margin-bottom:12px;"><strong>会议转录</strong><br><span style="color:#62748a;font-size:14px;">按时间顺序整理的完整转录内容</span></div>
            <div><strong>会议总结</strong><br><span style="color:#62748a;font-size:14px;">会议结论、议题摘要与行动项</span></div>
          </div>
          <p style="margin:0;padding:14px 16px;background:#fff8e6;border-radius:8px;color:#725400;font-size:13px;line-height:1.65;">AI 生成内容可能存在识别或理解偏差，重要结论、姓名、数字和日期请结合会议原始内容核对。</p>
        </div>
        <div style="padding:16px 28px;border-top:1px solid #e5e9ef;color:#7b8794;font-size:12px;">此邮件由 {escape(settings.email_brand_name)} 自动发送。</div>
      </div>
    </div>
  </body>
</html>""",
        subtype="html",
    )
    message.add_attachment(
        transcript.encode("utf-8"),
        maintype="text",
        subtype="markdown",
        filename=transcript_filename,
    )
    message.add_attachment(
        summary.encode("utf-8"),
        maintype="text",
        subtype="markdown",
        filename=summary_filename,
    )

    smtp_class = smtplib.SMTP_SSL if settings.email_use_ssl else smtplib.SMTP
    with smtp_class(settings.email_host, settings.email_port, timeout=30) as smtp:
        if settings.email_use_tls and not settings.email_use_ssl:
            smtp.starttls()
        if settings.email_host_user:
            smtp.login(
                settings.email_host_user,
                settings.email_host_password.get_secret_value(),
            )
        smtp.send_message(message)

    logger.info("Transcript and summary sent to %s", recipients)
