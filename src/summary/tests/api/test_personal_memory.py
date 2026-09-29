"""Administrative memory APIs require tenant credentials and preserve audit history."""

# ruff: noqa: D103
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from summary.core.config import get_settings
from summary.core.personal_memory import PersonalMemory
from summary.main import app


@pytest.fixture
def setup(tmp_path):
    original = dict(app.dependency_overrides)
    settings = get_settings().model_copy(
        update={
            "personal_memory_enabled": True,
            "meeting_memory_tenant_id": "test-tenant",
            "meeting_memory_state_file": str(tmp_path / "state.sqlite3"),
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    memory = PersonalMemory(settings.meeting_memory_state_file, "test-tenant")
    try:
        yield TestClient(app), memory, settings
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)


HEADERS = {"Authorization": "Bearer test-api-token"}
URL = "/api/v2/personal-memory"


def test_auth_required(setup):
    client, _, _ = setup
    assert client.get(URL).status_code in {401, 403}
    assert client.get(URL, headers={"Authorization": "Bearer wrong"}).status_code == 403
    assert client.get(URL, headers=HEADERS).json() == {"people": [], "items": []}


def test_disabled_or_unapproved_tenant_rejected(setup):
    client, _, settings = setup
    for change in (
        {"personal_memory_enabled": False},
        {"meeting_memory_tenant_id": "another"},
    ):
        app.dependency_overrides[get_settings] = lambda change=change: (
            settings.model_copy(update=change)
        )
        assert client.get(URL, headers=HEADERS).status_code == 403


def test_create_correct_audit_and_stale_revision(setup):
    client, memory, _ = setup
    response = client.post(
        URL + "/people",
        headers=HEADERS,
        json={"name": "小李", "aliases": ["李明"], "account": "account-1"},
    )
    assert response.status_code == 200
    person = response.json()["id"]
    quote = "- **[00:01:00] 小李：** 我整理操作说明。"
    transcript = "| 会议开始 | 2026-09-20 |\n## 参会人员\n小李\n## 逐字转录\n" + quote
    fact = {
        "person_id": person,
        "item_id": "",
        "kind": "task",
        "text": "整理说明",
        "status": "pending",
        "deadline": "",
        "quote": quote,
    }
    memory.ingest(
        transcript, "meeting-one", [], Mock(return_value=json.dumps({"facts": [fact]}))
    )
    item = client.get(URL, headers=HEADERS).json()["items"][0]
    correction = {
        "revision": item["seq"],
        "person": person,
        "text": "整理操作说明",
        "status": "completed",
        "deadline": "",
        "reason": "本人确认已完成",
    }
    path = URL + "/items/" + item["item"]
    assert client.patch(path, headers=HEADERS, json=correction).status_code == 200
    assert client.patch(path, headers=HEADERS, json=correction).status_code == 409
    history = client.get(path + "/history", headers=HEADERS).json()
    assert len(history) == 2 and history[-1]["reason"] == "本人确认已完成"
    assert (
        client.patch(
            URL + "/items/not-here", headers=HEADERS, json=correction
        ).status_code
        == 404
    )


def test_admin_page_contains_no_secrets_and_is_disabled_by_default(setup, monkeypatch):
    from summary import main  # noqa: PLC0415

    client, _, settings = setup
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: settings.model_copy(update={"personal_memory_enabled": False}),
    )
    assert client.get("/memory-admin").status_code == 404
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    response = client.get("/memory-admin")
    assert response.status_code == 200
    assert "test-api-token" not in response.text
    assert "localStorage" not in response.text
    assert response.headers["cache-control"] == "no-store"
