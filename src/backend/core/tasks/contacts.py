"""Best-effort asynchronous account contact persistence."""

from logging import getLogger

from core import models
from core.tasks._task import task

logger = getLogger(__name__)


@task
def upsert_account_contact(room_id, name, email, participant_identity="", authenticated=False):
    """Save a participant under the account that created the meeting."""
    normalized_email = (email or "").strip().lower()
    normalized_name = (name or "").strip()
    if not normalized_email or not normalized_name:
        return

    try:
        scheduled_meeting = (
            models.ScheduledMeeting.objects.select_related("organizer")
            .filter(room_id=room_id)
            .first()
        )
        if scheduled_meeting:
            owner = scheduled_meeting.organizer
        else:
            owner_access = (
                models.ResourceAccess.objects.select_related("user")
                .filter(resource_id=room_id, role=models.RoleChoices.OWNER)
                .order_by("created_at")
                .first()
            )
            owner = owner_access.user if owner_access else None

        if owner is None:
            logger.warning("Unable to resolve contact owner for room %s", room_id)
            return

        linked_user = None
        if authenticated and participant_identity:
            linked_user = models.User.objects.filter(sub=participant_identity).first()

        models.AccountContact.objects.update_or_create(
            owner=owner,
            email=normalized_email,
            defaults={"name": normalized_name, "linked_user": linked_user},
        )
    except Exception:  # noqa: BLE001
        # Contact collection is intentionally best effort and must never affect meetings.
        logger.exception("Unable to save participant contact for room %s", room_id)
