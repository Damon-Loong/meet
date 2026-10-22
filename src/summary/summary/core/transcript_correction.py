"""Constrained terminology correction for formatted meeting transcripts."""

import json
import logging
import re
from collections.abc import Callable, Iterable

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

SPEECH_LINE = re.compile(
    r"^(?P<prefix>-\s*\*\*\[[^]]+]\s*[^：]+：\*\*\s*)(?P<text>.*)$"
)

SYSTEM_PROMPT = """你是会议转录的专有名词纠错器。
候选标准词均为公司已经确认的正确专名；如果正文出现与候选词同音或近音的写法，
即使错误写法本身也像正常人名或公司名，也应纠正为候选标准词。
只判断转录中明确属于候选标准词的同音字、近音字或明显错别字。
不得润色、改写、概括、补充或删除会议内容，不得修改数字、日期、金额、时间戳和说话人。
original 必须是对应行正文中原样存在的最短错误片段；
replacement 必须完整等于一个候选标准词。
无法确定时不要输出纠正。只返回符合给定 JSON Schema 的结果。"""


class Correction(BaseModel):
    """One exact, line-scoped spelling replacement."""

    model_config = ConfigDict(extra="forbid")

    line: int = Field(ge=1)
    original: str = Field(min_length=1, max_length=32)
    replacement: str = Field(min_length=1, max_length=64)


class CorrectionBatch(BaseModel):
    """Bounded corrections returned for one transcript chunk."""

    model_config = ConfigDict(extra="forbid")

    corrections: list[Correction] = Field(default_factory=list, max_length=200)


CORRECTION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "transcript_terminology_corrections",
        "strict": True,
        "schema": CorrectionBatch.model_json_schema(),
    },
}


def _terms(values: Iterable[str]) -> tuple[str, ...]:
    """Normalize configured canonical terms without learning from transcripts."""
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def _chunks(items: list[tuple[int, str]], max_chars: int):
    """Yield complete utterance lines within a bounded model input size."""
    current: list[tuple[int, str]] = []
    size = 0
    for item in items:
        item_size = len(item[1]) + 24
        if current and size + item_size > max_chars:
            yield current
            current = []
            size = 0
        current.append(item)
        size += item_size
    if current:
        yield current


def correct_transcript_spelling(
    transcript: str,
    canonical_terms: Iterable[str],
    call: Callable,
    *,
    max_chars: int = 20000,
) -> str:
    """Correct only validated terminology substitutions and fail open per chunk."""
    terms = _terms(canonical_terms)
    if not terms:
        return transcript

    trailing_newline = transcript.endswith("\n")
    lines = transcript.splitlines()
    utterances: list[tuple[int, str]] = []
    prefixes: dict[int, str] = {}
    for line_number, line in enumerate(lines, start=1):
        match = SPEECH_LINE.match(line)
        if not match or not match.group("text").strip():
            continue
        prefixes[line_number] = match.group("prefix")
        utterances.append((line_number, match.group("text")))
    if not utterances:
        return transcript

    allowed = set(terms)
    applied = 0
    rejected = 0
    for chunk_index, chunk in enumerate(_chunks(utterances, max_chars), start=1):
        source = {
            "候选标准词": terms,
            "转录行": [
                {"line": line_number, "text": text} for line_number, text in chunk
            ],
        }
        try:
            raw = call(
                SYSTEM_PROMPT,
                json.dumps(source, ensure_ascii=False),
                name=f"transcript-correction-{chunk_index}",
                response_format=CORRECTION_RESPONSE_FORMAT,
            )
            batch = CorrectionBatch.model_validate_json(raw)
        except Exception:
            # Correction is advisory: summary and delivery must continue unchanged.
            logger.warning(
                "Transcript correction unavailable for chunk %s; preserving source",
                chunk_index,
                exc_info=True,
            )
            continue

        chunk_lines = {line_number for line_number, _ in chunk}
        seen: set[tuple[int, str]] = set()
        for correction in batch.corrections:
            key = (correction.line, correction.original)
            line_index = correction.line - 1
            if (
                correction.line not in chunk_lines
                or line_index < 0
                or line_index >= len(lines)
                or correction.replacement not in allowed
                or correction.original == correction.replacement
                or correction.original in allowed
                or key in seen
                or "\n" in correction.original
                or not re.search(r"[A-Za-z\u3400-\u9fff]", correction.original)
            ):
                rejected += 1
                continue
            match = SPEECH_LINE.match(lines[line_index])
            if not match or correction.original not in match.group("text"):
                rejected += 1
                continue
            corrected = match.group("text").replace(
                correction.original, correction.replacement
            )
            lines[line_index] = prefixes[correction.line] + corrected
            seen.add(key)
            applied += 1

    logger.info(
        "Transcript terminology correction complete | applied=%s rejected=%s",
        applied,
        rejected,
    )
    result = "\n".join(lines)
    return result + ("\n" if trailing_newline else "")
