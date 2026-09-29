"""Attachment naming and serialized MIME compatibility regressions."""

# ruff: noqa: D103
from email import policy
from email.parser import BytesParser
from unittest.mock import MagicMock, Mock

from summary.core import email_service


def test_original_meeting_date_and_single_filename_parameter(monkeypatch):
    monkeypatch.setattr(
        email_service,
        "settings",
        email_service.settings.model_copy(
            update={
                "email_delivery_enabled": True,
                "email_use_ssl": False,
                "email_use_tls": False,
                "email_host_user": "",
            }
        ),
    )
    smtp = MagicMock()
    monkeypatch.setattr(email_service.smtplib, "SMTP", Mock(return_value=smtp))
    transcript = (
        "# marsh的长期会议｜会议转录\n\n| 会议开始 | 2026-09-28 16:57:50 |\n"
        + "正文测试。\n" * 12000
    )
    summary = "**会议纪要｜2026 年 9 月 28 日**\n\n- [ ] 完整待办。\n"
    email_service.send_meeting_documents(
        recipients=["test@example.com"],
        title="【测试】marsh的长期会议｜新版纪要验收",
        transcript=transcript,
        summary=summary,
    )
    message = smtp.__enter__.return_value.send_message.call_args.args[0]
    raw = message.as_bytes(policy=message.policy.clone(linesep="\r\n"))
    assert b"filename*0*=" not in raw
    assert raw.count(b"filename*=utf-8''") == 2
    assert max(map(len, raw.split(b"\r\n"))) <= 998
    decoded = BytesParser(policy=policy.default).parsebytes(raw)
    parts = list(decoded.iter_attachments())
    assert [p.get_filename() for p in parts] == [
        "marsh的会议｜会议转录_20260928.md",
        "marsh的会议｜会议总结_20260928.md",
    ]
    assert parts[0].get_payload(decode=True) == transcript.encode("utf-8")
    assert parts[1].get_payload(decode=True) == summary.encode("utf-8")
    assert "【测试】marsh的长期会议｜新版纪要验收" in str(decoded["Subject"])


def test_business_meeting_title_not_rewritten():
    assert (
        email_service._attachment_prefix("# AfB业务讨论｜会议转录", "fallback")
        == "AfB业务讨论"
    )
