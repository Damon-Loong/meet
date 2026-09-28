"""Reject truncated or refused completions before treating them as valid minutes."""

# ruff: noqa: D103

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from summary.core.llm_service import LLMException, LLMService


def service_with_response(reason="stop", content="测试结果", refusal=None):
    response = SimpleNamespace(
        id="response-test",
        model="test-model",
        usage=None,
        choices=[
            SimpleNamespace(
                finish_reason=reason,
                message=SimpleNamespace(content=content, refusal=refusal),
            )
        ],
    )
    observability = Mock(is_enabled=False)
    client = observability.get_openai_client.return_value
    client.chat.completions.create.return_value = response
    return LLMService(observability)


@pytest.mark.parametrize("reason", ["length", "content_filter", "tool_calls", None])
def test_nonfinal_response_is_rejected_even_when_content_is_valid_json(reason):
    service = service_with_response(reason, '{"valid":"json"}')
    with pytest.raises(LLMException, match="did not finish normally"):
        service.call("system", "source", "test")
    assert service.last_response_metadata["finish_reason"] == reason


@pytest.mark.parametrize("content", [None, "", "   "])
def test_empty_output_is_rejected(content):
    with pytest.raises(LLMException, match="empty content"):
        service_with_response(content=content).call("system", "source", "test")


def test_refusal_is_rejected():
    with pytest.raises(LLMException, match="refused"):
        service_with_response(refusal="no").call("system", "source", "test")


def test_success_records_metadata_without_prompt_content():
    service = service_with_response()
    assert service.call("system", "PRIVATE SOURCE", "test") == "测试结果"
    assert service.last_response_metadata["response_id"] == "response-test"
    assert "PRIVATE SOURCE" not in str(service.last_response_metadata)
