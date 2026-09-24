"""Long-audio chunk planning and transcript reconstruction."""

from pathlib import Path

from summary.core.long_audio import (
    CHUNK_SECONDS,
    OVERLAP_SECONDS,
    chunk_windows,
    extract_chunk,
    merge_transcripts,
    namespace_unmatched,
    shift_timestamps,
)


def test_extract_chunk_copies_audio_stream_without_reencoding(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))

    monkeypatch.setattr("summary.core.long_audio.subprocess.run", fake_run)
    extract_chunk(Path("source.ogg"), Path("chunk.ogg"), 4790, 5228.5)

    command, kwargs = calls[0]
    assert command[command.index("-c:a") + 1] == "copy"
    assert command[command.index("-ss") + 1] == "4790.000"
    assert command[command.index("-t") + 1] == "438.500"
    assert not any(option in command for option in ("-ac", "-ar", "-b:a"))
    assert kwargs["check"] is True


def test_short_audio_stays_whole():
    assert chunk_windows(CHUNK_SECONDS) == [(0.0, CHUNK_SECONDS)]


def test_long_audio_uses_eighty_minute_windows_with_overlap():
    windows = chunk_windows(CHUNK_SECONDS + 120)
    assert windows == [
        (0.0, CHUNK_SECONDS),
        (CHUNK_SECONDS - OVERLAP_SECONDS, CHUNK_SECONDS + 120),
    ]
    assert all(end - start <= CHUNK_SECONDS for start, end in windows)


def test_shift_nested_word_timestamps_without_mutating_input():
    original = {
        "segments": [{"start": 1.0, "end": 2.0, "words": [{"start": 1.2, "end": 1.4}]}],
        "word_segments": [{"start": 1.2, "end": 1.4}],
    }
    shifted = shift_timestamps(original, 4790)
    assert shifted["segments"][0]["start"] == 4791
    assert shifted["segments"][0]["words"][0]["end"] == 4791.4
    assert shifted["word_segments"][0]["start"] == 4791.2
    assert original["segments"][0]["start"] == 1.0


def test_merge_deduplicates_same_overlap_text_but_keeps_distinct_speech():
    first = {"segments": [
        {"start": 4794.0, "end": 4796.0, "speaker": "龙", "text": "好的。"},
    ]}
    second = {"segments": [
        {"start": 4794.2, "end": 4796.1, "speaker": "龙", "text": "好的"},
        {"start": 4797.0, "end": 4798.0, "speaker": "李", "text": "继续"},
    ]}
    merged = merge_transcripts(
        [first, second], [(0.0, 4800.0), (4790.0, 4900.0)]
    )
    assert [segment["text"] for segment in merged["segments"]] == ["好的。", "继续"]


def test_unmatched_speaker_labels_do_not_collide_across_chunks():
    transcript = {"segments": [{"start": 4801, "end": 4802, "speaker": None,
                                "text": "[S01]你好"}]}
    labeled = namespace_unmatched(transcript, 1)
    assert labeled["segments"][0]["speaker"] == "第2段发言人S01"
    assert labeled["segments"][0]["text"] == "你好"
