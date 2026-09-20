"""Email delivery for completed meeting transcripts and summaries."""

import logging
import smtplib
from email.message import EmailMessage

from summary.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def send_meeting_documents(
    *, recipients: list[str], title: str, transcript: str, summary: str
) -> None:
    """Send one message to all meeting participants."""
    recipients = list(dict.fromkeys(email.strip().lower() for email in recipients))

    if not settings.email_delivery_enabled:
        logger.info("Email delivery is disabled; skipping message to %s", recipients)
        return

    message = EmailMessage()
    message["Subject"] = f"{title}：转录和 AI 总结"
    message["From"] = settings.email_from
    message["To"] = ", ".join(recipients)
    message.set_content(
        f"{settings.email_brand_name} 已完成本次会议的语音转录和 AI 总结。\n\n"
        "转录文档和会议总结已作为附件发送。"
    )
    message.add_attachment(
        transcript.encode("utf-8"),
        maintype="text",
        subtype="markdown",
        filename="会议转录.md",
    )
    message.add_attachment(
        summary.encode("utf-8"),
        maintype="text",
        subtype="markdown",
        filename="会议总结.md",
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
