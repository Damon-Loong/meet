"""Meeting-scoped Redis storage for participants who joined a room."""

import json
from uuid import UUID

from django.core.cache import cache


class MeetingParticipantsCache:
    """Keep one deduplicated attendee roster in Redis for each meeting."""

    KEY_PREFIX = "meeting-participants"
    FALLBACK_TTL_SECONDS = 30 * 24 * 60 * 60

    @classmethod
    def _get_key(cls, room_id: UUID | str) -> str:
        return cache.client.make_key(f"{cls.KEY_PREFIX}_{room_id!s}")

    @staticmethod
    def _redis(write: bool = True):
        return cache.client.get_client(write=write)

    def add(
        self,
        room_id: UUID | str,
        room_sid: str,
        identity: str,
        name: str,
        email: str = "",
    ):
        """Add or refresh a participant, keyed by LiveKit room and identity."""
        if not room_sid or not identity:
            return

        attendee = {
            "identity": identity,
            "name": name or identity,
            "email": email or "",
        }
        key = self._get_key(room_id)
        pipe = self._redis().pipeline(transaction=False)
        pipe.hset(
            key, f"{room_sid}:{identity}", json.dumps(attendee, ensure_ascii=False)
        )
        pipe.expire(key, self.FALLBACK_TTL_SECONDS)
        pipe.execute()

    def get(self, room_id: UUID | str, room_sid: str) -> list[dict[str, str]]:
        """Return attendees captured during one LiveKit room instance."""
        entries = self._redis(write=False).hgetall(self._get_key(room_id))
        attendees = []
        prefix = f"{room_sid}:"
        for field, value in entries.items():
            if isinstance(field, bytes):
                field = field.decode("utf-8")
            # A missing SID identifies recordings created before this change.
            if room_sid and not field.startswith(prefix):
                continue
            if not room_sid and ":" in field:
                continue

            if isinstance(value, bytes):
                value = value.decode("utf-8")
            try:
                attendee = json.loads(value)
            except (TypeError, ValueError):
                continue
            if isinstance(attendee, dict):
                attendees.append(attendee)
        return attendees

    def clear(self, room_id: UUID | str) -> None:
        """Delete the meeting attendee roster after expiry or cancellation."""
        self._redis().delete(self._get_key(room_id))
