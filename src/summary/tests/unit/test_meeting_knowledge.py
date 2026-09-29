"""Offline contract tests for the documented AFB vector API."""

# ruff: noqa: D103
from unittest.mock import Mock

import pytest
import requests

from summary.core.meeting_knowledge import (
    KnowledgeError,
    MeetingKnowledgeClient,
    shared_namespace,
    transcript_documents,
)


@pytest.fixture()
def setup_client():
    session = Mock()
    session.request.return_value.status_code = 200
    client = MeetingKnowledgeClient(
        api_key="test-only",
        collection_id="vc_test",
        namespace="meet_scope",
        session=session,
    )
    return client, session


def test_scope_is_stable_and_separates_tenants():
    assert shared_namespace("a", "p") == shared_namespace("a", "p")
    assert shared_namespace("a", "p") != shared_namespace("b", "p")
    with pytest.raises(ValueError):
        shared_namespace("a", "")


def test_chunks_preserve_original_and_have_idempotent_ids():
    original = "会议原文\n" * 1000
    args = {"namespace": "meet_scope", "recording_id": "r1", "source_name": "测试"}
    docs = transcript_documents(original, **args)
    assert "".join(d["content"] for d in docs) == original
    assert docs == transcript_documents(original, **args)
    assert all(len(d["id"]) <= 64 for d in docs)
    assert docs[0]["id"] != transcript_documents(original + "修改", **args)[0]["id"]


def test_submit_does_not_reset_or_claim_indexing_complete(setup_client):
    client, session = setup_client
    session.request.return_value.json.return_value = {"job_id": "vwj_test"}
    docs = transcript_documents(
        "测试会议", namespace="meet_scope", recording_id="r1", source_name="测试"
    )
    assert client.submit(docs) == "vwj_test"
    assert session.request.call_args.kwargs["json"]["reset"] is False
    assert session.request.call_args.kwargs["allow_redirects"] is False


def test_reject_out_of_scope_write_before_network(setup_client):
    client, session = setup_client
    with pytest.raises(ValueError):
        client.submit([{"id": "x", "content": "test", "namespace": "other"}])
    session.request.assert_not_called()


def test_query_always_scoped_and_hybrid(setup_client):
    client, session = setup_client
    hit = {"id": "x", "content": "原文", "source_id": "r1", "namespace": "meet_scope"}
    session.request.return_value.json.return_value = {"results": [hit]}
    assert client.query("上次安排") == [hit]
    assert session.request.call_args.kwargs["json"] == {
        "query": "上次安排",
        "mode": "hybrid",
        "namespace": "meet_scope",
        "top_k": 5,
    }


@pytest.mark.parametrize("namespace", [None, "other"])
def test_query_fails_closed_on_scope_mismatch(setup_client, namespace):
    client, session = setup_client
    session.request.return_value.json.return_value = {
        "results": [{"namespace": namespace, "content": "private", "source_id": "r1"}]
    }
    with pytest.raises(KnowledgeError):
        client.query("test")


@pytest.mark.parametrize("status", [302, 401, 500])
def test_http_errors_not_silently_empty_or_followed(setup_client, status):
    client, session = setup_client
    session.request.return_value.status_code = status
    with pytest.raises(KnowledgeError):
        client.query("test")


def test_timeout_is_sanitized(setup_client):
    client, session = setup_client
    session.request.side_effect = requests.Timeout("private provider response")
    with pytest.raises(KnowledgeError, match="unavailable") as error:
        client.query("test")
    assert "private" not in str(error.value)


def test_job_status_retains_failure_counts(setup_client):
    client, session = setup_client
    session.request.return_value.json.return_value = {
        "job": {
            "id": "vwj_test",
            "status": "completed",
            "total": 2,
            "processed": 2,
            "upserted": 1,
            "failed": 1,
            "errors": ["private"],
        }
    }
    result = client.job_status("vwj_test")
    assert result["failed"] == 1
    assert "errors" not in result


def test_insecure_base_rejected():
    with pytest.raises(ValueError):
        MeetingKnowledgeClient(
            api_key="test",
            collection_id="vc_test",
            namespace="scope",
            base_url="http://afb.mbmzone.com/afb-agent/v1",
        )
