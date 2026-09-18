"""Simplified Chinese locale strings."""

from summary.core.locales.strings import LocaleStrings

STRINGS = LocaleStrings(
    empty_transcription="**没有检测到可转录的语音内容。**",
    download_header_template=("\n*[下载会议录音]({download_link})*\n"),
    form_footer_template=("\n\n*[提交转录反馈]({form_link})*\n"),
    hallucination_replacement_text="[无法识别]",
    summary_title_template="{title}的会议总结",
)
