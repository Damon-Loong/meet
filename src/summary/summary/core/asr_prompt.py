"""MOSS request defaults and paused vocabulary hints."""

MOSS_TRANSCRIPTION_PROMPT = (
    "请将音频转写为文本，每一段需以起始时间戳和说话人编号"
    "（[S01]、[S02]、[S03]…）开头，正文为对应的语音内容，"
    "并在段末标注结束时间戳，以清晰标明该段语音范围。"
)


def transcription_generation_params(
    model: str, max_tokens: int | None
) -> dict[str, int | float]:
    """Use MOSS's duration budget and damp non-speech repetition loops.

    A fixed request budget disables SGLang-Omni's duration-scaled default.
    Keep explicit budgets unchanged for other transcription providers.
    """
    if model.lower().rsplit("/", 1)[-1] == "moss-transcribe-diarize":
        return {"repetition_penalty": 1.1}
    return {"max_new_tokens": max_tokens} if max_tokens else {}


def transcription_prompt(model: str, hotwords: tuple[str, ...]) -> str:
    """Use the recognizer's default prompt until hotword regression is resolved.

    The full vocabulary reproducibly caused runaway repetition on a 48-second
    recording. Ignore configured vocabulary too, so stale deployment settings
    cannot silently re-enable the affected request path.
    """
    return ""
