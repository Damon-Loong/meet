"""Offline regressions for person identity, evidence, updates and safe delivery."""

# ruff: noqa: D103
import json
from unittest.mock import Mock

import pytest

from summary.core.personal_memory import PersonalMemory, personal_context

ROSTER = [{"identity": "account-a", "name": "小王"}]
LINE = "- **[00:01:00] 小王：** 我负责整理设备说明，周五交付。"


def transcript(line=LINE, date="2026-09-20", names="小王"):
    return (
        f"| 会议开始 | {date} 10:00:00 |\n## 参会人员\n\n{names}\n\n## 逐字转录\n{line}"
    )


@pytest.fixture
def memory(tmp_path):
    result = PersonalMemory(tmp_path / "state.sqlite3", "team-a")
    result.register(ROSTER)
    return result


def proposal(memory, **overrides):
    return {
        "person_id": memory.people()[0]["id"],
        "item_id": "",
        "kind": "task",
        "text": "整理设备说明",
        "status": "pending",
        "deadline": "周五",
        "quote": LINE,
        **overrides,
    }


def ingest(memory, facts=None, source="one", text=None):
    call = Mock(
        return_value=json.dumps(
            {"facts": facts if facts is not None else [proposal(memory)]},
            ensure_ascii=False,
        )
    )
    result = memory.ingest(text or transcript(), source, ROSTER, call)
    return result, call


def test_create_read_and_replay(memory):
    assert ingest(memory)[0] == {"status": "completed", "records": 1}
    assert ingest(memory)[0]["status"] == "already_processed"
    assert len(memory.items()) == 1
    context = memory.context(ROSTER, transcript(date="2026-09-21"), "next")
    assert "整理设备说明" in context and "周五" in context and LINE in context


def test_no_mention_does_not_finish(memory):
    ingest(memory)
    ingest(memory, [], "two", transcript("今天讨论其他问题", "2026-09-21"))
    assert memory.items()[0]["status"] == "pending"


def test_explicit_completion_links_existing_task(memory):
    ingest(memory)
    item = memory.items()[0]
    line = "- **[00:02:00] 小王：** 设备说明已经完成并交付。"
    fact = proposal(
        memory, item_id=item["item"], quote=line, deadline="", status="completed"
    )
    ingest(memory, [fact], "two", transcript(line, "2026-09-21"))
    assert memory.items()[0]["status"] == "completed"
    assert len(memory.audit(item["item"])) == 2


@pytest.mark.parametrize(
    "line",
    [
        "还没有完成",
        "计划明天完成",
        "差一点做完",
        "正在看",
        "已经完成了吗？",
        "周五交付",
    ],
)
def test_uncertain_completion_requires_confirmation(memory, line):
    quote = "- **[00:00:01] 小王：** " + line
    ingest(
        memory,
        [proposal(memory, quote=quote, status="completed", deadline="")],
        text=transcript(quote),
    )
    assert memory.items()[0]["status"] == "needs_confirmation"


def test_same_name_accounts_never_merge(memory):
    memory.register([{"identity": "account-b", "name": "小王"}])
    assert len(memory.people()) == 2
    assert memory.resolve([], transcript()) == []
    assert len(memory.resolve(ROSTER, transcript())) == 1


def test_alias_and_account_mapping_is_explicit(memory):
    person = memory.people()[0]["id"]
    memory.add_person("王明", ["小王"], "second-account", person)
    assert memory.resolve([], transcript())[0]["id"] == person
    memory.add_person("王明", [], person=person)
    assert memory.resolve([], transcript()) == []
    with pytest.raises(ValueError):
        memory.add_person("别人", [], "second-account")


def test_ambiguous_person_is_not_assigned(memory):
    ingest(memory, [proposal(memory, person_id="unknown")])
    assert memory.items()[0]["person"] == ""
    assert memory.items()[0]["status"] == "needs_confirmation"


def test_quote_without_owner_is_unassigned(memory):
    line = "- **[00:00:01] 发言人 01：** 我完成了设备说明。"
    ingest(
        memory,
        [proposal(memory, quote=line, deadline="", status="completed")],
        text=transcript(line),
    )
    assert memory.items()[0]["person"] == ""


@pytest.mark.parametrize("quote", ["捏造的证据", "我负责整理设备说明，周五交付。"])
def test_fabricated_or_partial_quote_rejected_atomically(memory, quote):
    with pytest.raises(ValueError):
        ingest(memory, [proposal(memory), proposal(memory, quote=quote)])
    assert not memory.items()


def test_future_same_day_and_self_excluded(memory):
    ingest(memory)
    assert memory.context(ROSTER, transcript(date="2026-09-19"), "two") == ""
    assert memory.context(ROSTER, transcript(), "two") == ""
    assert memory.context(ROSTER, transcript(date="2026-09-21"), "one") == ""


def test_tenant_isolation(memory):
    ingest(memory)
    foreign = PersonalMemory(memory.path, "team-b")
    assert not foreign.items() and not foreign.people()
    item = memory.items()[0]
    assert not foreign.audit(item["item"])
    with pytest.raises(KeyError):
        foreign.correct(
            item["item"],
            revision=item["seq"],
            person=item["person"],
            text="x",
            status="pending",
            deadline="",
            reason="x",
        )


def test_human_correction_is_audited_and_not_overwritten(memory):
    ingest(memory)
    old = memory.items()[0]
    memory.correct(
        old["item"],
        revision=old["seq"],
        person=old["person"],
        text=old["text"],
        status="completed",
        deadline="",
        reason="负责人确认完成",
    )
    assert memory.items()[0]["status"] == "completed"
    with pytest.raises(ValueError):
        memory.correct(
            old["item"],
            revision=old["seq"],
            person=old["person"],
            text="x",
            status="pending",
            deadline="",
            reason="stale",
        )
    ingest(
        memory,
        [proposal(memory, item_id=old["item"])],
        "two",
        transcript(date="2026-09-21"),
    )
    records = memory.items()
    assert next(i for i in records if i["item"] == old["item"])["status"] == "completed"
    assert any(i["status"] == "needs_confirmation" for i in records)
    assert memory.audit(old["item"])[-1]["reason"] == "负责人确认完成"


def test_out_of_order_ingestion_preserves_newer_state(memory):
    ingest(memory)
    item = memory.items()[0]
    quote = "- **[00:00:01] 小王：** 设备说明已完成。"
    ingest(
        memory,
        [
            proposal(
                memory,
                item_id=item["item"],
                quote=quote,
                deadline="",
                status="completed",
            )
        ],
        "later",
        transcript(quote, "2026-09-23"),
    )
    ingest(
        memory,
        [proposal(memory, item_id=item["item"])],
        "middle",
        transcript(date="2026-09-22"),
    )
    assert memory.items()[0]["status"] == "completed"


def test_edited_source_needs_reconciliation(memory):
    ingest(memory)
    with pytest.raises(ValueError):
        ingest(memory, text=transcript(LINE + "变化"))
    assert len(memory.items()) == 1


def test_deadline_and_responsibility_not_inferred(memory):
    ingest(
        memory,
        [
            proposal(
                memory, kind="responsibility", status="active", deadline="2026-09-30"
            )
        ],
    )
    item = memory.items()[0]
    assert item["deadline"] == "" and item["status"] == "needs_confirmation"


def test_disabled_or_failure_does_not_block_summary(tmp_path):
    settings = Mock(personal_memory_enabled=False, meeting_memory_tenant_id="team-a")
    assert personal_context(settings, "team-a", [], "bad", "x") == ""
    settings.personal_memory_enabled = True
    settings.meeting_memory_state_file = tmp_path
    assert personal_context(settings, "team-a", [], transcript(), "x") == ""
    assert personal_context(settings, "team-b", [], transcript(), "x") == ""


def test_background_failure_does_not_retry_mail(monkeypatch):
    from summary.core import celery_worker as worker  # noqa: PLC0415

    monkeypatch.setattr(
        worker,
        "settings",
        worker.settings.model_copy(
            update={
                "personal_memory_enabled": True,
                "meeting_memory_tenant_id": "team-a",
            }
        ),
    )
    queue = Mock(side_effect=RuntimeError("unavailable"))
    monkeypatch.setattr(worker.update_personal_memory_task, "apply_async", queue)
    worker.enqueue_personal_memory("team-a", "text", "source", [])
    queue.assert_called_once()


def test_two_meetings_same_day_can_recall_prior(memory):
    ingest(memory)
    later = transcript().replace("10:00:00", "14:00:00")
    assert "整理设备说明" in memory.context(ROSTER, later, "afternoon")
    earlier = transcript().replace("10:00:00", "09:00:00")
    assert not memory.context(ROSTER, earlier, "morning")
    unknown_time = transcript().replace(" 10:00:00", "")
    assert not memory.context(ROSTER, unknown_time, "unknown-time")


def test_later_manual_completion_not_leaked_into_historical_preview(memory):
    ingest(memory)
    item = memory.items()[0]
    memory.correct(
        item["item"],
        revision=item["seq"],
        person=item["person"],
        text=item["text"],
        status="completed",
        deadline="",
        reason="今天确认完成",
    )
    past = memory.items(before="2026-09-21 00:00:00")
    assert past[0]["status"] == "pending"


def test_explicit_merge_keeps_task_and_identity_audit(memory):
    ingest(memory)
    source = memory.people()[0]["id"]
    target = memory.add_person("王明", [], "account-b")
    memory.merge(source, target, "本人确认两账号相同")
    assert len(memory.people()) == 1
    assert set(memory.people()[0]["accounts"]) == {"account-a", "account-b"}
    item = memory.items()[0]
    assert item["person"] == target
    assert len(memory.audit(item["item"])) == 2
    assert memory.resolve(ROSTER, transcript())[0]["id"] == target
    with pytest.raises(ValueError):
        memory.merge(source, target, "重复操作")


def test_progress_keeps_original_deadline_and_its_date(memory):
    ingest(memory)
    old = memory.items()[0]
    quote = "- **[00:00:01] 小王：** 设备说明正在整理。"
    ingest(
        memory,
        [
            proposal(
                memory,
                item_id=old["item"],
                quote=quote,
                deadline="",
                status="in_progress",
            )
        ],
        "two",
        transcript(quote, "2026-09-21"),
    )
    item = memory.items()[0]
    assert item["deadline"] == "周五"
    assert item["deadline_source"] == "one"
    assert item["deadline_date"].startswith("2026-09-20")


def test_duplicate_concurrent_extraction_is_idempotent(memory):
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415
    from threading import Barrier  # noqa: PLC0415

    barrier = Barrier(2)

    def call(*args, **kwargs):
        barrier.wait(timeout=5)
        return json.dumps({"facts": [proposal(memory)]})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: memory.ingest(transcript(), "same", ROSTER, call), range(2)
            )
        )
    assert {r["status"] for r in results} == {"completed", "already_processed"}
    assert len(memory.items()) == 1


def test_summary_reads_personal_history_then_enqueues_after_mail(monkeypatch):
    from summary.core import celery_worker as worker  # noqa: PLC0415

    order = []
    monkeypatch.setattr(worker, "optional_history", lambda *_: "团队历史")
    monkeypatch.setattr(worker, "personal_context", lambda *_: "个人历史")
    generate = Mock(return_value="**会议纪要｜测试**")
    monkeypatch.setattr(worker, "summarize_transcription_internals", generate)
    monkeypatch.setattr(
        worker.file_service, "store_summary", lambda **_: order.append("store")
    )
    monkeypatch.setattr(
        worker.file_service,
        "get_summary_signed_url",
        lambda _: "https://example.com/summary",
    )
    monkeypatch.setattr(
        worker, "send_meeting_documents", lambda **_: order.append("mail")
    )
    monkeypatch.setattr(worker, "_should_push_to_docs", lambda _: False)
    monkeypatch.setattr(worker.call_webhook_v2_task, "apply_async", Mock())
    monkeypatch.setattr(worker.metadata_manager, "capture", Mock())
    queue = Mock(side_effect=lambda *_: order.append("personal"))
    monkeypatch.setattr(worker, "enqueue_personal_memory", queue)
    task = worker.summarize_v2_task
    task.push_request(id="00000000-0000-0000-0000-000000000001")
    try:
        task.run(
            {
                "tenant_id": "test-tenant",
                "user_sub": "test",
                "content": transcript(),
                "received_at": "2026-09-29T00:00:00Z",
                "participants": ROSTER,
                "recipient_emails": ["test@example.com"],
                "push_to_docs_config": {
                    "user_email": "test@example.com",
                    "title": "测试会议",
                },
            }
        )
    finally:
        task.pop_request()
    assert generate.call_args.kwargs["history_context"] == "团队历史个人历史"
    assert order == ["store", "mail", "personal"]
    assert queue.call_args.args[-1] == ROSTER
