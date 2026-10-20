"""Optional, confirmed vocabulary hints for the deployed MOSS recognizer."""

MOSS_TRANSCRIPTION_PROMPT = (
    "请将音频转写为文本，每一段需以起始时间戳和说话人编号"
    "（[S01]、[S02]、[S03]…）开头，正文为对应的语音内容，"
    "并在段末标注结束时间戳，以清晰标明该段语音范围。"
)


def transcription_prompt(model: str, hotwords: tuple[str, ...]) -> str:
    """Keep other recognizers unchanged and preserve MOSS output instructions."""
    if model.lower().rsplit("/", 1)[-1] != "moss-transcribe-diarize":
        return ""
    words = list(dict.fromkeys(word.strip() for word in hotwords if word.strip()))
    if not words:
        return ""
    return MOSS_TRANSCRIPTION_PROMPT + "热词提示：" + ", ".join(words)
