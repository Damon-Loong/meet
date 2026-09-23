"""Tests for the meeting-scoped attendee cache."""

from uuid import uuid4

from core.services.meeting_participants import MeetingParticipantsCache


def test_meeting_participant_roster_add_update_and_clear():
    room_id = uuid4()
    store = MeetingParticipantsCache()

    store.add(room_id, "RM_first", "identity-1", "Long", "long@example.com")
    store.add(room_id, "RM_first", "identity-2", "Guest", "")
    store.add(room_id, "RM_first", "identity-1", "Long Updated", "long@example.com")

    attendees = {item["identity"]: item for item in store.get(room_id, "RM_first")}
    assert attendees == {
        "identity-1": {
            "identity": "identity-1",
            "name": "Long Updated",
            "email": "long@example.com",
        },
        "identity-2": {"identity": "identity-2", "name": "Guest", "email": ""},
    }

    store.clear(room_id)
    assert store.get(room_id, "RM_first") == []


def test_meeting_participant_rosters_are_isolated_by_room():
    first_room, second_room = uuid4(), uuid4()
    store = MeetingParticipantsCache()
    store.add(first_room, "RM_first", "same-identity", "First", "first@example.com")
    store.add(second_room, "RM_second", "same-identity", "Second", "second@example.com")

    assert store.get(first_room, "RM_first")[0]["name"] == "First"
    assert store.get(second_room, "RM_second")[0]["name"] == "Second"


def test_meeting_participant_rosters_are_isolated_by_livekit_room_sid():
    room_id = uuid4()
    store = MeetingParticipantsCache()
    store.add(room_id, "RM_first", "same-identity", "Earlier", "old@example.com")
    store.add(room_id, "RM_second", "same-identity", "Current", "new@example.com")

    assert store.get(room_id, "RM_first")[0]["email"] == "old@example.com"
    assert store.get(room_id, "RM_second") == [
        {"identity": "same-identity", "name": "Current", "email": "new@example.com"}
    ]
    assert store.get(room_id, "") == []
