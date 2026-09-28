"""Validated content and deterministic rendering for concise meeting minutes."""

import re
from datetime import date
from html import escape

from pydantic import BaseModel, ConfigDict, field_validator


class SummaryText(BaseModel):
    """Reject extra fields and normalize text from model responses."""

    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def trim_text(cls, value):
        """Normalize whitespace without changing factual content."""
        return " ".join(value.split()) if isinstance(value, str) else value


class Conclusion(SummaryText):
    """One key conclusion with its qualification or constraint."""

    title: str
    detail: str


class Action(SummaryText):
    """A future action, with timing kept distinct from a deadline."""

    task: str
    timing: str


class OwnerActions(SummaryText):
    """Actions explicitly assigned to one person; focus describes the tasks."""

    owner: str
    focus: str
    actions: list[Action]


class ConciseSummary(SummaryText):
    """Content only: meeting metadata and layout are owned by the renderer."""

    conclusions: list[Conclusion]
    owners: list[OwnerActions]
    uncertainties: list[str]


SUMMARY_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "concise_meeting_minutes",
        "strict": True,
        "schema": ConciseSummary.model_json_schema(),
    },
}


def inline_text(value: str) -> str:
    """Keep model and participant text from injecting Markdown structure or HTML."""
    value = escape(" ".join(value.split()), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|~-])", r"\\\1", value)


def transcript_header(transcript: str) -> str:
    """Read only metadata, never participant-like statements in the transcript body."""
    return re.split(r"^## 逐字转录\s*$", transcript, maxsplit=1, flags=re.MULTILINE)[0]


def meeting_date(transcript: str) -> str:
    """Use the authoritative start date rather than an LLM or generation date."""
    match = re.search(
        r"^\|\s*会议开始\s*\|\s*(\d{4}-\d{2}-\d{2})(?:\s|\|)",
        transcript_header(transcript),
        flags=re.MULTILINE,
    )
    if match:
        try:
            started = date.fromisoformat(match.group(1))
            return f"{started.year} 年 {started.month} 月 {started.day} 日"
        except ValueError:
            pass
    return "日期未记录"


def participants_line(transcript: str) -> str:
    """Preserve the meeting roster independently of assigned actions."""
    match = re.search(
        r"^## 参会人员\s*\n(.*?)(?=^## |\Z)",
        transcript_header(transcript),
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match and match.group(1).strip() else "未记录"


def _conclusion_lines(content: ConciseSummary) -> list[str]:
    """Format conclusions without duplicated items."""
    lines = []
    seen_conclusions = set()
    for conclusion in content.conclusions:
        key = (conclusion.title.casefold(), conclusion.detail.casefold())
        if not conclusion.title or not conclusion.detail:
            raise ValueError("Conclusion title and detail must not be empty")
        if key in seen_conclusions:
            continue
        seen_conclusions.add(key)
        lines.append(
            f"{len(seen_conclusions)}. **{inline_text(conclusion.title)}** "
            f"{inline_text(conclusion.detail)}"
        )
    if not seen_conclusions:
        lines.append("- 无明确记录。")
    return lines


def _owner_groups(content: ConciseSummary):
    """Merge exact owner names and move unassigned tasks to pending questions."""
    # Merge exact display names only. Upstream can normalize obvious roster-name
    # typos while retaining source names; rendering must not infer assignments.
    groups: dict[str, tuple[str, str, list[Action]]] = {}
    pending = [" ".join(item.split()) for item in content.uncertainties if item.strip()]
    for group in content.owners:
        if not group.actions:
            continue
        if any(not action.task for action in group.actions):
            raise ValueError("Action task must not be empty")
        owner = group.owner.strip()
        if not owner or owner in {"待确认", "未明确", "未知", "未记录"}:
            for action in group.actions:
                timing = f"（{action.timing}）" if action.timing else ""
                pending.append(f"负责人待确认：{action.task}{timing}")
            continue
        key = owner.casefold()
        if key not in groups:
            groups[key] = (owner, group.focus, [])
        groups[key][2].extend(group.actions)
    return groups, pending


def render_concise_summary(content: ConciseSummary, transcript: str) -> str:
    """Render writing-block-style minutes; new action items are always unchecked."""
    lines = [
        f"**会议纪要｜{meeting_date(transcript)}**",
        "",
        f"参会人：{inline_text(participants_line(transcript).rstrip('。'))}。",
        "",
        "**主要结论**",
        "",
        *_conclusion_lines(content),
    ]
    groups, pending = _owner_groups(content)
    has_undated_actions = False
    for owner, focus, actions in groups.values():
        label = inline_text(owner)
        if focus:
            label += f"｜{inline_text(focus)}"
        lines.extend(["", f"**{label}**", ""])
        seen_actions = set()
        for action in actions:
            key = (action.task.casefold(), action.timing.casefold())
            if key in seen_actions:
                continue
            seen_actions.add(key)
            timing = f" **{inline_text(action.timing)}**" if action.timing else ""
            lines.append(f"- [ ] {inline_text(action.task)}{timing}")
            has_undated_actions |= not action.timing

    if has_undated_actions:
        pending.append("除上述明确时间外，其余任务未约定截止日期。")
    lines.extend(["", "**待确认事项**", ""])
    lines.extend(f"- {inline_text(item)}" for item in dict.fromkeys(pending))
    if not pending:
        lines.append("- 无明确记录。")
    return "\n".join(lines) + "\n"
