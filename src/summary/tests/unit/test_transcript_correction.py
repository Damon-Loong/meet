"""Constrained post-ASR terminology correction."""

# ruff: noqa: D103

import json
from unittest.mock import Mock

from summary.core.transcript_correction import correct_transcript_spelling

TRANSCRIPT = """# 测试会议｜会议转录

## 参会人员

Marsh、魏嘉

## 逐字转录

- **[00:14:49] Marsh：** 经销商卖给建福门店，下午再和魏佳确认。
- **[00:15:12] Marsh：** 金额是 500 万，时间是下周。
"""


def response(corrections):
    return json.dumps({"corrections": corrections}, ensure_ascii=False)


def test_applies_only_exact_line_scoped_canonical_replacements():
    call = Mock(
        return_value=response(
            [
                {"line": 9, "original": "建福", "replacement": "见福"},
                {"line": 9, "original": "魏佳", "replacement": "魏嘉"},
            ]
        )
    )
    result = correct_transcript_spelling(TRANSCRIPT, ("见福", "魏嘉"), call)
    assert "卖给见福门店，下午再和魏嘉确认" in result
    assert "金额是 500 万，时间是下周" in result
    assert "## 参会人员\n\nMarsh、魏嘉" in result
    assert result.endswith("\n")
    assert call.call_args.kwargs["response_format"]["type"] == "json_schema"


def test_rejects_rewriting_unknown_terms_and_nonexistent_source():
    call = Mock(
        return_value=response(
            [
                {"line": 9, "original": "建福", "replacement": "未知公司"},
                {"line": 9, "original": "不存在", "replacement": "见福"},
                {"line": 10, "original": "500", "replacement": "见福"},
                {"line": 3, "original": "参会人员", "replacement": "见福"},
            ]
        )
    )
    assert correct_transcript_spelling(TRANSCRIPT, ("见福",), call) == TRANSCRIPT


def test_model_failure_preserves_source_and_does_not_raise():
    call = Mock(side_effect=RuntimeError("temporary model failure"))
    assert correct_transcript_spelling(TRANSCRIPT, ("见福",), call) == TRANSCRIPT


def test_empty_vocabulary_or_no_utterances_skips_model():
    call = Mock()
    assert correct_transcript_spelling(TRANSCRIPT, (), call) == TRANSCRIPT
    assert (
        correct_transcript_spelling("# 只有标题\n", ("见福",), call) == "# 只有标题\n"
    )
    call.assert_not_called()


def test_chunks_long_transcript_without_rewriting_structure():
    transcript = "# 会\n\n## 逐字转录\n\n" + "\n".join(
        f"- **[00:00:{i:02d}] Marsh：** 第{i}行建福。" for i in range(1, 5)
    )
    call = Mock(
        side_effect=[
            response([{"line": 5, "original": "建福", "replacement": "见福"}]),
            response([{"line": 7, "original": "建福", "replacement": "见福"}]),
        ]
    )
    result = correct_transcript_spelling(transcript, ("见福",), call, max_chars=80)
    assert result.count("见福") == 2
    assert result.count("建福") == 2
    assert call.call_count == 2
