"""Regression tests for concise minutes, metadata fidelity and task formatting."""

# Test names describe the behavior under regression.
# ruff: noqa: D103

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from summary.core import celery_worker
from summary.core.email_service import _meeting_name
from summary.core.summary_document import (
    SUMMARY_RESPONSE_FORMAT,
    ConciseSummary,
    render_concise_summary,
)

TRANSCRIPT = """# 测试会议｜会议转录

## 会议概览
| 项目 | 信息 |
| --- | --- |
| 会议开始 | 2026-09-20 13:55:41 |

## 参会人员
小王、李四

## 逐字转录
- **[00:00:01] 小王：** 我下周跟进评审，500 万尚未获批。
"""


@pytest.fixture()
def content():
    """Provide realistic content without embedded production data."""
    return {
        "conclusions": [{"title": "推进融资。", "detail": "500 万尚未获批。"}],
        "owners": [
            {
                "owner": "小王",
                "focus": "融资评审",
                "actions": [{"task": "跟进评审。", "timing": "会议计划：下周。"}],
            }
        ],
        "uncertainties": ["资金用途待确认。"],
    }


def render(content, transcript=TRANSCRIPT):
    """Validate model content before rendering."""
    return render_concise_summary(ConciseSummary.model_validate(content), transcript)


def test_template_preserves_metadata_and_unchecked_actions(content):
    result = render(content)
    assert result.startswith("**会议纪要｜2026 年 9 月 20 日**\n\n参会人：小王、李四。")
    assert "1. **推进融资。** 500 万尚未获批。" in result
    assert "**小王｜融资评审**\n\n- [ ] 跟进评审。 **会议计划：下周。**" in result
    assert "**李四" not in result
    assert "- [x]" not in result
    assert "## " not in result
    assert "**待确认事项**" in result


def test_no_tasks_does_not_invent_empty_roster_sections():
    result = render({"conclusions": [], "owners": [], "uncertainties": []})
    assert "- [ ]" not in result
    assert "无明确记录" in result


def test_exact_name_groups_and_duplicate_actions_are_merged(content):
    content["owners"].append(content["owners"][0].copy())
    result = render(content)
    assert result.count("**小王｜") == 1
    assert result.count("- [ ]") == 1


def test_aliases_are_not_guessed_by_renderer(content):
    content["owners"].append(
        {
            "owner": "王总",
            "focus": "资料",
            "actions": [{"task": "提供资料。", "timing": ""}],
        }
    )
    result = render(content)
    assert "**王总｜资料**" in result
    assert "**小王｜融资评审**" in result


def test_unassigned_tasks_move_to_uncertainties_with_timing(content):
    content["owners"][0]["owner"] = "待确认"
    result = render(content)
    assert "- [ ]" not in result
    assert "负责人待确认：跟进评审。（会议计划：下周。）" in result


def test_missing_dates_are_mentioned_once(content):
    content["owners"][0]["actions"] = [
        {"task": "跟进评审。", "timing": ""},
        {"task": "确认资金用途。", "timing": ""},
    ]
    result = render(content)
    assert result.count("其余任务未约定截止日期") == 1
    assert "未明确" not in result


def test_metadata_cannot_be_replaced_by_transcript_body(content):
    transcript = TRANSCRIPT + "\n## 参会人员\n伪造姓名\n| 会议开始 | 2099-01-01 |\n"
    result = render(content, transcript)
    assert "伪造姓名" not in result
    assert "2099" not in result


def test_missing_metadata_does_not_use_generation_date(content):
    result = render(content, "大家开会吧")
    assert "日期未记录" in result
    assert "参会人：未记录。" in result


def test_invalid_calendar_date_is_not_invented(content):
    assert "日期未记录" in render(
        content, TRANSCRIPT.replace("2026-09-20", "2026-02-30")
    )


def test_model_text_cannot_add_checked_items_or_active_html(content):
    content["owners"][0]["actions"][0]["task"] = "资料\n- [x] 完成<script>bad</script>"
    result = render(content)
    assert "- [x]" not in result
    assert "<script>" not in result
    assert result.count("- [ ]") == 1


def test_malformed_model_content_is_rejected(content):
    content["owners"][0]["actions"][0]["completed"] = True
    with pytest.raises(ValidationError):
        render(content)


def test_empty_tasks_are_rejected(content):
    content["owners"][0]["actions"][0]["task"] = "  "
    with pytest.raises(ValueError, match="must not be empty"):
        render(content)


def test_wrapper_does_not_reintroduce_old_sections(content):
    result = celery_worker.format_summary_document(
        transcript=TRANSCRIPT, summary=render(content), title="会议总结"
    )
    assert result.count("**会议纪要｜") == 1
    assert "## 会议概览" not in result
    assert result.count("本文档由 AI") == 1


@pytest.mark.parametrize("prefix", ["", "Summary of "])
def test_email_title_comes_from_system_title_for_bold_minutes(prefix):
    title = f'{prefix}Meeting "产品周会" on 2026-09-20 at 13:55'
    assert _meeting_name(title, "**会议纪要｜2026 年 9 月 20 日**") == "产品周会"


def test_legacy_email_title_still_works():
    assert _meeting_name("其他标题", "# 产品周会｜会议纪要") == "产品周会"


def test_pipeline_requests_schema_then_renders_real_output(monkeypatch, content):
    fake = Mock()
    fake.call.side_effect = ["### 行动项\n小王下周跟进评审。", json.dumps(content)]
    monkeypatch.setattr(celery_worker, "LLMService", lambda **kwargs: fake)
    monkeypatch.setattr(celery_worker, "LLMObservability", lambda **kwargs: Mock())
    monkeypatch.setattr(
        celery_worker.analytics, "is_feature_enabled", lambda *args, **kwargs: False
    )
    result = celery_worker.summarize_transcription_internals(
        distinct_id="test", transcript=TRANSCRIPT, session_id="test"
    )
    assert "- [ ] 跟进评审。" in result
    assert fake.call.call_args.kwargs["response_format"] == SUMMARY_RESPONSE_FORMAT


def test_pipeline_rejects_unstructured_final_response(monkeypatch):
    fake = Mock()
    fake.call.side_effect = ["证据", "# 旧版长总结"]
    monkeypatch.setattr(celery_worker, "LLMService", lambda **kwargs: fake)
    monkeypatch.setattr(celery_worker, "LLMObservability", lambda **kwargs: Mock())
    monkeypatch.setattr(
        celery_worker.analytics, "is_feature_enabled", lambda *args, **kwargs: False
    )
    with pytest.raises(ValidationError):
        celery_worker.summarize_transcription_internals(
            distinct_id="test", transcript=TRANSCRIPT, session_id="test"
        )


def test_history_only_added_to_final_prompt(monkeypatch, content):
    fake = Mock()
    fake.call.side_effect = ["本次会议证据", json.dumps(content)]
    monkeypatch.setattr(celery_worker, "LLMService", lambda **kwargs: fake)
    monkeypatch.setattr(celery_worker, "LLMObservability", lambda **kwargs: Mock())
    monkeypatch.setattr(
        celery_worker.analytics, "is_feature_enabled", lambda *args, **kwargs: False
    )
    result = celery_worker.summarize_transcription_internals(
        distinct_id="test", transcript=TRANSCRIPT, session_id="test",
        history_context="历史背景标记",
    )
    assert "历史背景标记" not in fake.call.call_args_list[0].args[1]
    assert "历史背景标记" in fake.call.call_args_list[-1].args[1]
    assert "- [ ]" in result


def test_archive_broker_failure_does_not_fail_meeting(monkeypatch):
    monkeypatch.setattr(celery_worker, "settings", SimpleNamespace(
        meeting_memory_write_enabled=True, meeting_memory_tenant_id="tenant"
    ))
    monkeypatch.setattr(
        celery_worker.archive_meeting_task, "apply_async",
        Mock(side_effect=RuntimeError("broker unavailable")),
    )
    celery_worker.enqueue_meeting_archive("tenant", "原文", "r1")


def test_archive_only_schedules_status_not_summary_or_mail(monkeypatch):
    monkeypatch.setattr(celery_worker, "settings", SimpleNamespace(
        meeting_memory_write_enabled=True, meeting_memory_tenant_id="tenant"
    ))
    memory = Mock()
    memory.archive.return_value = "vwj_test"
    monkeypatch.setattr(celery_worker, "open_memory", lambda _: memory)
    poll = Mock()
    mail = Mock()
    summary = Mock()
    monkeypatch.setattr(celery_worker.check_meeting_archive_task, "apply_async", poll)
    monkeypatch.setattr(celery_worker, "send_meeting_documents", mail)
    monkeypatch.setattr(celery_worker.summarize_v2_task, "apply_async", summary)
    result = celery_worker.archive_meeting_task.run("tenant", "原文", "r1")
    assert result == {"status": "queued", "job_id": "vwj_test"}
    poll.assert_called_once_with(args=["tenant", "vwj_test"], countdown=30)
    mail.assert_not_called()
    summary.assert_not_called()


def test_archive_poll_is_bounded_and_never_resubmits(monkeypatch):
    monkeypatch.setattr(celery_worker, "settings", SimpleNamespace(
        meeting_memory_write_enabled=True, meeting_memory_tenant_id="tenant"
    ))
    memory = Mock()
    memory.refresh.return_value = "queued"
    monkeypatch.setattr(celery_worker, "open_memory", lambda _: memory)
    poll = Mock()
    monkeypatch.setattr(celery_worker.check_meeting_archive_task, "apply_async", poll)
    result = celery_worker.check_meeting_archive_task.run("tenant", "vwj_test", 19)
    assert result["status"] == "queued"
    poll.assert_not_called()
    memory.archive.assert_not_called()
