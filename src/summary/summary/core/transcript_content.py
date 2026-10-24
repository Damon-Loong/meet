"""Recognize protocol labels without treating them as spoken content."""

import re

_TIMESTAMP_LABEL = re.compile(
    r"\[(?:\d+(?:\.\d+)?|\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)\]"
)
_SPEAKER_LABEL = re.compile(r"\[(?:S\d+|speaker[_ ]?\d+)\]", re.IGNORECASE)
_REFUSAL_ONLY = re.compile(
    r"(?:i['’]m sorry,?\s+(?:but\s+)?i can['’]t assist with that request[.!]?\s*)+",
    re.IGNORECASE,
)


def strip_timestamp_labels(text: str) -> str:
    """Drop bracketed timestamps, preserving ordinary numbers and other text."""
    return _TIMESTAMP_LABEL.sub("", text).strip()


def has_spoken_text(text: str) -> bool:
    """Speaker labels and timestamps alone are not a transcript body."""
    return bool(_SPEAKER_LABEL.sub("", strip_timestamp_labels(text)).strip())


def is_refusal_only(texts: list[str]) -> bool:
    """Match only the observed refusal, never a fragment of a real discussion."""
    body = " ".join(
        _SPEAKER_LABEL.sub("", strip_timestamp_labels(text)).strip() for text in texts
    ).strip()
    return bool(_REFUSAL_ONLY.fullmatch(body))
