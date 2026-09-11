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
from app.agent.llm import (
    LLMUnavailable,
    _extract_json,
    _is_transient,
    structured_call,
)


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


# --- transient vs permanent failures --------------------------------------
# Groq's JSON mode intermittently rejects its own generation with
# 400 json_validate_failed. Treating that as "unavailable" made roughly a
# third of all runs fall back to rules while health checks stayed green.
@pytest.mark.parametrize(
    "message",
    [
        "Error code: 400 - {'code': 'json_validate_failed'}",
        "Error code: 429 - rate_limit_exceeded",
        "503 Service Unavailable",
        "Read timed out",
        "Connection reset by peer",
        "The service is overloaded",
    ],
)
def test_transient_failures_are_recognised(message):
    assert _is_transient(Exception(message)) is True


@pytest.mark.parametrize(
    "message",
    [
        "Error code: 400 - {'code': 'model_decommissioned'}",
        "Error code: 404 - {'code': 'model_not_found'}",
        "401 authentication_error: invalid_api_key",
        "The model `x` does not exist",
    ],
)
def test_permanent_failures_are_not_retried(message):
    """A wrong model or bad key will never succeed - failing fast is correct."""
    assert _is_transient(Exception(message)) is False


class _FlakyClient:
    """Fails with `error` for the first `fail_times` calls, then succeeds."""

    def __init__(self, error: str, fail_times: int, payload: str):
        self.error = error
        self.fail_times = fail_times
        self.payload = payload
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError(self.error)
        return _Reply(self.payload)


def test_transient_failure_is_retried_and_succeeds(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_max_retries", 3)
    client = _FlakyClient(
        "Error code: 400 - {'code': 'json_validate_failed'}",
        fail_times=2,
        payload='{"name": "widget", "count": 4}',
    )
    monkeypatch.setattr(llm, "_get_client", lambda model: client)
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)  # no real backoff

    result = structured_call("sys", "user", _Schema, model="test-model")

    assert result.count == 4
    assert client.calls == 3, "should have retried twice before succeeding"


def test_permanent_failure_fails_on_the_first_call(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_max_retries", 3)
    client = _FlakyClient(
        "Error code: 400 - {'code': 'model_decommissioned'}",
        fail_times=99,
        payload="{}",
    )
    monkeypatch.setattr(llm, "_get_client", lambda model: client)
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)

    with pytest.raises(LLMUnavailable, match="model_decommissioned"):
        structured_call("sys", "user", _Schema, model="test-model")

    assert client.calls == 1, "a decommissioned model must not be retried"


def test_transient_failure_eventually_gives_up(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_max_retries", 2)
    client = _FlakyClient("503 Service Unavailable", fail_times=99, payload="{}")
    monkeypatch.setattr(llm, "_get_client", lambda model: client)
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)

    with pytest.raises(LLMUnavailable):
        structured_call("sys", "user", _Schema, model="test-model")

    assert client.calls == 3, "max_retries + 1 attempts, then degrade"
