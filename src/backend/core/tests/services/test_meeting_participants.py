"""Tests for the meeting-scoped attendee cache."""

from uuid import uuid4

from core.services.meeting_participants import MeetingParticipantsCache


def test_meeting_participant_roster_add_update_and_clear():
    room_id = uuid4()
    store = MeetingParticipantsCache()

    store.add(room_id, "identity-1", "Long", "long@example.com")
    store.add(room_id, "identity-2", "Guest", "")
    store.add(room_id, "identity-1", "Long Updated", "long@example.com")

    attendees = {item["identity"]: item for item in store.get(room_id)}
    assert attendees == {
        "identity-1": {
            "identity": "identity-1",
            "name": "Long Updated",
            "email": "long@example.com",
        },
        "identity-2": {"identity": "identity-2", "name": "Guest", "email": ""},
    }

    store.clear(room_id)
    assert store.get(room_id) == []


def test_meeting_participant_rosters_are_isolated_by_room():
    first_room, second_room = uuid4(), uuid4()
    store = MeetingParticipantsCache()
    store.add(first_room, "same-identity", "First", "first@example.com")
    store.add(second_room, "same-identity", "Second", "second@example.com")

    assert store.get(first_room)[0]["name"] == "First"
    assert store.get(second_room)[0]["name"] == "Second"
