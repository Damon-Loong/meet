"""Periodic reminders and room expiry."""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from core import models
from core.services.scheduling import SchedulingService
from core.tasks._task import task


@task(name="core.process_scheduled_meetings")
def process_scheduled_meetings():
    now = timezone.now()
    invitations = (
        models.MeetingInvitation.objects.select_related("meeting", "meeting__room")
        .filter(
            response_status=models.InvitationResponseChoices.PENDING,
            meeting__status=models.ScheduledMeetingStatusChoices.SCHEDULED,
            meeting__starts_at__gt=now,
            meeting__starts_at__lte=now + timedelta(minutes=30),
        )
    )
    for invitation in invitations:
        remaining = invitation.meeting.starts_at - now
        if remaining <= timedelta(minutes=10):
            if invitation.reminder_10m_sent_at is None:
                SchedulingService.send_invitation(invitation, reminder_minutes=10)
        elif invitation.reminder_30m_sent_at is None:
            SchedulingService.send_invitation(invitation, reminder_minutes=30)

    idle_before = now - timedelta(minutes=30)
    (
        models.Room.objects.filter(
            room_type=models.RoomTypeChoices.INSTANT,
            lifecycle_status=models.RoomLifecycleStatusChoices.ACTIVE,
            active_participant_count=0,
        )
        .filter(
            Q(last_empty_at__lte=idle_before)
            | Q(last_empty_at__isnull=True, created_at__lte=idle_before)
        )
        .update(
            lifecycle_status=models.RoomLifecycleStatusChoices.EXPIRED,
            expired_at=now,
        )
    )
    (
        models.Room.objects.filter(
            room_type=models.RoomTypeChoices.SCHEDULED,
            lifecycle_status=models.RoomLifecycleStatusChoices.ACTIVE,
            active_participant_count=0,
            scheduled_meeting__status=models.ScheduledMeetingStatusChoices.SCHEDULED,
            scheduled_meeting__ends_at__lte=idle_before,
        )
        .filter(Q(last_empty_at__lte=idle_before) | Q(last_empty_at__isnull=True))
        .update(
            lifecycle_status=models.RoomLifecycleStatusChoices.EXPIRED,
            expired_at=now,
        )
    )
    models.ScheduledMeeting.objects.filter(
        room__lifecycle_status=models.RoomLifecycleStatusChoices.EXPIRED,
        status=models.ScheduledMeetingStatusChoices.SCHEDULED,
    ).update(status=models.ScheduledMeetingStatusChoices.FINISHED)
