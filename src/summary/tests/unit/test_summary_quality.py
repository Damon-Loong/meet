"""Regression tests for the mandatory delivery gate."""

# ruff: noqa: D103
import json
from unittest.mock import Mock

import pytest

from summary.core.summary_quality import SummaryReviewRequired, ensure_deliverable


def draft(detail="仅为预计，尚未确定。"):
    return json.dumps(
        {
            "conclusions": [{"title": "安排", "detail": detail}],
            "owners": [],
            "uncertainties": [],
        },
        ensure_ascii=False,
    )


GOOD = '{"approved":true,"issues":[],"critical_issues":[]}'
BAD = '{"approved":false,"issues":["期限未明确"],"critical_issues":[]}'
CRITICAL = '{"approved":false,"issues":[],"critical_issues":["核心决策与原文相反"]}'


def test_approved_draft_is_rendered():
    call = Mock(return_value=GOOD)
    assert "仅为预计" in ensure_deliverable(draft(), "原文", "历史", call, "规则")
    assert "原文" in call.call_args.args[1]


def test_one_repair_then_full_review():
    call = Mock(side_effect=[BAD, draft("时间待确认。"), GOOD])
    assert "时间待确认" in ensure_deliverable(draft(), "原文", "", call, "规则")
    assert [c.kwargs["name"] for c in call.call_args_list] == [
        "delivery-review-0",
        "delivery-repair",
        "delivery-review-1",
    ]


def test_major_error_repair_never_returned():
    call = Mock(side_effect=[CRITICAL, draft(), CRITICAL])
    with pytest.raises(SummaryReviewRequired):
        ensure_deliverable(draft(), "原文", "", call, "规则")
    assert call.call_count == 3


@pytest.mark.parametrize("reply", ["{}", "not json", '{"approved":false,"issues":[]}'])
def test_invalid_or_negative_verdict_does_not_block(reply):
    call = Mock(return_value=reply)
    assert "仅为预计" in ensure_deliverable(draft(), "原文", "", call, "规则")


def test_local_fragment_check_overrides_optimistic_reviewer():
    broken = draft("通过部署")
    call = Mock(side_effect=[GOOD, broken, GOOD])
    with pytest.raises(SummaryReviewRequired):
        ensure_deliverable(broken, "原文", "", call, "规则")


def test_review_outage_does_not_block():
    assert "仅为预计" in ensure_deliverable(
        draft(), "原文", "", Mock(side_effect=TimeoutError), "规则"
    )


@pytest.mark.parametrize("repair", ["{}", TimeoutError()])
def test_failed_minor_repair_preserves_usable_original(repair):
    call = Mock(side_effect=[BAD, repair])
    assert "仅为预计" in ensure_deliverable(draft(), "原文", "", call, "规则")


def test_minor_disagreement_after_repair_still_delivers():
    call = Mock(side_effect=[BAD, draft("时间待确认。"), BAD])
    assert "时间待确认" in ensure_deliverable(draft(), "原文", "", call, "规则")


def test_major_error_not_cleared_by_reviewer_outage():
    call = Mock(side_effect=[CRITICAL, draft(), TimeoutError()])
    with pytest.raises(SummaryReviewRequired):
        ensure_deliverable(draft(), "原文", "", call, "规则")


def test_malformed_draft_can_be_repaired_once():
    call = Mock(side_effect=[draft(), GOOD])
    assert "仅为预计" in ensure_deliverable("{}", "原文", "", call, "规则")


def test_failed_gate_stops_before_storage_or_email(monkeypatch):
    from summary.core import celery_worker  # noqa: PLC0415

    generate = Mock(side_effect=SummaryReviewRequired())
    save, send = Mock(), Mock()
    monkeypatch.setattr(celery_worker, "summarize_transcription_internals", generate)
    monkeypatch.setattr(celery_worker.file_service, "store_summary", save)
    monkeypatch.setattr(celery_worker, "send_meeting_documents", send)
    monkeypatch.setattr(celery_worker, "optional_history", lambda *_: "")
    with pytest.raises(SummaryReviewRequired):
        celery_worker.summarize_v2_task.run(
            {
                "tenant_id": "test-tenant",
                "user_sub": "test",
                "content": "原文",
                "received_at": "2026-09-29T00:00:00Z",
                "recipient_emails": ["test@example.com"],
                "push_to_docs_config": {
                    "user_email": "test@example.com",
                    "title": "测试",
                },
            }
        )
    save.assert_not_called()
    send.assert_not_called()
    assert SummaryReviewRequired in celery_worker.summarize_v2_task.dont_autoretry_for
