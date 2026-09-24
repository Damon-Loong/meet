"""Temporary audio chunks and transcript timeline helpers for long recordings."""

import copy
import re
import subprocess
from pathlib import Path

CHUNK_SECONDS = 80 * 60
OVERLAP_SECONDS = 10
SPEAKER_PREFIX = re.compile(r"^\s*\[([A-Za-z]\d{1,3})\]\s*")
GENERIC_SPEAKER = re.compile(r"^(?:S\d{1,3}|SPEAKER_?\d{1,3})$", re.IGNORECASE)


def chunk_windows(duration: float) -> list[tuple[float, float]]:
    """Return (start, end) windows, each at most 80 minutes long."""
    if duration <= 0:
        raise ValueError("Audio duration must be positive")
    windows = []
    start = 0.0
    while start < duration:
        end = min(start + CHUNK_SECONDS, duration)
        windows.append((start, end))
        if end == duration:
            break
        start = end - OVERLAP_SECONDS
    return windows


def extract_chunk(source: Path, target: Path, start: float, end: float) -> None:
    """Cut an audio window without changing its codec, channels, or quality."""
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-ss", f"{start:.3f}", "-i", str(source),
            "-t", f"{end - start:.3f}", "-map", "0:a:0", "-vn",
            "-c:a", "copy",
            "-y", str(target),
        ],
        check=True,
    )


def shift_timestamps(transcript: dict, offset: float) -> dict:
    """Shift segment and word times to the original recording's timeline."""
    result = copy.deepcopy(transcript)

    def shift(item: dict) -> None:
        for key in ("start", "end"):
            if item.get(key) is not None:
                item[key] += offset

    for segment in result.get("segments") or []:
        shift(segment)
        for word in segment.get("words") or []:
            shift(word)
    for word in result.get("word_segments") or []:
        shift(word)
    return result


def namespace_unmatched(transcript: dict, chunk_index: int) -> dict:
    """Prevent unmatched S01 labels in different chunks looking like one person."""
    result = copy.deepcopy(transcript)
    for segment in result.get("segments") or []:
        text = segment.get("text") or ""
        match = SPEAKER_PREFIX.match(text)
        raw_speaker = segment.get("speaker")
        label = match.group(1) if match else raw_speaker
        if label and (not raw_speaker or GENERIC_SPEAKER.fullmatch(raw_speaker)):
            segment["speaker"] = f"第{chunk_index + 1}段发言人{label}"
            if match:
                segment["text"] = text[match.end():]
    return result


def merge_transcripts(chunks: list[dict], windows: list[tuple[float, float]]) -> dict:
    """Merge global-timestamp chunks, removing matching text in overlap areas."""
    segments: list[dict] = []
    words: list[dict] = []
    for index, chunk in enumerate(chunks):
        overlap_start = windows[index][0]
        previous_end = windows[index - 1][1] if index else 0.0
        for segment in chunk.get("segments") or []:
            if index and segment.get("start") is not None and segment["start"] < previous_end:
                normalized = re.sub(r"[\W_]+", "", segment.get("text") or "").casefold()
                duplicate = next(
                    (
                        old for old in segments
                        if old.get("end") is not None and old["end"] > overlap_start
                        and old.get("speaker") == segment.get("speaker")
                        and re.sub(r"[\W_]+", "", old.get("text") or "").casefold() == normalized
                        and normalized
                    ),
                    None,
                )
                if duplicate is not None:
                    continue
            segments.append(segment)
        for word in chunk.get("word_segments") or []:
            if index and word.get("start") is not None and word["start"] < previous_end:
                if any(
                    old.get("word") == word.get("word")
                    and old.get("start") is not None
                    and abs(old["start"] - word["start"]) < 0.3
                    for old in words
                ):
                    continue
            words.append(word)
    segments.sort(key=lambda segment: segment.get("start") or 0)
    words.sort(key=lambda word: word.get("start") or 0)
    return {"segments": segments, "word_segments": words}
