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
        json={
            "name": "小李",
            "aliases": ["李明"],
            "account": "account-1",
            "email": "li@example.com",
        },
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


def test_self_tasks_are_scoped_by_exact_participant_email(setup):
    client, memory, _ = setup
    roster = [
        {"identity": "account-a", "name": "小王", "email": "wang@example.com"},
        {"identity": "account-b", "name": "小李", "email": "li@example.com"},
    ]
    memory.register(roster)
    people = {person["name"]: person["id"] for person in memory.people()}
    quotes = {
        "小王": "- **[00:01:00] 小王：** 我整理说明。",
        "小李": "- **[00:02:00] 小李：** 我检查清单。",
    }
    facts = [
        {
            "person_id": people[name], "item_id": "", "kind": "task",
            "text": text, "status": "pending", "deadline": "", "quote": quotes[name],
        }
        for name, text in (("小王", "整理说明"), ("小李", "检查清单"))
    ]
    transcript = (
        "| 会议开始 | 2026-10-12 10:00:00 |\n## 参会人员\n小王、小李\n"
        "## 逐字转录\n" + "\n".join(quotes.values())
    )
    response = json.dumps({"facts": facts}, ensure_ascii=False)
    memory.ingest_summary("**小王**\n- [ ] 整理说明\n**小李**\n- [ ] 检查清单", transcript, "meeting-one", roster)
    url = URL + "/self/tasks"
    response = client.post(url, headers=HEADERS, json={"email": "WANG@example.com"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["text"] for item in items] == ["整理说明"]
    item = items[0]
    changed = client.post(
        f"{url}/{item['item']}/status", headers=HEADERS,
        json={"email": "wang@example.com", "revision": item["seq"], "completed": True},
    )
    assert changed.status_code == 200
    assert changed.json()["item"]["status"] == "completed"
    forbidden = client.post(
        f"{url}/{item['item']}/status", headers=HEADERS,
        json={
            "email": "li@example.com",
            "revision": changed.json()["item"]["seq"],
            "completed": False,
        },
    )
    assert forbidden.status_code == 404
    unauthenticated = client.post(url, json={"email": "wang@example.com"})
    assert unauthenticated.status_code in {401, 403}


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
