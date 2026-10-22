"""Optional, confirmed vocabulary hints for the deployed MOSS recognizer."""

MOSS_TRANSCRIPTION_PROMPT = (
    "请将音频转写为文本，每一段需以起始时间戳和说话人编号"
    "（[S01]、[S02]、[S03]…）开头，正文为对应的语音内容，"
    "并在段末标注结束时间戳，以清晰标明该段语音范围。"
)


def transcription_prompt(model: str, hotwords: tuple[str, ...]) -> str:
    """Use the recognizer's default prompt until hotword regression is resolved.

    The full vocabulary reproducibly caused runaway repetition on a 48-second
    recording. Ignore configured vocabulary too, so stale deployment settings
    cannot silently re-enable the affected request path.
    """
    return ""
