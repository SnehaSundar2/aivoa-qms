"""Tests for the Groq wrapper.

These matter because the LLM path cannot be exercised in CI against the real
API. The parsing and repair logic is where the bugs actually live, so it is
tested against a stub client that reproduces the ways a model misbehaves:
code fences, chatty preambles, and schema violations.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.agent import llm
from app.agent.llm import LLMUnavailable, _extract_json, structured_call


class _Schema(BaseModel):
    name: str
    count: int


class _Reply:
    def __init__(self, content: str) -> None:
        self.content = content


class _StubClient:
    """Returns each queued reply in turn and records what it was sent."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(messages)
        if not self.replies:
            raise AssertionError("stub client called more times than expected")
        return _Reply(self.replies.pop(0))


@pytest.fixture
def stub(monkeypatch):
    def _install(*replies: str) -> _StubClient:
        client = _StubClient(*replies)
        monkeypatch.setattr(llm, "_get_client", lambda model: client)
        return client

    return _install


# --- _extract_json --------------------------------------------------------
@pytest.mark.parametrize(
    "raw",
    [
        '{"name": "a", "count": 1}',
        '```json\n{"name": "a", "count": 1}\n```',
        '```\n{"name": "a", "count": 1}\n```',
        'Sure! Here is the JSON:\n{"name": "a", "count": 1}',
        '{"name": "a", "count": 1}\n\nLet me know if you need anything else.',
    ],
)
def test_extract_json_handles_common_model_wrappers(raw):
    assert _extract_json(raw) == {"name": "a", "count": 1}


def test_extract_json_handles_nested_braces():
    raw = 'Here:\n{"name": "a", "count": 1, "meta": {"nested": {"deep": true}}}'
    assert _extract_json(raw)["meta"]["nested"]["deep"] is True


@pytest.mark.parametrize("raw", ["", "no json here", "{unbalanced"])
def test_extract_json_rejects_garbage(raw):
    with pytest.raises(ValueError):
        _extract_json(raw)


# --- structured_call ------------------------------------------------------
def test_structured_call_returns_validated_model(stub):
    stub('{"name": "widget", "count": 3}')
    result = structured_call("sys", "user", _Schema, model="test-model")
    assert result.name == "widget"
    assert result.count == 3


def test_schema_is_injected_into_the_system_prompt(stub):
    client = stub('{"name": "a", "count": 1}')
    structured_call("BE A ROBOT", "user", _Schema, model="test-model")

    system = client.calls[0][0][1]
    assert "BE A ROBOT" in system
    assert '"count"' in system, "the JSON schema must reach the model"


def test_structured_call_repairs_an_invalid_first_response(stub):
    # First reply is missing `count`; the repair round-trip fixes it.
    client = stub('{"name": "widget"}', '{"name": "widget", "count": 7}')
    result = structured_call("sys", "user", _Schema, model="test-model")

    assert result.count == 7
    assert len(client.calls) == 2

    repair_turn = client.calls[1][-1]
    assert repair_turn[0] == "human"
    assert "did not validate" in repair_turn[1]


def test_structured_call_gives_up_after_one_repair(stub):
    client = stub('{"name": "a"}', '{"still": "broken"}')
    with pytest.raises(LLMUnavailable, match="schema validation failed"):
        structured_call("sys", "user", _Schema, model="test-model")
    assert len(client.calls) == 2, "must not retry forever"


def test_transport_errors_become_llm_unavailable(monkeypatch):
    class _Exploding:
        def invoke(self, messages):
            raise RuntimeError("connection reset")

    monkeypatch.setattr(llm, "_get_client", lambda model: _Exploding())
    with pytest.raises(LLMUnavailable, match="connection reset"):
        structured_call("sys", "user", _Schema, model="test-model")


def test_missing_api_key_is_reported_as_unavailable(monkeypatch):
    monkeypatch.setattr(llm.settings, "groq_api_key", "")
    llm._client_cache.clear()
    with pytest.raises(LLMUnavailable, match="GROQ_API_KEY"):
        structured_call("sys", "user", _Schema, model="test-model")
