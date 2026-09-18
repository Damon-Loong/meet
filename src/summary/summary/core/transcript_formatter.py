"""Transcript formatting into readable conversation format with speaker labels."""

import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from summary.core.config import get_settings
from summary.core.locales import LocaleStrings

settings = get_settings()

logger = logging.getLogger(__name__)


class TranscriptFormatter:
    """Formats WhisperX transcription output into readable conversation format.

    Handles:
    - Extracting segments from transcription objects or dictionaries
    - Combining consecutive segments from the same speaker
    - Removing hallucination patterns from content
    - Generating descriptive titles from context
    """

    def __init__(self, locale: LocaleStrings):
        """Initialize formatter with settings and locale."""
        self.hallucination_patterns = settings.hallucination_patterns
        self._locale = locale

    def _get_segments(self, transcription):
        """Extract segments from transcription object or dictionary."""
        if hasattr(transcription, "segments"):
            return transcription.segments

        if isinstance(transcription, dict):
            return transcription.get("segments", None)

        return None

    def format(
        self,
        transcription,
        download_link: str | None = None,
        form_link: str | None = None,
        title: str | None = None,
        recording_metadata=None,
        participant_metadata: dict | None = None,
    ) -> str:
        """Format transcription as a professional meeting record."""
        segments = self._get_segments(transcription)

        if not segments:
            transcript = self._locale.empty_transcription
        participants = self._get_participants(participant_metadata, segments or [])
        if segments:
            transcript = self._remove_hallucinations(
                self._format_speaker(segments, participants)
            )
        content = self._format_document(
            title=title,
            transcript=transcript,
            participants=participants,
            recording_metadata=recording_metadata,
        )
        if form_link:
            content = self._add_footer(content, form_link)

        return content

    def _remove_hallucinations(self, content: str) -> str:
        """Remove hallucination patterns from content."""
        replacement = self._locale.hallucination_replacement_text or ""

        for pattern in self.hallucination_patterns:
            content = content.replace(pattern, replacement)
        return content

    def _format_speaker(self, segments, participants: list[str]) -> str:
        """Format every segment on its own timestamped line."""
        lines = []
        for segment in segments:
            text = segment.get("text", "").strip()
            raw_speaker = segment.get("speaker")
            prefix = re.match(r"^\s*\[([^\]]+)\]\s*", text)
            if prefix and not raw_speaker:
                raw_speaker = prefix.group(1)
                text = text[prefix.end() :].strip()
            speaker = self._display_speaker(raw_speaker)
            if len(participants) == 1 and self._is_generic_speaker(speaker):
                speaker = participants[0]
            if text:
                timestamp = self._format_offset(segment.get("start"))
                lines.append(f"- **[{timestamp}] {speaker}：** {text}")

        return "\n\n".join(lines)

    @staticmethod
    def _is_generic_speaker(speaker: str) -> bool:
        return speaker == "未知发言人" or speaker.startswith("发言人 ")

    @staticmethod
    def _format_offset(value) -> str:
        """Render seconds from recording start as HH:MM:SS."""
        try:
            total = max(0, int(float(value or 0)))
        except (TypeError, ValueError):
            total = 0
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    @staticmethod
    def _display_speaker(speaker) -> str:
        """Turn raw diarization labels into reader-friendly names."""
        if not speaker or speaker == "UNKNOWN_SPEAKER":
            return "未知发言人"
        value = str(speaker)
        match = re.fullmatch(r"(?:S|SPEAKER_?)(\d+)", value, re.IGNORECASE)
        if match:
            return f"发言人 {int(match.group(1)):02d}"
        return value

    def _get_participants(self, metadata: dict | None, segments) -> list[str]:
        """Return unique participant names, falling back to detected speakers."""
        names = []
        for participant in (metadata or {}).get("participants", []):
            identity = str(participant.get("identity") or "")
            name = participant.get("name") or participant.get("identity")
            if identity.upper().startswith("EG_") or str(name or "").upper().startswith(
                "EG_"
            ):
                continue
            if name and name not in names:
                names.append(str(name))
        if not names:
            for segment in segments:
                speaker = segment.get("speaker")
                if not speaker:
                    prefix = re.match(
                        r"^\s*\[([^\]]+)\]", segment.get("text", "")
                    )
                    speaker = prefix.group(1) if prefix else None
                name = self._display_speaker(speaker)
                if name not in names:
                    names.append(name)
        return names

    def _format_datetime(self, value: datetime | None) -> str:
        if value is None:
            return "未记录"
        try:
            value = value.astimezone(ZoneInfo(settings.document_timezone))
        except (ValueError, TypeError):
            pass
        return value.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _format_duration(start: datetime | None, end: datetime | None) -> str:
        if not start or not end:
            return "未记录"
        total = max(0, int((end - start).total_seconds()))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours} 小时 {minutes} 分 {seconds} 秒"
        return f"{minutes} 分 {seconds} 秒"

    def _format_document(
        self, *, title, transcript, participants, recording_metadata
    ) -> str:
        """Build the complete Markdown meeting transcript."""
        document_title = title or "会议转录"
        english_title = re.fullmatch(
            r'Meeting "(.+)" on \d{4}-\d{2}-\d{2} at \d{2}:\d{2}',
            document_title,
        )
        if english_title:
            document_title = f"{english_title.group(1)}｜会议转录"
        start = getattr(recording_metadata, "started_at", None)
        end = getattr(recording_metadata, "ended_at", None)
        participant_text = "、".join(participants) if participants else "未记录"
        participant_count = len(participants) if participants else 0

        return (
            f"# {document_title}\n\n"
            "## 会议概览\n\n"
            "| 项目 | 信息 |\n"
            "| --- | --- |\n"
            f"| 会议开始 | {self._format_datetime(start)} |\n"
            f"| 会议结束 | {self._format_datetime(end)} |\n"
            f"| 会议时长 | {self._format_duration(start, end)} |\n"
            f"| 参会人数 | {participant_count} 人 |\n\n"
            "## 参会人员\n\n"
            f"{participant_text}\n\n"
            "## 会议事件\n\n"
            f"- **{self._format_datetime(start)}**　会议开始\n"
            f"- **{self._format_datetime(end)}**　会议结束\n\n"
            "## 逐字转录\n\n"
            "> 时间标记为相对于会议开始的时长。转录内容由 AI 自动生成，可能存在误差。\n\n"
            f"{transcript.strip()}\n"
        )

    def _add_header(self, content, download_link: str | None) -> str:
        """Add download link header to the document content."""
        if not download_link:
            return content

        header = self._locale.download_header_template.format(
            download_link=download_link
        )
        return header + content

    def _add_footer(self, content, form_link: str | None):
        if not form_link:
            return content

        footer = self._locale.form_footer_template.format(form_link=form_link)
        return content + footer
