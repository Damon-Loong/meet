"""Isolate persistent email checkpoints from production paths."""

import pytest


@pytest.fixture(autouse=True)
def isolated_delivery_storage(monkeypatch, tmp_path):
    """Never share delivery state between unit tests."""
    from summary.core import celery_worker, email_service  # noqa: PLC0415

    for module in (celery_worker, email_service):
        monkeypatch.setattr(
            module,
            "settings",
            module.settings.model_copy(
                update={"meeting_memory_state_file": str(tmp_path / "memory.sqlite3")}
            ),
        )
