"""Celery tasks for the core app."""

from core.tasks.connection_test import delete_connection_test_room
from core.tasks.file import process_file_deletion
from core.tasks.scheduling import process_scheduled_meetings

__all__ = (
    "delete_connection_test_room",
    "process_file_deletion",
    "process_scheduled_meetings",
)
