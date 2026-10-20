"""Fault injection for partial minutes, transcript-first mail and supplements."""

# ruff: noqa: D103
import json
from unittest.mock import MagicMock, Mock

import pytest

from summary.core import celery_worker as worker
from summary.core import email_service
from summary.core.delivery_state import DeliveryState, DeliveryUncertain
from summary.core.llm_service import LLMException
from summary.core.summary_fallback import (
    is_unavailable,
    salvage_draft,
    unavailable_summary,
)


def candidate():
    return json.dumps(
        {
            "conclusions": [
                {"title": "资料", "detail": "资料已整理。"},
                {"title": "支出", "detail": "批准支出一千万元。"},
            ],
            "owners": [
                {
                    "owner": "小王",
                    "focus": "支付",
                    "actions": [{"task": "支付一千万元", "timing": "今天"}],
                }
            ],
            "uncertainties": [],
        },
        ensure_ascii=False,
    )


def test_partial_keeps_exact_supported_text_without_bad_tasks():
    call = Mock(
        return_value=json.dumps(
            {
                "items": [
                    {"item_id": "c0", "supported": True},
                    {"item_id": "c1", "supported": False},
                    {"item_id": "a0_0", "supported": False},
                ]
            }
        )
    )
    result = salvage_draft(
        candidate(), "资料已整理，支出尚未批准。", call, ["金额未经批准"]
    )
    assert "资料已整理" in result
    assert "一千万元" not in result
    assert "- [ ]" not in result
    assert "确认" in result


@pytest.mark.parametrize(
    "reply",
    ["{}", '{"items":[]}', '{"items":[{"item_id":"unknown","supported":true}]}'],
)
def test_missing_or_invalid_item_verdict_falls_back(reply):
    assert is_unavailable(
        salvage_draft(candidate(), "转录", Mock(return_value=reply), [])
    )


def test_smtp_duplicate_and_ambiguous_outcome(monkeypatch):
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
    sender = smtp.__enter__.return_value.send_message
    sender.return_value = {}
    monkeypatch.setattr(email_service.smtplib, "SMTP", Mock(return_value=smtp))
    kwargs = {
        "recipients": ["test@example.com"],
        "title": "会议",
        "transcript": "完整转录",
        "summary": unavailable_summary(),
        "delivery_key": "job:initial",
    }
    email_service.send_meeting_documents(**kwargs)
    email_service.send_meeting_documents(**kwargs)
    sender.assert_called_once()
    message = sender.call_args.args[0]
    assert "纪要待补发" in message["Subject"]
    assert (
        "AI 总结已完成" not in message.get_body(preferencelist=("html",)).get_content()
    )
    assert "纪要生成说明" in list(message.iter_attachments())[1].get_filename()
    sender.side_effect = TimeoutError()
    kwargs["delivery_key"] = "job2:initial"
    with pytest.raises(TimeoutError):
        email_service.send_meeting_documents(**kwargs)
    with pytest.raises(DeliveryUncertain):
        email_service.send_meeting_documents(**kwargs)
    assert sender.call_count == 2


def wire_worker(monkeypatch):
    monkeypatch.setattr(
        worker,
        "settings",
        worker.settings.model_copy(update={"email_delivery_enabled": True}),
    )
    monkeypatch.setattr(worker, "optional_history", lambda *_: "")
    monkeypatch.setattr(worker, "personal_context", lambda *_: "")
    monkeypatch.setattr(worker, "_should_push_to_docs", lambda *_: False)
    monkeypatch.setattr(worker.file_service, "store_summary", Mock())
    monkeypatch.setattr(
        worker.file_service,
        "get_summary_signed_url",
        lambda _: "https://example.com/summary",
    )
    monkeypatch.setattr(worker.call_webhook_v2_task, "apply_async", Mock())
    monkeypatch.setattr(worker.metadata_manager, "capture", Mock())
    monkeypatch.setattr(worker, "enqueue_personal_memory", Mock())
    return {
        "tenant_id": "test-tenant",
        "user_sub": "test",
        "content": "会议原始转录",
        "received_at": "2026-10-20T00:00:00Z",
        "recipient_emails": ["test@example.com"],
        "push_to_docs_config": {"user_email": "test@example.com", "title": "会议"},
    }


def test_generation_failure_sends_transcript_then_recovers_once(monkeypatch):
    payload = wire_worker(monkeypatch)
    state = DeliveryState(worker.settings.meeting_memory_state_file)
    sends = []

    def send(**kwargs):
        key = kwargs["delivery_key"]
        if state.claim(key):
            sends.append(kwargs)
            state.finish(key, "sent")

    monkeypatch.setattr(worker, "send_meeting_documents", send)
    generate = Mock(
        side_effect=[
            LLMException("empty response"),
            "**会议纪要｜2026 年 10 月 20 日**\n\n资料整理完毕。",
        ]
    )
    monkeypatch.setattr(worker, "summarize_transcription_internals", generate)
    queue = Mock()
    monkeypatch.setattr(worker.recover_summary_mail_task, "apply_async", queue)
    job = "00000000-0000-0000-0000-000000000009"
    worker.summarize_v2_task.push_request(id=job)
    try:
        worker.summarize_v2_task.run(payload)
        worker.summarize_v2_task.run(payload)
    finally:
        worker.summarize_v2_task.pop_request()
    assert len(sends) == 1
    assert is_unavailable(sends[0]["summary"])
    worker.enqueue_personal_memory.assert_not_called()
    assert queue.call_args.kwargs["countdown"] == 300
    worker.recover_summary_mail_task.run(payload, job)
    worker.recover_summary_mail_task.run(payload, job)
    assert len(sends) == 2
    assert sends[1]["supplement"] is True
    assert not is_unavailable(sends[1]["summary"])
    assert generate.call_count == 2
    scheduled = queue.call_count
    worker.summarize_v2_task.push_request(id=job)
    try:
        worker.summarize_v2_task.run(payload)
    finally:
        worker.summarize_v2_task.pop_request()
    assert queue.call_count == scheduled
    assert len(sends) == 2
    assert not is_unavailable(
        worker.file_service.store_summary.call_args.kwargs["summary"]
    )


def test_recovery_exhaustion_does_not_send_another_fallback(monkeypatch):
    payload = wire_worker(monkeypatch)
    state = DeliveryState(worker.settings.meeting_memory_state_file)
    state.claim("test-tenant:job:initial")
    state.finish("test-tenant:job:initial", "sent")
    monkeypatch.setattr(
        worker,
        "summarize_transcription_internals",
        Mock(return_value=unavailable_summary()),
    )
    mail = Mock()
    monkeypatch.setattr(worker, "send_meeting_documents", mail)
    worker.recover_summary_mail_task.push_request(retries=1)
    try:
        result = worker.recover_summary_mail_task.run(payload, "job")
    finally:
        worker.recover_summary_mail_task.pop_request()
    assert result["status"] == "needs_review"
    mail.assert_not_called()


def test_recovery_waits_fifteen_minutes_after_first_failed_attempt(monkeypatch):
    from celery.exceptions import Retry  # noqa: PLC0415

    payload = wire_worker(monkeypatch)
    state = DeliveryState(worker.settings.meeting_memory_state_file)
    state.claim("test-tenant:job:initial")
    state.finish("test-tenant:job:initial", "sent")
    monkeypatch.setattr(
        worker,
        "summarize_transcription_internals",
        Mock(side_effect=LLMException("offline")),
    )
    retry = Mock(side_effect=Retry())
    monkeypatch.setattr(worker.recover_summary_mail_task, "retry", retry)
    worker.recover_summary_mail_task.push_request(retries=0)
    try:
        with pytest.raises(Retry):
            worker.recover_summary_mail_task.run(payload, "job")
    finally:
        worker.recover_summary_mail_task.pop_request()
    assert retry.call_args.kwargs["countdown"] == 900


def test_parallel_claims_allow_only_one_sender(tmp_path):
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    state = DeliveryState(tmp_path / "memory.sqlite3")

    def claim(_):
        try:
            return state.claim("one")
        except DeliveryUncertain:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(claim, range(4))) == 1


def test_all_rejected_items_use_transcript_notice():
    call = Mock(
        return_value=json.dumps(
            {
                "items": [
                    {"item_id": item, "supported": False}
                    for item in ("c0", "c1", "a0_0")
                ]
            }
        )
    )
    result = salvage_draft(candidate(), "原文", call, [])
    assert is_unavailable(result)
    assert "一千万元" not in result
