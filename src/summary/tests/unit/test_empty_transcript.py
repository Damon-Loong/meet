"""Label-only meetings complete without downstream AI work or delivery."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from summary.core.locales.zh import STRINGS
from summary.core.transcript_content import (
    has_spoken_text,
    is_refusal_only,
    strip_timestamp_labels,
)
from summary.core.transcript_formatter import TranscriptFormatter


@pytest.mark.parametrize("text", ["", "  ", "[S01]", "[S260][3.99]", "[0][S01][3.99]", "[00:03:02.99][speaker_2]", "[S01] [S02] [4.00]"])
def test_labels_are_not_spoken_text(text):
    assert not has_spoken_text(text)


@pytest.mark.parametrize("text", ["[S01]Price is 3.99", "[S01]I'm sorry, I can't assist with that request.", "[S01] [AI] 100", "[S01]0"])
def test_actual_words_and_ordinary_numbers_are_preserved(text):
    assert has_spoken_text(text)
    assert strip_timestamp_labels(text) == text


@pytest.mark.parametrize("texts", [
    ["[S01]I'm sorry, I can't assist with that request."],
    ["[S01][2.00] I'm sorry, but I can't assist with that request.[4.00]"],
    ["[S01]I'm sorry,", "[S01]I can't assist with that request."],
    ["I’m sorry, I can’t assist with that request."],
    ["I'm sorry, I can't assist with that request."] * 2,
])
def test_matches_only_observed_refusal(texts):
    assert is_refusal_only(texts)


@pytest.mark.parametrize("texts", [
    ["[S01]I'm sorry, I can't assist with that request.", "[S02]Please discuss the budget."],
    ["The model replied: I'm sorry, I can't assist with that request."],
    ["I'm sorry, but I can't assist with that request.", "Yes, you can ask the question."],
    ["I'm sorry, I cannot join the meeting."],
    [],
])
def test_does_not_match_other_speech_or_quoted_refusal(texts):
    assert not is_refusal_only(texts)


def test_formatter_filters_time_labels_but_keeps_speech():
    formatter = TranscriptFormatter(STRINGS)
    body = formatter._format_speaker([
        {"start": 3.99, "text": "[S260][3.99]"},
        {"start": 10, "text": "[S01][10.00]Price is 3.99[12.00]"},
    ], [])
    assert "[3.99]" not in body
    assert "[10.00]" not in body
    assert "[12.00]" not in body
    assert "Price is 3.99" in body
    assert "[00:00:10]" in body
    assert len(body.splitlines()) == 1


@pytest.mark.parametrize("segments", [[], [{"text": "[S01]"}], [{"text": "[S260][3.99]"}], [{"text": "[S01]"}, {"text": "[S02][0.00][00:00:03.99]"}], [{"text": "[S01]I'm sorry, I can't assist with that request."}], [{"text": "[S01]I'm sorry, but I can't assist with that request."}], [{"text": "[S01]I'm sorry,"}, {"text": "[S01]I can't assist with that request."}]])
def test_empty_meeting_stops_before_documents_ai_and_delivery(monkeypatch, segments):
    from summary.core import celery_worker as worker
    from openai.types.audio import Transcription

    response = Transcription(text="", segments=segments)
    monkeypatch.setattr(worker, "transcribe_audio", Mock(return_value=(response, False)))
    mocks = {}
    for name in (
        "format_transcript", "correct_transcript_spelling", "resolve_speaker_identities_and_apply_to",
        "create_document_in_lasuite_docs", "summarize_v2_task", "enqueue_meeting_archive",
        "file_service", "call_webhook_v2_task", "metadata_manager",
    ):
        mocks[name] = Mock()
        monkeypatch.setattr(worker, name, mocks[name])
    mocks["file_service"].get_transcript_signed_url.return_value = "https://example.com/empty.json"
    payload = {
        "received_at": datetime.now(timezone.utc), "tenant_id": "test-tenant",
        "user_sub": "test-user", "user_email": "owner@example.com",
        "recipient_emails": ["owner@example.com"], "cloud_storage_url": "https://example.com/audio.ogg",
        "language": "en", "context_language": "en",
    }
    task = worker.process_audio_transcribe_v2_task
    task.push_request(id="empty-meeting-test")
    try:
        result = task.run(payload)
    finally:
        task.pop_request()
    for name in ("format_transcript", "correct_transcript_spelling", "resolve_speaker_identities_and_apply_to", "create_document_in_lasuite_docs", "enqueue_meeting_archive"):
        mocks[name].assert_not_called()
    mocks["summarize_v2_task"].apply_async.assert_not_called()
    stored = mocks["file_service"].store_transcript.call_args.kwargs["transcript"]
    assert stored.segments == ()
    mocks["call_webhook_v2_task"].apply_async.assert_called_once()
    assert result["status"] == "success"


def test_normal_meeting_keeps_summary_path_and_removes_only_time_labels(monkeypatch):
    from summary.core import celery_worker as worker
    from openai.types.audio import Transcription

    response = Transcription(text="", segments=[{"text": "[S01][3.99]Price is 3.99[5.00]"}, {"text": "[S02][6.00]"}])
    monkeypatch.setattr(worker, "transcribe_audio", Mock(return_value=(response, False)))
    monkeypatch.setattr(worker, "settings", worker.settings.model_copy(update={"transcript_correction_enabled": False, "is_resolve_speaker_identities_enabled": False}))
    monkeypatch.setattr(worker, "_should_push_to_docs", Mock(return_value=False))
    monkeypatch.setattr(worker, "_should_auto_create_summary", Mock(return_value=True))
    formatter = Mock(return_value="formatted transcript")
    monkeypatch.setattr(worker, "format_transcript", formatter)
    summary = Mock()
    monkeypatch.setattr(worker, "summarize_v2_task", summary)
    for name in ("enqueue_meeting_archive", "file_service", "call_webhook_v2_task", "metadata_manager"):
        monkeypatch.setattr(worker, name, Mock())
    worker.file_service.get_transcript_signed_url.return_value = "https://example.com/transcript.json"
    payload = SimpleNamespace(
        metadata=None, cloud_storage_url="https://example.com/audio.ogg", language="en", context_language="en",
        tenant_id="test-tenant", user_sub="test-user", user_email="owner@example.com",
        recipient_emails=["owner@example.com"], media_recording_id=None,
        push_to_docs_config=SimpleNamespace(title="Meeting", download_link=None, form_link=None, user_email="owner@example.com"),
    )
    monkeypatch.setattr(worker, "TranscribeTaskJob", Mock(model_validate=Mock(return_value=payload)))
    task = worker.process_audio_transcribe_v2_task
    task.push_request(id="normal-meeting-test")
    try:
        result = task.run({})
    finally:
        task.pop_request()
    assert [s["text"] for s in formatter.call_args.args[0]["segments"]] == ["[S01]Price is 3.99"]
    summary.apply_async.assert_called_once()
    worker.enqueue_meeting_archive.assert_called_once()
    assert result["status"] == "success"
