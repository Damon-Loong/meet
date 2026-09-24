"""Match diarization speaker labels to meeting participants using VAD timelines."""

import json
import logging
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from typing import Any

from summary.core.config import get_settings

settings = get_settings()

logger = logging.getLogger(__name__)

MOSS_SPEAKER_PREFIX = re.compile(r"^\s*\[([A-Za-z]\d{1,3})\]\s*")
# LiveKit VAD state callbacks lag behind the corresponding recorded audio.
# Widen only the matching window; keep the stored timestamps unchanged.
VAD_START_TOLERANCE_SECONDS = 1.5
VAD_END_TOLERANCE_SECONDS = 0.25
ASSIGNMENT_MARGIN = 0.15


def _speaker_label(segment: dict[str, Any]) -> str | None:
    """Read either a structured speaker or MOSS's text prefix."""
    if segment.get("speaker"):
        return segment["speaker"]
    match = MOSS_SPEAKER_PREFIX.match(segment.get("text") or "")
    return match.group(1) if match else None


@dataclass
class Interval:
    """A time interval in seconds relative to recording start."""

    start: float
    end: float


@dataclass
class SpeakerAssignment:
    """Maps a diarization speaker label to a participant."""

    speaker_label: str
    participant_id: str
    participant_name: str
    score: float


@dataclass
class AssignmentResult:
    """Result of speaker-to-participant assignment."""

    assignments: list[SpeakerAssignment] = field(default_factory=list)
    unassigned_speakers: list[str] = field(default_factory=list)

    def apply_to(self, diarization: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of diarization with speaker labels replaced by names.

        Replaces `"speaker"` fields in segments and word_segments with the
        assigned participant name.  Unassigned speakers are left as-is.

        Args:
            diarization: WhisperX dict with `segments` and optionally
                `word_segments`.

        Returns:
            New dict with speaker labels replaced.
        """
        speaker_to_name = {
            a.speaker_label: a.participant_name for a in self.assignments
        }

        name_to_speaker_count = defaultdict(int)
        for name in speaker_to_name.values():
            name_to_speaker_count[name] += 1

        def _replace_speaker(item: dict[str, Any]) -> dict[str, Any]:
            label = _speaker_label(item)
            if label in speaker_to_name:
                name = speaker_to_name[label]
                suffix = (
                    f" ({label})" if name_to_speaker_count[name] > 1 else ""
                )  # Add suffix only if there are multiple detected speakers per user
                updated = {**item, "speaker": f"{name}{suffix}"}
                if not item.get("speaker") and "text" in item:
                    updated["text"] = MOSS_SPEAKER_PREFIX.sub("", item["text"], count=1)
                return updated
            return {**item}

        def _process_segment(item: dict[str, Any], include_words: bool = False) -> dict[str, Any]:
            new_item = _replace_speaker(item)
            if include_words and item.get("words") is not None:
                new_item["words"] = [_replace_speaker(w) for w in item["words"]]
            return new_item

        result: dict[str, Any] = {}
        for key, value in diarization.items():
            if key not in ("segments", "word_segments"):
                result[key] = value
                continue
            result[key] = [
                _process_segment(item, include_words=(key == "segments"))
                for item in value
            ] if value is not None else None
        return result


def _merge_intervals(intervals: list[Interval]) -> list[Interval]:
    """Return a list of non-overlapping intervals sorted by start time."""
    if not intervals:
        return []
    sorted_intervals = sorted(intervals, key=lambda interval: interval.start)
    merged: list[Interval] = [
        Interval(sorted_intervals[0].start, sorted_intervals[0].end)
    ]
    for interval in sorted_intervals[1:]:
        if interval.start <= merged[-1].end:
            merged[-1].end = max(merged[-1].end, interval.end)
        else:
            merged.append(Interval(interval.start, interval.end))
    return merged


def _total_duration(intervals: list[Interval]) -> float:
    """Return the sum of all interval durations."""
    return sum(interval.end - interval.start for interval in intervals)


def _overlap_duration(
    a_intervals: list[Interval],
    b_intervals: list[Interval],
) -> float:
    """Compute total overlap between two merged interval lists, sorted by start time."""
    overlap = 0.0
    i = j = 0
    while i < len(a_intervals) and j < len(b_intervals):
        a = a_intervals[i]
        b = b_intervals[j]
        lo = max(a.start, b.start)
        hi = min(a.end, b.end)
        if lo < hi:
            overlap += hi - lo
        if a.end <= b.end:
            i += 1
        else:
            j += 1
    return overlap


def _format_timelines_debug(
    participant_timelines: dict[str, list[Interval]],
    participant_names: dict[str, str],
    speaker_timelines: dict[str, list[Interval]],
) -> str:
    """Render participant and speaker timelines side-by-side for debugging.

    Each row is the slice between two consecutive interval boundaries
    (drawn from both sides). A filled cell marks an active participant
    (left block) or speaker (right block) during that slice, so vertical
    alignment makes overlap visually obvious.
    """
    participant_ids = sorted(participant_timelines.keys())
    speaker_labels = sorted(speaker_timelines.keys())

    if not participant_ids and not speaker_labels:
        return "(no timelines)"

    boundaries: set[float] = set()
    for intervals in (*participant_timelines.values(), *speaker_timelines.values()):
        for iv in intervals:
            boundaries.add(iv.start)
            boundaries.add(iv.end)
    sorted_boundaries = sorted(boundaries)
    if len(sorted_boundaries) < 2:
        return "(no intervals)"

    p_headers = [participant_names.get(pid, pid) for pid in participant_ids]
    s_headers = list(speaker_labels)
    p_widths = [max(len(h), 3) for h in p_headers]
    s_widths = [max(len(h), 3) for h in s_headers]

    def _active(intervals: list[Interval], lo: float, hi: float) -> bool:
        mid = (lo + hi) / 2
        return any(iv.start <= mid < iv.end for iv in intervals)

    def _cells(
        intervals_list: list[list[Interval]],
        widths: list[int],
        lo: float,
        hi: float,
    ) -> str:
        return " ".join(
            ("█" * w if _active(iv, lo, hi) else "·" * w)
            for iv, w in zip(intervals_list, widths, strict=True)
        )

    p_iv_list = [participant_timelines[pid] for pid in participant_ids]
    s_iv_list = [speaker_timelines[sl] for sl in speaker_labels]

    time_col = "[   start →      end]"
    p_hdr = (
        " ".join(h.center(w) for h, w in zip(p_headers, p_widths, strict=True))
        or "(none)"
    )
    s_hdr = (
        " ".join(h.center(w) for h, w in zip(s_headers, s_widths, strict=True))
        or "(none)"
    )
    sep = "  ||  "
    lines = [
        f"{time_col}  {p_hdr}{sep}{s_hdr}",
        "-" * (len(time_col) + 2 + len(p_hdr) + len(sep) + len(s_hdr)),
    ]
    for lo, hi in zip(sorted_boundaries, sorted_boundaries[1:], strict=False):
        time_str = f"[{lo:8.2f} → {hi:8.2f}]"
        p_row = _cells(p_iv_list, p_widths, lo, hi) or " " * len(p_hdr)
        s_row = _cells(s_iv_list, s_widths, lo, hi) or " " * len(s_hdr)
        lines.append(f"{time_str}  {p_row}{sep}{s_row}")
    return "\n".join(lines)


def _build_participant_timelines(
    metadata: dict[str, Any],
    recording_start_datetime: datetime,
    recording_end_datetime: datetime | None = None,
) -> tuple[dict[str, list[Interval]], dict[str, str]]:
    """Build VAD interval timelines for each participant.

    Args:
        metadata: Dict with `events` and `participants` keys.
        recording_start_datetime: UTC datetime used as t=0 reference.
        recording_end_datetime: UTC datetime of recording end. When provided,
            any open speech_start without a matching speech_end is closed at
            this time (the participant is assumed to be speaking until the end).

    Returns:
        participant_id → merged VAD intervals
            (seconds relative to recording_start_datetime).
        participant_id → display name.
        Intervals are in seconds relative to recording_start_datetime.
        Events before recording start are clamped to 0.
    """
    events = metadata.get("events", [])
    participants_info = {
        p["participantId"]: p.get("name", p["participantId"])
        for p in metadata.get("participants", [])
    }

    ref_epoch = recording_start_datetime.timestamp()

    open_starts: dict[str, float] = {}
    intervals: dict[str, list[Interval]] = {}

    for event in events:
        pid = event["participant_id"]
        ts = datetime.fromisoformat(event["timestamp"]).timestamp() - ref_epoch
        etype = event["type"]

        if etype == "speech_start":
            open_starts[pid] = max(ts, 0.0)
        elif etype == "speech_end":
            start = open_starts.pop(pid, None)
            if start is not None:
                end = max(ts, 0.0)
                if end > start:
                    intervals.setdefault(pid, []).append(Interval(start, end))

    # Close any speech_start that was never matched by a speech_end.
    # Assume the participant kept speaking until the recording ended.
    if recording_end_datetime is not None and open_starts:
        recording_end = recording_end_datetime.timestamp() - ref_epoch
        for pid, start in open_starts.items():
            end = max(recording_end, 0.0)
            if end > start:
                intervals.setdefault(pid, []).append(Interval(start, end))

    for pid, pid_intervals in intervals.items():
        intervals[pid] = _merge_intervals(pid_intervals)

    return intervals, participants_info


def _build_speaker_timelines(transcription: Any) -> dict[str, list[Interval]]:
    """Build interval timelines from WhisperX transcription segments."""
    intervals: dict[str, list[Interval]] = {}
    segments = transcription.get("segments") or []
    max_word_duration = settings.resolve_speaker_identities_max_word_duration

    for segment in segments:
        speaker = _speaker_label(segment)
        if speaker is None:
            continue

        words = [
            w
            for w in (segment.get("words") or [])
            if w.get("start") is not None and w.get("end") is not None
        ]
        if not words:
            intervals.setdefault(speaker, []).append(
                Interval(segment["start"], segment["end"])
            )
            continue

        start_time: float | None = segment["start"]
        for word in words:
            if start_time is None:
                start_time = word["start"]
            if not settings.resolve_speaker_identities_enable_split_on_words:
                continue
            if word["end"] - word["start"] > max_word_duration:
                end_time = word["start"] + max_word_duration
                if end_time > start_time:
                    intervals.setdefault(speaker, []).append(
                        Interval(start_time, end_time)
                    )
                start_time = None

        if start_time is not None:
            last = words[-1]
            end_time = min(last["end"], last["start"] + max_word_duration)
            if end_time > start_time:
                intervals.setdefault(speaker, []).append(Interval(start_time, end_time))

    for speaker, speaker_intervals in intervals.items():
        intervals[speaker] = _merge_intervals(speaker_intervals)
    return intervals


def _json_default(obj: Any) -> Any:
    """Encode datetimes, dataclasses, and pydantic models for `json.dumps`.

    Intended to be used for logging of `resolve_speaker_identities` (input
    and computed variables)
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, set):
        return sorted(obj)
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if hasattr(obj, "segments") and hasattr(obj, "word_segments"):
        return {"segments": obj.segments, "word_segments": obj.word_segments}
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")

    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _best_unique_assignment(
    scores: list[list[float]],
    threshold: float,
    excluded: tuple[int, int] | None = None,
) -> tuple[float, list[int | None]]:
    """Maximum-weight one-to-one assignment with an unmatched slot per speaker."""
    rows = len(scores)
    if not rows:
        return 0.0, []
    participants = len(scores[0])
    columns = participants + rows
    costs = [
        [
            -score if j < participants and score >= threshold and (i, j) != excluded
            else 0.0 if j >= participants else 1_000_000.0
            for j, score in enumerate(row + [0.0] * rows)
        ]
        for i, row in enumerate(scores)
    ]
    # Rectangular Hungarian algorithm (rows <= columns).
    u = [0.0] * (rows + 1)
    v = [0.0] * (columns + 1)
    p = [0] * (columns + 1)
    way = [0] * (columns + 1)
    for i in range(1, rows + 1):
        p[0] = i
        j0 = 0
        minv = [float("inf")] * (columns + 1)
        used = [False] * (columns + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = 0
            for j in range(1, columns + 1):
                if used[j]:
                    continue
                cur = costs[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(columns + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    assignment: list[int | None] = [None] * rows
    for j in range(1, columns + 1):
        if p[j] and j <= participants:
            assignment[p[j] - 1] = j - 1
    total = sum(scores[i][j] for i, j in enumerate(assignment) if j is not None)
    return total, assignment


def resolve_speaker_identities(
    metadata: dict[str, Any],
    transcription: Any,
    recording_start_datetime: datetime,
    recording_end_datetime: datetime,
    overlap_threshold: float = settings.resolve_speaker_identities_default_overlap_threshold,  # noqa: E501
) -> AssignmentResult:
    """Assign each speaker label globally using all its recorded speech.

    Args:
        metadata: User metadata with `events` and `participants`.
        transcription: WhisperX Transcription object with a `segments` attribute.
        recording_start_datetime: UTC datetime for t=0 reference.
        recording_end_datetime: UTC datetime of recording end. Open speech
            intervals are closed at this time.
        overlap_threshold: Minimum overlap/speaker_duration to accept.

    Returns:
        AssignmentResult with per-speaker assignments and unassigned
        speakers.
    """
    participant_timelines, participant_names = _build_participant_timelines(
        metadata, recording_start_datetime, recording_end_datetime
    )
    speaker_timelines = _build_speaker_timelines(transcription)

    tolerant_participant_timelines = {
        pid: _merge_intervals([
            Interval(max(0.0, iv.start - VAD_START_TOLERANCE_SECONDS),
                     iv.end + VAD_END_TOLERANCE_SECONDS)
            for iv in intervals
        ])
        for pid, intervals in participant_timelines.items()
    }

    result = AssignmentResult()
    speakers = list(speaker_timelines)
    participants = list(tolerant_participant_timelines)
    scores = []
    for intervals in speaker_timelines.values():
        duration = _total_duration(intervals)
        scores.append([
            _overlap_duration(intervals, tolerant_participant_timelines[pid]) / duration
            if duration else 0.0
            for pid in participants
        ])

    total, chosen = _best_unique_assignment(scores, overlap_threshold)
    for i, speaker in enumerate(speakers):
        j = chosen[i]
        if j is None:
            result.unassigned_speakers.append(speaker)
            continue
        alternative_total, _ = _best_unique_assignment(
            scores, overlap_threshold, excluded=(i, j)
        )
        margin = total - alternative_total
        if margin < ASSIGNMENT_MARGIN:
            result.unassigned_speakers.append(speaker)
            logger.info("Speaker %s remains ambiguous (margin=%.3f)", speaker, margin)
            continue
        pid = participants[j]
        result.assignments.append(SpeakerAssignment(
            speaker_label=speaker,
            participant_id=pid,
            participant_name=participant_names.get(pid, pid),
            score=scores[i][j],
        ))
        logger.info("Assigned %s -> %s (score=%.3f, margin=%.3f)", speaker,
                    participant_names.get(pid, pid), scores[i][j], margin)

    logger.debug(
        json.dumps(
            {
                "input": {
                    "recording_start_datetime": recording_start_datetime.isoformat(),
                    "recording_end_datetime": recording_end_datetime.isoformat(),
                    "metadata": metadata,
                    "transcription": transcription,
                },
                "computed": {
                    "speaker_timelines": speaker_timelines,
                    "participant_timelines": participant_timelines,
                    "result": result,
                },
            },
            default=_json_default,
            indent=2,
            ensure_ascii=False,
        ),
    )
    logger.debug(
        _format_timelines_debug(
            participant_timelines, participant_names, speaker_timelines
        ),
    )

    return result
