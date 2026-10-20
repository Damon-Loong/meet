"""Semantic regression cases use synthetic source material, never real meetings."""

# ruff: noqa: D103

import json
from copy import deepcopy
from unittest.mock import Mock

import pytest

from summary.core import celery_worker
from summary.core.evidence_summary import (
    Claim,
    DraftClaim,
    Repair,
    SummaryReviewRequired,
    Turn,
    _apply_repair,
    check_claim,
    draft_claim,
    generate_evidence_summary,
    materialize,
    revise_evidence_summary,
    source_turns,
    source_windows,
)

SOURCE = """# 测试会议
## 会议概览
| 会议开始 | 2026-09-20 10:00:00 |
## 参会人员
李明、小王
## 逐字转录
- **[00:00:01] 发言人 01：** 小王整理验收清单，预计下周完成。
- **[00:00:02] 发言人 02：** 好的。
"""


@pytest.fixture()
def candidate():
    return {
        "kind": "action",
        "status": "confirmed",
        "text": "整理验收清单。",
        "sources": [{"turn_id": "T0001", "quote": "小王整理验收清单，预计下周完成。"}],
        "owner": "小王",
        "owner_display": "小王",
        "owner_sources": [{"turn_id": "T0001", "quote": "小王整理验收清单"}],
        "timing": {
            "kind": "estimate",
            "text": "预计下周完成",
            "sources": [{"turn_id": "T0001", "quote": "预计下周完成"}],
        },
    }


def errors(candidate, source=SOURCE):
    turns = {turn.id: turn for turn in source_turns(source)}
    return check_claim(Claim.model_validate(candidate), turns)


def reviewer(status="supported", **kwargs):
    result = {
        "verdicts": [
            {"claim_id": "C0001", "status": status, "reason": "已核对原文及回应"}
        ],
        "conclusion_ids": [],
        "coverage_complete": True,
        "coverage_issues": [],
    }
    result.update(kwargs)
    return result


def generate(candidate, review=None, source=SOURCE):
    call = Mock(
        side_effect=[
            json.dumps(
                {"claims": [draft_claim(Claim.model_validate(candidate)).model_dump()]}
            ),
            json.dumps(review or reviewer()),
        ]
    )
    result = generate_evidence_summary(source, call, reconcile=False, max_revisions=0)
    return result, call


def test_source_ids_ignore_roster_and_preserve_unknown_speakers():
    turns = source_turns(SOURCE)
    assert len(turns) == 2
    assert turns[0].id == "T0001"
    assert turns[0].speaker == "发言人 01"
    assert turns[0].text == "小王整理验收清单，预计下周完成。"
    assert turns[0].timestamp == "00:00:01"


def test_window_boundaries_include_replies_without_losing_turns():
    turns = [
        Turn(id=f"T{i}", timestamp="", speaker="", text="一句话" * 5) for i in range(20)
    ]
    windows = source_windows(turns, budget=50, overlap=2)
    assert {t.id for w in windows for t in w} == {t.id for t in turns}
    assert {t.id for t in windows[0]} & {t.id for t in windows[1]}


def test_valid_owner_and_estimate_are_not_upgraded(candidate):
    assert errors(candidate) == []
    result, _ = generate(candidate)
    assert result.safe_to_deliver
    assert "预计：预计下周完成" in result.markdown
    assert "截止" not in result.markdown.split("**待确认事项**")[0]


@pytest.mark.parametrize("owner", ["王晓", "李明", "发言人 01"])
def test_roster_or_similar_name_does_not_prove_assignment(candidate, owner):
    candidate["owner"] = owner
    assert any("owner" in error for error in errors(candidate))


def test_named_speaker_can_accept_task_without_repeating_own_name(candidate):
    source = SOURCE.replace("发言人 01：** 小王整理", "小王：** 我来整理")
    candidate["sources"][0]["quote"] = "我来整理验收清单"
    candidate["owner_sources"][0]["quote"] = "我来整理验收清单"
    assert errors(candidate, source) == []


def test_unknown_speaker_cannot_be_mapped_to_roster(candidate):
    source = SOURCE.replace("小王整理", "我来整理")
    candidate["sources"][0]["quote"] = "我来整理验收清单"
    candidate["owner_sources"][0]["quote"] = "我来整理验收清单"
    assert "owner_not_explicit_in_evidence" in errors(candidate, source)


def test_explicit_raw_name_is_preserved_not_fuzzy_matched(candidate):
    candidate["owner"] = "老王"
    candidate["owner_display"] = "老王"
    candidate["sources"][0]["quote"] = candidate["sources"][0]["quote"].replace(
        "小王", "老王"
    )
    candidate["owner_sources"][0]["quote"] = "老王整理验收清单"
    result, _ = generate(candidate, source=SOURCE.replace("：** 小王", "：** 老王"))
    assert result.safe_to_deliver
    assert "**老王｜待办**" in result.markdown
    assert "姓名待核对" not in result.markdown


def test_obvious_name_typo_uses_roster_without_changing_source(candidate):
    source = SOURCE.replace("李明、小王", "李明、王晓明").replace(
        "小王整理", "王小明整理"
    )
    candidate["owner"] = "王小明"
    candidate["owner_display"] = "王晓明"
    for field in ("sources", "owner_sources"):
        candidate[field][0]["quote"] = candidate[field][0]["quote"].replace(
            "小王", "王小明"
        )
    result, call = generate(candidate, source=source)
    assert result.safe_to_deliver
    assert "**王晓明｜待办**" in result.markdown
    assert result.claims["C0001"].owner == "王小明"
    assert "王小明整理" in result.claims["C0001"].owner_sources[0].quote
    assert all("李明、王晓明" in entry.args[1] for entry in call.call_args_list)


def test_unknown_display_name_falls_back_without_blocking(candidate):
    candidate["owner_display"] = "王某某"
    result, _ = generate(candidate)
    assert result.safe_to_deliver
    assert "**小王｜待办**" in result.markdown
    assert "王某某" not in result.markdown


def test_name_variant_between_assignment_and_acceptance_does_not_block(candidate):
    source = (
        SOURCE.replace("李明、小王", "李明、王晓明")
        .replace("小王整理", "王小明整理")
        .replace("好的。", "王小名盯一下这个事情。")
    )
    candidate["owner"] = "王小明"
    candidate["owner_display"] = "王晓明"
    candidate["sources"][0]["quote"] = "王小明整理验收清单，预计下周完成。"
    candidate["owner_sources"] = [
        {"turn_id": "T0002", "quote": "王小名盯一下这个事情。"}
    ]
    result, _ = generate(candidate, source=source)
    assert result.safe_to_deliver
    assert "**王晓明｜待办**" in result.markdown


def test_joint_owners_need_not_appear_as_one_contiguous_name(candidate):
    source = SOURCE.replace("小王整理", "小王和李明一起整理")
    candidate["owner"] = "小王、李明"
    candidate["owner_display"] = "小王、李明"
    for field in ("sources", "owner_sources"):
        candidate[field][0]["quote"] = "小王和李明一起整理验收清单"
    result, _ = generate(candidate, source=source)
    assert result.safe_to_deliver
    assert "**小王、李明｜待办**" in result.markdown


def test_unassigned_task_is_retained_without_inventing_a_person(candidate):
    candidate["owner"] = ""
    candidate["owner_sources"] = []
    result, _ = generate(candidate)
    assert "负责人待确认：整理验收清单" in result.markdown
    assert "- [ ]" not in result.markdown


def test_estimate_cannot_be_promoted_even_with_cherry_picked_quote(candidate):
    candidate["timing"] = {
        "kind": "deadline",
        "text": "下周完成",
        "sources": [{"turn_id": "T0001", "quote": "下周完成"}],
    }
    assert "qualified_time_promoted_to_deadline" in errors(candidate)
    result, _ = generate(candidate)
    assert not result.safe_to_deliver
    assert "- [ ]" not in result.markdown


def test_explicit_deadline_is_retained(candidate):
    source = SOURCE.replace("预计下周完成", "必须周五之前完成")
    candidate["sources"][0]["quote"] = "小王整理验收清单"
    candidate["timing"] = {
        "kind": "deadline",
        "text": "周五之前完成",
        "sources": [{"turn_id": "T0001", "quote": "必须周五之前完成"}],
    }
    assert errors(candidate, source) == []


def test_later_wait_condition_blocks_a_proposed_tuesday_date(candidate):
    source = SOURCE.replace("预计下周完成", "我觉得周二完成").replace(
        "好的。", "需要等大会结束，做不了。"
    )
    candidate["sources"][0]["quote"] = "小王整理验收清单"
    candidate["timing"] = {
        "kind": "target",
        "text": "周二完成",
        "sources": [{"turn_id": "T0001", "quote": "我觉得周二完成"}],
    }
    result, call = generate(candidate, reviewer("needs_review"), source=source)
    assert not result.safe_to_deliver
    assert "需要等大会结束" in call.call_args.args[1]
    assert "近邻可能修改时间" in call.call_args.args[1]


def test_relative_date_cannot_be_replaced_with_a_guessed_calendar_date(candidate):
    candidate["timing"]["text"] = "2026年9月28日完成"
    assert "time_wording_changed" in errors(candidate)


@pytest.mark.parametrize(
    "ref",
    [
        {"turn_id": "T9999", "quote": "小王整理验收清单"},
        {"turn_id": "T0001", "quote": "小王负责采购并已获批"},
        {"turn_id": "T0001", "quote": ""},
    ],
)
def test_fabricated_citations_are_blocked(candidate, ref):
    candidate["sources"] = [ref]
    assert errors(candidate)


def test_proposal_is_not_rendered_as_confirmed_decision(candidate):
    candidate["kind"] = "decision"
    candidate["status"] = "proposed"
    result, _ = generate(candidate, reviewer(conclusion_ids=["C0001"]))
    assert result.safe_to_deliver
    assert "未定案" in result.markdown
    assert "已确认决定" not in result.markdown


def test_completed_or_proposed_action_cannot_be_published(candidate):
    candidate["status"] = "withdrawn"
    result, _ = generate(candidate)
    assert result.safe_to_deliver
    assert "- [ ]" not in result.markdown
    assert "整理验收清单" not in result.markdown


@pytest.mark.parametrize("status", ["needs_review", "rejected"])
def test_semantic_rejection_blocks_delivery_even_if_quotes_match(candidate, status):
    result, call = generate(candidate, reviewer(status))
    assert not result.safe_to_deliver
    assert "- [ ]" not in result.markdown
    assert "好的。" in call.call_args.args[1]  # review sees replies, not only extracts


@pytest.mark.parametrize(
    "verdicts",
    [
        [],
        [
            {"claim_id": "C0001", "status": "supported", "reason": ""},
            {"claim_id": "C0001", "status": "supported", "reason": ""},
        ],
        [{"claim_id": "C9999", "status": "supported", "reason": ""}],
    ],
)
def test_missing_duplicate_or_invented_review_ids_fail_closed(candidate, verdicts):
    result, _ = generate(candidate, reviewer(verdicts=verdicts))
    assert "review_missing_or_duplicate_claim_ids" in result.issues


def test_missing_important_coverage_blocks_delivery(candidate):
    result, _ = generate(
        candidate, reviewer(coverage_complete=False, coverage_issues=["遗漏另一项任务"])
    )
    assert not result.safe_to_deliver


def test_invalid_conclusion_selection_is_blocked(candidate):
    result, _ = generate(candidate, reviewer(conclusion_ids=["C0001"]))
    assert "invalid_conclusion_selection" in result.issues


def test_oversized_source_is_not_silently_truncated():
    call = Mock()
    with pytest.raises(SummaryReviewRequired):
        generate_evidence_summary(SOURCE, call, max_source_chars=1)
    call.assert_not_called()


def test_error_message_does_not_leak_private_source():
    assert (
        str(SummaryReviewRequired())
        == "Summary requires review; automatic delivery blocked"
    )


def test_pipeline_gate_prevents_automatic_delivery(monkeypatch, candidate):
    audit, _ = generate(candidate, reviewer("needs_review"))
    monkeypatch.setattr(
        celery_worker,
        "settings",
        celery_worker.settings.model_copy(update={"summary_evidence_enabled": True}),
    )
    monkeypatch.setattr(
        celery_worker, "generate_evidence_summary", lambda *a, **k: audit
    )
    monkeypatch.setattr(celery_worker, "LLMObservability", lambda **kwargs: Mock())
    monkeypatch.setattr(celery_worker, "LLMService", lambda **kwargs: Mock())
    monkeypatch.setattr(
        celery_worker.analytics, "is_feature_enabled", lambda *a, **k: False
    )
    store = Mock()
    send = Mock()
    monkeypatch.setattr(celery_worker.file_service, "store_summary", store)
    monkeypatch.setattr(celery_worker, "send_meeting_documents", send)
    with pytest.raises(SummaryReviewRequired):
        celery_worker.summarize_v2_task.run(
            {
                "user_sub": "test",
                "tenant_id": "test-tenant",
                "content": SOURCE,
                "received_at": "2026-09-28T10:00:00Z",
            }
        )
    store.assert_not_called()
    send.assert_not_called()
    assert SummaryReviewRequired in celery_worker.summarize_v2_task.dont_autoretry_for


def wire(candidate):
    return draft_claim(Claim.model_validate(candidate)).model_dump()


def extraction(*candidates):
    return json.dumps({"claims": [wire(c) for c in candidates]})


def repair(candidate, claim_id="C0001"):
    return json.dumps(
        {
            "replacements": [
                {
                    "claim_id": claim_id,
                    "reason": "按原文纠正",
                    "claims": [wire(candidate)],
                }
            ],
            "additions": [],
        }
    )


def test_source_quotes_are_resolved_by_program_not_retyped_by_model(candidate):
    draft = DraftClaim.model_validate(wire(candidate))
    turns = {t.id: t for t in source_turns(SOURCE)}
    claim = materialize(draft, turns)
    assert claim.owner_sources[0].quote == turns["T0001"].text
    draft.source_ids = ["T9999"]
    assert "unknown_source_turn" in check_claim(materialize(draft, turns), turns)


def test_national_day_phrase_is_not_converted_in_task_or_timing(candidate):
    source = SOURCE.replace("预计下周完成", "月底就是十一之前完成")
    candidate["sources"][0]["quote"] = "小王整理验收清单"
    candidate["text"] = "2026-10-11 前整理验收清单"
    candidate["timing"] = {"kind": "unspecified", "text": "", "sources": []}
    assert "calendar_date_not_in_source" in errors(candidate, source)
    candidate["text"] = "整理验收清单"
    candidate["timing"] = {
        "kind": "deadline",
        "text": "十一之前",
        "sources": [{"turn_id": "T0001", "quote": "月底就是十一之前完成"}],
    }
    assert errors(candidate, source) == []
    result, _ = generate(candidate, source=source)
    assert "十一之前" in result.markdown
    assert "10-11" not in result.markdown


def test_reconciliation_preserves_estimate_before_first_review(candidate):
    mistaken = deepcopy(candidate)
    mistaken["timing"]["kind"] = "deadline"
    call = Mock(
        side_effect=[
            extraction(mistaken),
            extraction(candidate),
            json.dumps(reviewer()),
        ]
    )
    result = generate_evidence_summary(SOURCE, call)
    assert result.safe_to_deliver
    assert len(result.rounds) == 1
    assert "截止" not in result.markdown
    assert [entry.kwargs["name"] for entry in call.call_args_list] == [
        "evidence-extract-1",
        "evidence-reconcile",
        "evidence-review-0",
    ]


def test_failed_revision_is_repaired_then_independently_reviewed(candidate):
    mistaken = deepcopy(candidate)
    mistaken["timing"]["kind"] = "deadline"
    call = Mock(
        side_effect=[
            extraction(mistaken),
            extraction(mistaken),
            json.dumps(reviewer()),
            repair(candidate),
            json.dumps(reviewer()),
        ]
    )
    result = generate_evidence_summary(SOURCE, call)
    assert result.safe_to_deliver
    assert len(result.rounds) == 2
    assert result.rounds[0].issues
    assert not result.rounds[1].issues
    repair_input = call.call_args_list[3].args[1]
    assert "qualified_time_promoted_to_deadline" in repair_input
    assert "好的。" in repair_input


def test_repair_stops_at_budget_and_keeps_gate_closed(candidate):
    call = Mock(
        side_effect=[
            extraction(candidate),
            extraction(candidate),
            json.dumps(reviewer("needs_review")),
            repair(candidate),
            json.dumps(reviewer("needs_review")),
        ]
    )
    result = generate_evidence_summary(SOURCE, call)
    assert not result.safe_to_deliver
    assert len(result.rounds) == 2
    assert call.call_count == 5


def test_corrected_old_plan_is_not_reintroduced_by_rendering(candidate):
    source = SOURCE.replace("好的。", "改为李明收集反馈，小王不用整理清单了。")
    corrected = deepcopy(candidate)
    corrected.update(text="收集反馈", owner="李明", owner_display="李明")
    corrected["sources"] = corrected["owner_sources"] = [
        {"turn_id": "T0002", "quote": "改为李明收集反馈，小王不用整理清单了。"}
    ]
    corrected["timing"] = {"kind": "unspecified", "text": "", "sources": []}
    call = Mock(
        side_effect=[
            extraction(candidate),
            extraction(corrected),
            json.dumps(reviewer()),
        ]
    )
    result = generate_evidence_summary(source, call)
    assert result.safe_to_deliver
    assert "收集反馈" in result.markdown
    assert "整理验收清单" not in result.markdown


def test_uncertain_proposal_remains_pending_not_confirmed_action(candidate):
    candidate["kind"] = "uncertainty"
    candidate["status"] = "proposed"
    candidate["text"] = "是否整理验收清单尚未确定。"
    result, _ = generate(candidate)
    assert result.safe_to_deliver
    assert "是否整理验收清单尚未确定" in result.markdown
    assert "- [ ]" not in result.markdown


def test_audit_repairs_cannot_silently_drop_important_coverage(candidate):
    call = Mock(
        side_effect=[
            extraction(candidate),
            extraction(candidate),
            json.dumps(reviewer("needs_review")),
            json.dumps({"replacements": [], "additions": []}),
        ]
    )
    with pytest.raises(SummaryReviewRequired):
        generate_evidence_summary(SOURCE, call)


@pytest.mark.parametrize("status", ["proposed", "disputed", "reported"])
def test_unconfirmed_actions_are_pending_never_active_checkboxes(candidate, status):
    candidate["status"] = status
    result, _ = generate(candidate)
    assert result.safe_to_deliver
    assert "未定案：整理验收清单" in result.markdown
    assert "- [ ]" not in result.markdown


def test_explicit_waiting_condition_is_not_mistaken_for_rejected_fixed_date(candidate):
    source = SOURCE.replace("预计下周完成", "等大会结束再推进").replace(
        "好的。", "好的，需要等大会结束。"
    )
    candidate["sources"][0]["quote"] = "小王整理验收清单，等大会结束再推进。"
    candidate["timing"] = {
        "kind": "conditional",
        "text": "等大会结束再推进",
        "sources": [{"turn_id": "T0001", "quote": "等大会结束再推进"}],
    }
    result, _ = generate(candidate, source=source)
    assert result.safe_to_deliver
    assert "时间条件：等大会结束再推进" in result.markdown


@pytest.mark.parametrize("raw", ["九月十九号", "9月19号", "9月19日"])
def test_explicit_date_numerals_and_day_suffix_are_equivalent(candidate, raw):
    source = SOURCE.replace("预计下周完成", f"{raw}完成")
    candidate["text"] = "9月19日整理验收清单"
    candidate["sources"][0]["quote"] = f"小王整理验收清单，{raw}完成。"
    candidate["timing"] = {"kind": "unspecified", "text": "", "sources": []}
    assert errors(candidate, source) == []


def test_neighboring_delay_is_not_a_hard_error_for_an_unrelated_topic(candidate):
    source = SOURCE.replace("好的。", "好的，另一个项目需要等供应商到场。")
    result, call = generate(candidate, source=source)
    assert result.safe_to_deliver
    assert "近邻可能修改时间" in call.call_args.args[1]


def test_patch_keeps_unaffected_record_verbatim(candidate):
    turns = {t.id: t for t in source_turns(SOURCE)}
    claims = {
        "C0001": Claim.model_validate(candidate),
        "C0002": Claim.model_validate(candidate),
    }
    patch = Repair.model_validate_json(repair(candidate))
    result = _apply_repair(claims, patch, turns, ["C0001"])
    assert result["C0002"] is claims["C0002"]
    with pytest.raises(SummaryReviewRequired):
        _apply_repair(claims, patch, turns, ["C0002"])


def test_resume_refuses_changed_source_without_network(candidate):
    previous, _ = generate(candidate)
    call = Mock()
    with pytest.raises(SummaryReviewRequired):
        revise_evidence_summary(SOURCE + "changed", previous, call)
    call.assert_not_called()


def test_resume_repairs_and_reviews_full_source(candidate):
    previous, _ = generate(candidate, reviewer("needs_review"))
    call = Mock(side_effect=[repair(candidate), json.dumps(reviewer())])
    result = revise_evidence_summary(SOURCE, previous, call)
    assert result.safe_to_deliver
    assert call.call_args.kwargs["name"] == "evidence-review-resumed"
    assert "完整原文" in call.call_args.args[1]


def test_explicitly_completed_work_cannot_be_a_future_action(candidate):
    candidate["text"] = "发送验收清单（已在会中完成）"
    assert "completed_action_not_future" in errors(candidate)
