"""Groq LLM access with strict JSON output.

Two things matter here:

* **Schema discipline.** Every node asks for a JSON object and validates it
  against a Pydantic model before the graph is allowed to continue. A QMS
  cannot accept "roughly shaped" data, so a malformed reply is repaired once
  and then treated as a failure rather than silently coerced.
* **Graceful degradation.** If no API key is configured, or Groq is down, we
  raise `LLMUnavailable` and the calling node falls back to a deterministic
  rule-based path. The response is then flagged `degraded=True` and the UI
  shows a banner - an operator must never be led to believe a heuristic
  result came from the model.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


# Failures that are worth retrying: the model or the service stumbled on this
# particular call, but nothing is wrong with the configuration.
#
# json_validate_failed matters most. Groq's JSON mode intermittently rejects
# its own generation with a 400 and an empty failed_generation, roughly one
# call in three under load. Treating that as "the LLM is unavailable" made a
# third of all runs fall back to rules while /api/ai/health still reported
# everything healthy - the degradation was real but nearly invisible.
_TRANSIENT_MARKERS = (
    "json_validate_failed",
    "rate_limit",
    "429",
    "500",
    "502",
    "503",
    "504",
    "timeout",
    "timed out",
    "overloaded",
    "connection",
    "temporarily unavailable",
)

# Failures where retrying is pointless - the configuration is wrong.
_PERMANENT_MARKERS = (
    "model_decommissioned",
    "model_not_found",
    "invalid_api_key",
    "authentication",
    "401",
    "403",
    "does not exist",
)


def _is_transient(exc: Exception) -> bool:
    text = str(exc).lower()
    if any(marker in text for marker in _PERMANENT_MARKERS):
        return False
    return any(marker in text for marker in _TRANSIENT_MARKERS)


class LLMUnavailable(RuntimeError):
    """Raised when Groq cannot be reached or refuses to return usable JSON."""


_client_cache: dict[str, object] = {}


def _get_client(model: str):
    """Lazily build (and memoise) a ChatGroq client for the given model."""
    if not settings.groq_api_key:
        raise LLMUnavailable("GROQ_API_KEY is not set")

    if model not in _client_cache:
        try:
            from langchain_groq import ChatGroq
        except ImportError as exc:  # pragma: no cover
            raise LLMUnavailable(f"langchain-groq not installed: {exc}") from exc

        _client_cache[model] = ChatGroq(
            model=model,
            api_key=settings.groq_api_key,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
    return _client_cache[model]


def _extract_json(raw: str) -> dict:
    """Pull a JSON object out of a model reply that may be fenced or prefixed."""
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("empty response")

    fenced = _FENCE_RE.search(raw)
    if fenced:
        raw = fenced.group(1).strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Last resort: take the outermost brace-balanced span.
    start = raw.find("{")
    if start == -1:
        raise ValueError("no JSON object in response")
    depth = 0
    for idx in range(start, len(raw)):
        if raw[idx] == "{":
            depth += 1
        elif raw[idx] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(raw[start : idx + 1])
    raise ValueError("unbalanced JSON object in response")


def structured_call(
    system_prompt: str,
    user_prompt: str,
    schema: Type[T],
    model: str | None = None,
) -> T:
    """Call Groq and return a validated instance of `schema`.

    One repair round-trip is allowed: if validation fails we hand the model its
    own output plus the validation error and ask for a corrected object.
    """
    model = model or settings.groq_model
    client = _get_client(model)

    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    system = (
        f"{system_prompt}\n\n"
        "Reply with a single JSON object and nothing else - no prose, no code "
        "fences, no explanation outside the JSON.\n"
        "The object MUST validate against this JSON Schema:\n"
        f"{schema_json}\n"
        "Use null for anything the source does not state. Never invent batch "
        "numbers, dates, names or quantities."
    )

    messages = [("system", system), ("human", user_prompt)]
    attempts = max(1, settings.llm_max_retries) + 1

    for attempt in range(2):
        reply = None
        last_error: Exception | None = None

        # Retry transient failures before giving up on the model entirely.
        for call in range(attempts):
            try:
                reply = client.invoke(messages)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not _is_transient(exc) or call == attempts - 1:
                    logger.warning(
                        "Groq call failed (%s, attempt %s/%s): %s",
                        model, call + 1, attempts, exc,
                    )
                    raise LLMUnavailable(str(exc)) from exc

                # Jittered backoff so parallel graph branches do not retry in
                # lockstep and re-collide.
                delay = 0.4 * (2**call) + random.uniform(0, 0.3)
                logger.info(
                    "Transient Groq failure (%s, attempt %s/%s), retrying in %.1fs: %s",
                    model, call + 1, attempts, delay, str(exc)[:120],
                )
                time.sleep(delay)

        if reply is None:  # pragma: no cover - defensive
            raise LLMUnavailable(str(last_error))

        content = getattr(reply, "content", "") or ""
        try:
            return schema.model_validate(_extract_json(content))
        except (ValueError, ValidationError) as exc:
            logger.warning(
                "Groq returned unusable JSON (attempt %s/2, model=%s): %s",
                attempt + 1,
                model,
                exc,
            )
            if attempt == 1:
                raise LLMUnavailable(f"schema validation failed: {exc}") from exc
            messages = messages + [
                ("ai", content[:4000]),
                (
                    "human",
                    "That response did not validate against the schema. "
                    f"Error:\n{exc}\n\nReturn ONLY the corrected JSON object.",
                ),
            ]

    raise LLMUnavailable("exhausted repair attempts")  # pragma: no cover


def llm_available() -> bool:
    return bool(settings.groq_api_key)


def check_models(timeout: float = 15.0) -> dict:
    """Verify the configured models are actually served by Groq.

    This exists because of a failure mode that cost real debugging time: Groq
    decommissioned `gemma2-9b-it`, every call started returning 400
    model_decommissioned, and each node dutifully caught it and fell back to
    rules. The system stayed up and kept producing plausible output, with
    nothing but a per-request WARNING to say the LLM had stopped being used at
    all.

    Degrading on a transient outage is correct. Degrading permanently because
    a model no longer exists is a configuration error, and it should be stated
    once, loudly, at startup - and surfaced in /api/ai/health - rather than
    inferred from a `degraded` flag on every response.

    Never raises: a failed check is reported, not fatal, because the API being
    briefly unreachable must not stop the service from starting.
    """
    result: dict = {
        "checked": False,
        "ok": False,
        "configured": [settings.groq_model, settings.groq_reasoning_model],
        "missing": [],
        "available": [],
        "error": None,
    }

    if not settings.groq_api_key:
        result["error"] = "GROQ_API_KEY is not set"
        return result

    try:
        from groq import Groq

        listing = Groq(api_key=settings.groq_api_key, timeout=timeout).models.list()
        available = sorted(m.id for m in listing.data)
    except Exception as exc:  # noqa: BLE001 - a check must never break startup
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    result["checked"] = True
    result["available"] = available
    result["missing"] = [m for m in result["configured"] if m not in available]
    result["ok"] = not result["missing"]
    return result
