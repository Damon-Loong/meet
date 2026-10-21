"""Email delivery for completed meeting transcripts and summaries."""

import logging
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage
from html import escape
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID
from zoneinfo import ZoneInfo

import requests

from summary.core.config import get_settings
from summary.core.delivery_state import DeliveryState, DeliveryUncertain
from summary.core.meeting_memory import source_date
from summary.core.summary_fallback import is_unavailable

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
        return (
            first_heading.removesuffix("｜会议总结").removesuffix("｜会议纪要").strip()
        )

    # Concise minutes start with a bold date, so use the system-supplied title.
    name = title.removesuffix("的会议总结").strip()
    generated_title = re.fullmatch(
        r'(?:Summary of )?Meeting "(.+)" on \d{4}-\d{2}-\d{2} at \d{2}:\d{2}',
        name,
    )
    return generated_title.group(1) if generated_title else name or "会议"


def _safe_filename(value: str) -> str:
    """Remove characters that are invalid or awkward in attachment filenames."""
    value = re.sub(r'[\\/:*?"<>|\r\n]+', "_", value).strip(" ._")
    return value[:80] or "会议"


def _attachment_prefix(transcript: str, fallback: str) -> str:
    """Prefer the original meeting name over test/delivery title decorations."""
    heading = re.search(r"^#\s+(.+)$", transcript, re.M)
    name = heading[1] if heading else fallback
    name = re.sub(r"^(?:【测试】|\[测试\])\s*", "", name)
    name = re.split(r"[｜|](?:会议转录|会议总结|会议纪要|新版纪要验收)", name)[0]
    name = re.sub(r"的长期会议$", "的会议", name.strip())
    return _safe_filename(name)


def send_meeting_documents(
    *,
    recipients: list[str],
    title: str,
    transcript: str,
    summary: str,
    media_recording_id: UUID | None = None,
    webhook_url: str | None = None,
    webhook_api_key: str | None = None,
    delivery_key: str | None = None,
    supplement: bool = False,
    # 2026-10-20，wyy 新增：个人任务交付扩展，默认参数保持旧邮件行为。
    task_result_text: str | None = None,
    result_attachments: list[dict] | None = None,
) -> None:
    """Send one message to all meeting participants."""
    recipients = list(dict.fromkeys(email.strip().lower() for email in recipients))

    if not settings.email_delivery_enabled:
        logger.info("Email delivery is disabled; skipping message to %s", recipients)
        return

    if task_result_text is not None and (len(recipients) != 1 or not delivery_key):
        raise ValueError("Personal results require one recipient and a delivery key")
    if result_attachments and task_result_text is None:
        raise ValueError("Attachments require a personal result")
    if task_result_text is not None and len(task_result_text) > 100000:
        raise ValueError("Personal result is too large")

    state = DeliveryState(settings.meeting_memory_state_file) if delivery_key else None
    if state and state.status(delivery_key) == "sent":
        return
    if state and state.status(delivery_key) != "ready":
        raise DeliveryUncertain("Email outcome requires review")
    fallback = is_unavailable(summary)
    notice = (
        "会议转录已完成，请查看附件及录音链接。纪要暂未生成成功，系统将自动重试，成功后另行补发；若仍失败需管理员处理。"
        if fallback
        else "本次会议的语音转录和 AI 总结已完成，请查看邮件附件。"
    )

    meeting_name = _meeting_name(title, summary)
    now = datetime.now(ZoneInfo(settings.document_timezone))
    generated_at = now.strftime("%Y-%m-%d %H:%M")
    date_suffix = source_date(transcript).replace("-", "") or "日期未记录"
    filename_prefix = _attachment_prefix(transcript, meeting_name)
    transcript_filename = f"{filename_prefix}｜会议转录_{date_suffix}.md"
    summary_filename = f"{filename_prefix}｜会议总结_{date_suffix}.md"

    media_links: list[tuple[str, str]] = []
    if media_recording_id:
        if not webhook_api_key or not webhook_url:
            raise ValueError("Webhook configuration is required for media links")
        parsed_webhook = urlsplit(webhook_url)
        recording_base = parsed_webhook.path.split("/recordings/", 1)[0]
        media_links_url = urlunsplit(
            (
                parsed_webhook.scheme,
                parsed_webhook.netloc,
                f"{recording_base}/recordings/{media_recording_id}/email-media-links/",
                "",
                "",
            )
        )
        response = requests.post(
            media_links_url,
            headers={"Authorization": f"Bearer {webhook_api_key}"},
            timeout=20,
        )
        response.raise_for_status()
        media = response.json()
        if not media.get("audio"):
            raise ValueError("Meet did not return the transcript audio link")
        media_links.append(("转录音频（OGG）", media["audio"]))
        media_links.extend(
            (f"会议视频 {index}（MP4）", url)
            for index, url in enumerate(media.get("videos", []), start=1)
        )

    plain_media = (
        "录制文件下载（链接自本邮件生成起 24 小时内有效）：\n"
        + "\n".join(f"{label}：{url}" for label, url in media_links)
        + "\n\n"
        if media_links
        else ""
    )
    html_media = (
        '<div style="border:1px solid #dce5ee;border-radius:8px;padding:18px;margin:0 0 22px;">'
        '<h3 style="margin:0 0 12px;font-size:16px;">录制文件下载</h3>'
        + "".join(
            '<p style="margin:0 0 12px;"><a href="{}" style="color:#0645ad;'
            'font-weight:600;text-decoration:underline;">下载{}</a></p>'.format(
                escape(url, quote=True), escape(label)
            )
            for label, url in media_links
        )
        + '<p style="margin:4px 0 0;color:#62748a;font-size:13px;line-height:1.6;">'
        "以上链接自本邮件生成起 24 小时内有效，请及时下载保存。</p></div>"
        if media_links
        else ""
    )

    message = EmailMessage()
    status_label = (
        "纪要补发"
        if supplement
        else ("会议转录已生成，纪要待补发" if fallback else "会议资料已生成")
    )
    message["Subject"] = f"[{settings.email_brand_name}] {status_label}｜{meeting_name}"
    message["From"] = settings.email_from
    message["To"] = ", ".join(recipients)
    # 2026-10-20，wyy 新增：仅个人结果邮件显示执行说明。
    task_notice = "本人任务结果及生成文件见附件。\n\n" if task_result_text is not None else ""
    message.set_content(
        task_notice +
        f"{meeting_name}\n"
        "会议资料已生成\n\n"
        f"{notice}\n"
        f"生成时间：{generated_at}\n\n"
        "会议资料已随邮件附上。\n\n"
        f"{plain_media}"
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
          <h1 style="margin:8px 0 0;font-size:24px;line-height:1.4;">{escape(meeting_name)}</h1>
          <p style="margin:10px 0 0;font-size:14px;opacity:.82;">生成时间：{generated_at}</p>
        </div>
        <div style="padding:28px;">
          <p style="margin:0 0 20px;line-height:1.75;">{escape(notice)}</p>
          {'<p>本人任务结果及生成文件见附件。</p>' if task_result_text is not None else ''}
          {html_media}
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
        filename=(
            f"{filename_prefix}｜纪要生成说明_{date_suffix}.md"
            if fallback
            else summary_filename
        ),
    )

    # 2026-10-20，wyy 新增：附件清单已由可信 worker 验证，沿用原 SMTP 检查点。
    if task_result_text is not None:
        message.add_attachment(task_result_text.encode("utf-8"), maintype="text",
            subtype="plain", filename="会后任务结果.txt")
        for artifact in result_attachments or []:
            path = Path(artifact["path"])
            major, minor = artifact["mime"].split("/", 1)
            message.add_attachment(path.read_bytes(), maintype=major, subtype=minor,
                filename=_safe_filename(path.stem) + path.suffix.lower())

    # Preserve the existing body transfer encoding, but avoid RFC 2231 filename
    # continuations in serialized headers. Stay within the RFC 5322 hard limit.
    message.policy = message.policy.clone(max_line_length=998)
    smtp_class = smtplib.SMTP_SSL if settings.email_use_ssl else smtplib.SMTP
    with smtp_class(settings.email_host, settings.email_port, timeout=30) as smtp:
        if settings.email_use_tls and not settings.email_use_ssl:
            smtp.starttls()
        if settings.email_host_user:
            smtp.login(
                settings.email_host_user,
                settings.email_host_password.get_secret_value(),
            )
        if state and not state.claim(delivery_key):
            return
        try:
            refused = smtp.send_message(message)
            if state and refused:
                raise DeliveryUncertain(
                    "Some recipients were rejected; do not resend to everyone"
                )
        except Exception:
            if state:
                state.finish(delivery_key, "uncertain")
            raise
        if state:
            state.finish(delivery_key, "sent")

    logger.info("Transcript and summary sent to %s", recipients)
