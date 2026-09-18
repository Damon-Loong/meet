"""Tests for professional meeting transcript formatting."""

from datetime import datetime, timezone
from types import SimpleNamespace

from summary.core.locales.zh import STRINGS
from summary.core.transcript_formatter import TranscriptFormatter


def test_formats_professional_transcript_with_metadata():
    formatter = TranscriptFormatter(STRINGS)
    recording = SimpleNamespace(
        started_at=datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 9, 18, 9, 5, 8, tzinfo=timezone.utc),
    )
    transcription = {
        "segments": [
            {"start": 1.2, "speaker": "S01", "text": " 大家好。 "},
            {"start": 65.9, "speaker": "张三", "text": "开始讨论。"},
        ]
    }
    metadata = {
        "participants": [
            {"participantId": "1", "name": "张三"},
            {"participantId": "2", "name": "李四"},
        ]
    }

    content = formatter.format(
        transcription,
        download_link="https://example.com/recording",
        title="产品周会",
        recording_metadata=recording,
        participant_metadata=metadata,
    )

    assert content.startswith("# 产品周会")
    assert "| 会议开始 | 2026-09-18 17:00:00 |" in content
    assert "| 会议结束 | 2026-09-18 17:05:08 |" in content
    assert "| 会议时长 | 5 分 8 秒 |" in content
    assert "张三、李四" in content
    assert "**[00:00:01] 发言人 01：** 大家好。" in content
    assert "**[00:01:05] 张三：** 开始讨论。" in content
    assert "Download your recording" not in content
    assert "https://example.com/recording" not in content


def test_falls_back_to_detected_speakers_without_metadata():
    formatter = TranscriptFormatter(STRINGS)
    content = formatter.format(
        {"segments": [{"start": 0, "speaker": "S02", "text": "你好"}]}
    )

    assert "发言人 02" in content
    assert "| 参会人数 | 1 人 |" in content


def test_parses_moss_speaker_prefix_and_uses_only_participant_name():
    formatter = TranscriptFormatter(STRINGS)
    content = formatter.format(
        {"segments": [{"start": 4, "speaker": None, "text": "[S01] 你好"}]},
        participant_metadata={"participants": [{"name": "张三"}]},
    )

    assert "**[00:00:04] 张三：** 你好" in content
    assert "[S01]" not in content


def test_filters_livekit_egress_participant_and_localizes_generated_title():
    formatter = TranscriptFormatter(STRINGS)
    content = formatter.format(
        {"segments": [{"start": 1, "text": "[S01] 测试"}]},
        title='Meeting "weekly-room" on 2026-09-18 at 19:11',
        participant_metadata={
            "participants": [
                {"identity": "user-1", "name": "Long"},
                {"identity": "EG_wAhCysJZMtKo", "name": "EG_wAhCysJZMtKo"},
            ]
        },
    )

    assert content.startswith("# weekly-room｜会议转录")
    assert "| 参会人数 | 1 人 |" in content
    assert "EG_wAhCysJZMtKo" not in content
    assert "**[00:00:01] Long：** 测试" in content
