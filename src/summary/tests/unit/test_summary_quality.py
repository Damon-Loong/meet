"""Regression tests for the mandatory delivery gate."""

# ruff: noqa: D103
import json
from unittest.mock import Mock

import pytest

from summary.core.summary_quality import (
    SummaryReviewRequired,
    delivery_audit_callback,
    ensure_deliverable,
)


def test_delivery_audit_is_private_and_keeps_each_run(tmp_path):
    for _ in range(2):
        save = delivery_audit_callback(tmp_path / "state.sqlite3", "../../session")
        save({"attempt": 0, "blocking": ["测试"], "draft": "私有草稿"})
    paths = list((tmp_path / "delivery-audit").glob("*/review-0.json"))
    assert len(paths) == 2
    for path in paths:
        assert path.stat().st_mode & 0o777 == 0o600
        assert json.loads(path.read_text())["draft"] == "私有草稿"


def test_audit_failure_does_not_stop_delivery(tmp_path):
    (tmp_path / "delivery-audit").write_text("not a directory")
    save = delivery_audit_callback(tmp_path / "state.sqlite3", "session")
    result = ensure_deliverable(
        draft(), "原文", "", Mock(return_value=GOOD), "规则", audit=save
    )
    assert "仅为预计" in result


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


def test_real_meeting_dangling_speaker_is_repaired():
    call = Mock(side_effect=[GOOD, draft("确定两个方向，每个方向两人。"), GOOD])
    result = ensure_deliverable(
        draft("确定两个方向。Marsh确认"), "原文", "", call, "规则"
    )
    assert "Marsh确认" not in result
    assert "每个方向两人" in result


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


@pytest.mark.parametrize(
    "detail", ["此项由小王负责。", "方案交由Marsh确认。", "下一步请小王确认。"]
)
def test_complete_assignment_is_not_a_fragment(detail):
    result = ensure_deliverable(
        draft(detail), "原文", "", Mock(return_value=GOOD), "规则"
    )
    assert detail in result


def test_mixed_parentheses_do_not_trigger_repair():
    call = Mock(return_value=GOOD)
    result = ensure_deliverable(
        draft("核对资料（包含附件)。"), "原文", "", call, "规则"
    )
    assert "核对资料" in result
    assert call.call_count == 1


def test_punctuation_only_does_not_block_after_failed_repair():
    call = Mock(side_effect=[GOOD, TimeoutError()])
    result = ensure_deliverable(draft("核对资料（包含附件。"), "原文", "", call, "规则")
    assert "核对资料" in result


def test_punctuation_does_not_hide_critical_fact_error():
    call = Mock(side_effect=[CRITICAL, draft("核对资料（包含附件。"), CRITICAL])
    with pytest.raises(SummaryReviewRequired):
        ensure_deliverable(draft("核对资料（包含附件。"), "原文", "", call, "规则")


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
