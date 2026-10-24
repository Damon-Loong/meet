"""The unlimited default accepts long recordings without changing opt-in limits."""

import pytest

from summary.core.config import get_settings
from summary.core.file_service import FileService, MediaDurationTooLongError


@pytest.mark.parametrize("duration", [7200, 7201, 10800, 43200])
def test_unset_duration_limit_accepts_long_meetings(monkeypatch, duration):
    monkeypatch.delenv("RECORDING_MAX_DURATION", raising=False)
    settings = type(get_settings())()
    assert settings.recording_max_duration is None
    service = FileService.__new__(FileService)
    service._max_duration_seconds = settings.recording_max_duration
    service._validate_duration(duration)


def test_explicit_duration_limit_remains_supported():
    service = FileService.__new__(FileService)
    service._max_duration_seconds = 7200
    service._validate_duration(7200)
    with pytest.raises(MediaDurationTooLongError):
        service._validate_duration(7201)
