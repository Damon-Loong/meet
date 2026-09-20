"""Scheduled meetings and invitations."""

import hashlib
import html
import secrets
from datetime import timezone as datetime_timezone
from email.utils import parseaddr
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from core import models


class SchedulingService:
    """Business operations for immutable meeting schedules."""

    @staticmethod
    @transaction.atomic
    def create_schedule(
        room, organizer, starts_at, ends_at, timezone_name, invite_emails
    ):
        meeting = models.ScheduledMeeting.objects.create(
            room=room,
            organizer=organizer,
            topic=room.topic,
            starts_at=starts_at,
            ends_at=ends_at,
            timezone=timezone_name or "Asia/Shanghai",
        )
        organizer_email = organizer.email or organizer.admin_email
        recipients = list(invite_emails)
        if organizer_email:
            recipients.insert(0, organizer_email.lower())
        seen = set()
        for email in recipients:
            normalized = email.strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            is_organizer = bool(
                organizer_email and normalized == organizer_email.lower()
            )
            raw_token = secrets.token_urlsafe(32)
            invitation = models.MeetingInvitation.objects.create(
                meeting=meeting,
                email=normalized,
                is_organizer=is_organizer,
                response_status=(
                    models.InvitationResponseChoices.ACCEPTED
                    if is_organizer
                    else models.InvitationResponseChoices.PENDING
                ),
                confirmed_at=timezone.now() if is_organizer else None,
                token_digest=hashlib.sha256(raw_token.encode()).hexdigest(),
            )
            SchedulingService.send_invitation(invitation, raw_token=raw_token)
        return meeting

    @staticmethod
    def _format_local(dt, timezone_name):
        return dt.astimezone(ZoneInfo(timezone_name)).strftime("%Y/%m/%d %H:%M")

    @staticmethod
    def _ics(meeting, method="REQUEST"):
        stamp = timezone.now().astimezone(datetime_timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ"
        )
        start = meeting.starts_at.astimezone(datetime_timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ"
        )
        end = meeting.ends_at.astimezone(datetime_timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ"
        )
        status = "CANCELLED" if method == "CANCEL" else "CONFIRMED"
        room_url = f"{settings.EMAIL_APP_BASE_URL.rstrip('/')}/{meeting.room.slug}"
        organizer = meeting.organizer
        organizer_email = organizer.email or organizer.admin_email
        organizer_name = (
            organizer.full_name
            or organizer.short_name
            or organizer_email
            or "会议主持人"
        )
        sender_email = parseaddr(settings.EMAIL_FROM)[1]
        organizer_email = organizer_email or sender_email
        sent_by = (
            f';SENT-BY="mailto:{sender_email}"'
            if sender_email and sender_email.lower() != organizer_email.lower()
            else ""
        )
        attendees = []
        for invitation in meeting.invitations.all():
            if invitation.email.lower() == organizer_email.lower():
                continue
            partstat = (
                "ACCEPTED"
                if invitation.response_status
                == models.InvitationResponseChoices.ACCEPTED
                else "NEEDS-ACTION"
            )
            attendees.append(
                f"ATTENDEE;CN={invitation.email};ROLE=REQ-PARTICIPANT;"
                f"PARTSTAT={partstat};RSVP=TRUE:mailto:{invitation.email}"
            )
        return "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "PRODID:-//AfB Meet//ZH-CN",
                f"METHOD:{method}",
                "BEGIN:VEVENT",
                f"UID:{meeting.id}@afb-meet",
                f"DTSTAMP:{stamp}",
                f"DTSTART:{start}",
                f"DTEND:{end}",
                f"SUMMARY:{meeting.topic}",
                f"DESCRIPTION:{room_url}",
                f"ORGANIZER;CN={organizer_name}{sent_by}:mailto:{organizer_email}",
                *attendees,
                f"URL:{room_url}",
                f"STATUS:{status}",
                "END:VEVENT",
                "END:VCALENDAR",
                "",
            ]
        )

    @staticmethod
    def send_invitation(invitation, raw_token=None, reminder_minutes=None):
        meeting = invitation.meeting
        base_url = settings.EMAIL_APP_BASE_URL.rstrip("/")
        room_url = f"{base_url}/{meeting.room.slug}"
        confirm_url = (
            f"{base_url}/meeting-confirmation?token={raw_token}" if raw_token else ""
        )
        start = SchedulingService._format_local(meeting.starts_at, meeting.timezone)
        end = SchedulingService._format_local(meeting.ends_at, meeting.timezone)
        if reminder_minutes:
            subject = f"【{reminder_minutes}分钟后开始】{meeting.topic}"
            heading = f"会议将在{reminder_minutes}分钟后开始"
        else:
            subject = f"AfB Meet会议邀请：{meeting.topic}"
            heading = "AfB Meet会议邀请"
        confirm_block = ""
        if confirm_url and not invitation.is_organizer:
            confirm_block = (
                f'<p><a href="{html.escape(confirm_url)}" '
                'style="background:#000091;color:#fff;padding:12px 20px;'
                'text-decoration:none;border-radius:4px">确认参会</a></p>'
            )
        body = (
            f"<h2>{heading}</h2>"
            f"<p><strong>会议主题：</strong>{html.escape(meeting.topic)}</p>"
            f"<p><strong>开始时间：</strong>{start}</p>"
            f"<p><strong>结束时间：</strong>{end}</p>"
            "<p><strong>时区：</strong>(GMT+08:00) 中国标准时间 - 北京</p>"
            f"{confirm_block}<p><a href=\"{html.escape(room_url)}\">点击链接入会</a></p>"
        )
        text = (
            f"{heading}\n会议主题：{meeting.topic}\n开始时间：{start}\n"
            f"结束时间：{end}\n点击链接入会：{room_url}"
        )
        if confirm_url and not invitation.is_organizer:
            text += f"\n确认参会：{confirm_url}"
        organizer_email = meeting.organizer.email or meeting.organizer.admin_email
        message = EmailMultiAlternatives(
            subject,
            text,
            settings.EMAIL_FROM,
            [invitation.email],
            reply_to=[organizer_email] if organizer_email else None,
        )
        message.attach_alternative(body, "text/html")
        if not reminder_minutes:
            message.attach(
                "meeting.ics",
                SchedulingService._ics(meeting),
                "text/calendar; method=REQUEST",
            )
        try:
            message.send()
            now = timezone.now()
            if reminder_minutes == 30:
                invitation.reminder_30m_sent_at = now
            elif reminder_minutes == 10:
                invitation.reminder_10m_sent_at = now
            else:
                invitation.initial_email_sent_at = now
            invitation.send_error = ""
        except Exception as exc:  # SMTP errors are visible in admin and retryable.
            invitation.send_error = str(exc)[:2000]
        invitation.save()

    @staticmethod
    def confirm_invitation(raw_token):
        digest = hashlib.sha256(raw_token.encode()).hexdigest()
        invitation = (
            models.MeetingInvitation.objects.select_related("meeting")
            .filter(token_digest=digest)
            .first()
        )
        if invitation is None:
            raise NotFound("Invitation not found.")
        if (
            invitation.meeting.status
            == models.ScheduledMeetingStatusChoices.CANCELLED
        ):
            raise NotFound("Meeting has been cancelled.")
        if (
            invitation.response_status
            != models.InvitationResponseChoices.ACCEPTED
        ):
            invitation.response_status = models.InvitationResponseChoices.ACCEPTED
            invitation.confirmed_at = timezone.now()
            invitation.save(
                update_fields=["response_status", "confirmed_at", "updated_at"]
            )
        return invitation

    @staticmethod
    @transaction.atomic
    def cancel(room):
        now = timezone.now()
        room.lifecycle_status = models.RoomLifecycleStatusChoices.CANCELLED
        room.expired_at = now
        room.save(update_fields=["lifecycle_status", "expired_at", "updated_at"])
        meeting = room.scheduled_meeting
        meeting.status = models.ScheduledMeetingStatusChoices.CANCELLED
        meeting.save(update_fields=["status", "updated_at"])
        for invitation in meeting.invitations.all():
            message = EmailMultiAlternatives(
                f"AfB Meet会议已取消：{meeting.topic}",
                f"会议“{meeting.topic}”已取消。",
                settings.EMAIL_FROM,
                [invitation.email],
                reply_to=(
                    [meeting.organizer.email or meeting.organizer.admin_email]
                    if meeting.organizer.email or meeting.organizer.admin_email
                    else None
                ),
            )
            message.attach(
                "meeting.ics",
                SchedulingService._ics(meeting, "CANCEL"),
                "text/calendar; method=CANCEL",
            )
            try:
                message.send()
            except Exception:
                pass
