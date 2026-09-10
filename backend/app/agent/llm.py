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
import re
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


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

    for attempt in range(2):
        try:
            reply = client.invoke(messages)
        except Exception as exc:  # noqa: BLE001 - network/auth/rate-limit all land here
            logger.warning("Groq call failed (%s): %s", model, exc)
            raise LLMUnavailable(str(exc)) from exc

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
