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


@pytest.fixture(autouse=True)
def _clean_breaker():
    """The breaker is module state - reset it around every test."""
    llm.reset_breaker()
    yield
    llm.reset_breaker()


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
    # Sent as a compact field spec, not model_json_schema() - same information,
    # about a third of the tokens.
    assert "count (integer, required)" in system
    assert "name (string, required)" in system
    assert "anyOf" not in system, "the verbose JSON Schema envelope must not be sent"


def test_compact_schema_is_materially_smaller_than_json_schema():
    """The reason the field spec exists: Groq's free tier is 200k tokens/day."""
    import json

    from app.agent.schema_text import compact_schema
    from app.schemas import ExtractedComplaint

    verbose = json.dumps(ExtractedComplaint.model_json_schema(), indent=2)
    tight = compact_schema(ExtractedComplaint)

    assert len(tight) < len(verbose) / 2, "should be at least twice as compact"

    # ...and it must still carry every field and its guidance.
    for field in ExtractedComplaint.model_fields:
        assert field in tight
    assert "CHANNEL the complaint arrived through" in tight


def test_compact_schema_expands_nested_models():
    from pydantic import BaseModel

    from app.agent.schema_text import compact_schema
    from app.schemas import RootCause

    class _List(BaseModel):
        root_causes: list[RootCause]

    text = compact_schema(_List)
    assert "array of RootCause" in text
    assert "RootCause fields:" in text
    assert "investigation_step" in text


def test_daily_quota_is_not_retried(monkeypatch):
    """A per-day cap will not clear for hours; retrying only delays the fallback."""
    from app.agent.llm import _is_transient

    per_minute = (
        "Error code: 429 - rate_limit_exceeded: Limit 30000 on tokens per minute (TPM)"
    )
    per_day = (
        "Error code: 429 - rate_limit_exceeded: Limit 200000 on tokens per day (TPD)"
    )

    assert _is_transient(Exception(per_minute)) is True
    assert _is_transient(Exception(per_day)) is False


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


# --- quota circuit breaker -------------------------------------------------
# Without it, every node in the graph discovered the exhausted quota
# independently: seven nodes, seven round trips, each waiting for its own 429.
# A degraded run took 57 seconds instead of milliseconds.
DAILY_CAP_ERROR = (
    "Error code: 429 - {'error': {'message': 'Rate limit reached for model "
    "`openai/gpt-oss-20b` ... on tokens per day (TPD): Limit 200000, Used "
    "199992, Requested 605. Please try again in 4m17.904s.', "
    "'code': 'rate_limit_exceeded'}}"
)


def test_daily_cap_opens_the_breaker_and_later_calls_skip_the_network(monkeypatch):
    client = _FlakyClient(DAILY_CAP_ERROR, fail_times=99, payload="{}")
    monkeypatch.setattr(llm, "_get_client", lambda model: client)
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)

    # First call reaches Groq and learns the quota is gone.
    with pytest.raises(LLMUnavailable):
        structured_call("sys", "user", _Schema, model="test-model")
    assert client.calls == 1, "a daily cap must not be retried"
    assert llm.breaker_state()["open"] is True

    # Every later call fails instantly without a round trip.
    for _ in range(5):
        with pytest.raises(LLMUnavailable, match="quota"):
            structured_call("sys", "user", _Schema, model="test-model")
    assert client.calls == 1, "breaker must short-circuit before invoking"


def test_breaker_uses_the_wait_groq_reports():
    llm._open_breaker(DAILY_CAP_ERROR)
    remaining = llm.breaker_state()["seconds_remaining"]
    # 4m17.9s plus a small margin.
    assert 255 <= remaining <= 275


def test_breaker_falls_back_to_a_default_wait_when_none_is_given():
    llm._open_breaker("429 tokens per day exceeded")
    assert llm.breaker_state()["seconds_remaining"] > 600


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Please try again in 4m17.904s", 263),
        ("Please try again in 32.5s", 38),
        ("Please try again in 1m0s", 65),
    ],
)
def test_retry_after_parsing(text, expected):
    assert round(llm._parse_retry_after(text)) == expected


def test_a_successful_call_closes_the_breaker(monkeypatch):
    llm._open_breaker(DAILY_CAP_ERROR)
    assert llm.breaker_state()["open"] is True

    # Pretend the cooldown elapsed, then let a call succeed.
    llm.reset_breaker()
    client = _FlakyClient("unused", fail_times=0, payload='{"name": "a", "count": 1}')
    monkeypatch.setattr(llm, "_get_client", lambda model: client)

    structured_call("sys", "user", _Schema, model="test-model")
    assert llm.breaker_state()["open"] is False


def test_breaker_does_not_open_for_a_per_minute_limit(monkeypatch):
    """A burst limit clears in seconds - it must not pause the whole agent."""
    per_minute = "Error code: 429 - rate_limit_exceeded on tokens per minute (TPM)"
    client = _FlakyClient(per_minute, fail_times=1, payload='{"name": "a", "count": 1}')
    monkeypatch.setattr(llm, "_get_client", lambda model: client)
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)

    result = structured_call("sys", "user", _Schema, model="test-model")

    assert result.count == 1
    assert client.calls == 2, "a per-minute limit should be retried"
    assert llm.breaker_state()["open"] is False


# --- half-open probing -----------------------------------------------------
# The first version of the breaker had no way to discover that the quota had
# recovered: it held the agent in rule-based mode for the full cooldown even
# when a single call would have succeeded. Groq's free tier replenishes
# continuously, so the wait it reports is a worst case, not a reset time.
def test_no_probe_is_allowed_immediately_after_opening():
    llm.reset_breaker()
    llm._open_breaker("429 tokens per day (TPD). Please try again in 4m17.904s")

    assert llm.breaker_state()["open"] is True
    assert llm.breaker_state()["probe_due"] is False
    assert not any(llm._claim_probe() for _ in range(7))


def test_exactly_one_probe_is_claimed_when_one_is_due():
    """A seven-node graph must cost one test call, not seven round trips."""
    import time

    llm.reset_breaker()
    llm._open_breaker("429 tokens per day (TPD). Please try again in 4m17.904s")
    llm._breaker_next_probe = time.time() - 1  # a probe is now due

    claims = [llm._claim_probe() for _ in range(7)]
    assert sum(claims) == 1


def test_the_probe_interval_is_shorter_than_the_reported_wait():
    """Otherwise the probe never happens before the cooldown expires anyway."""
    llm.reset_breaker()
    llm._open_breaker("429 tokens per day (TPD). Please try again in 4m17.904s")

    state = llm.breaker_state()
    assert state["seconds_remaining"] > llm._PROBE_INTERVAL_SECONDS


def test_a_successful_probe_closes_the_breaker(monkeypatch):
    import time

    llm.reset_breaker()
    llm._open_breaker("429 tokens per day (TPD). Please try again in 4m17.904s")
    llm._breaker_next_probe = time.time() - 1

    client = _FlakyClient("unused", fail_times=0, payload='{"name": "a", "count": 1}')
    monkeypatch.setattr(llm, "_get_client", lambda model: client)

    result = structured_call("sys", "user", _Schema, model="test-model")

    assert result.count == 1
    assert llm.breaker_state()["open"] is False, "a working call must close it"


def test_a_failed_probe_leaves_the_breaker_open(monkeypatch):
    import time

    llm.reset_breaker()
    llm._open_breaker("429 tokens per day (TPD). Please try again in 4m17.904s")
    llm._breaker_next_probe = time.time() - 1

    client = _FlakyClient(
        "429 tokens per day (TPD). Please try again in 2m0s", fail_times=99, payload="{}"
    )
    monkeypatch.setattr(llm, "_get_client", lambda model: client)
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)

    with pytest.raises(LLMUnavailable):
        structured_call("sys", "user", _Schema, model="test-model")

    assert llm.breaker_state()["open"] is True
    assert client.calls == 1, "the probe is a single call, not a retry storm"
