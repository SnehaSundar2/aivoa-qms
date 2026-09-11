"""The conversational copilot.

One turn looks like this:

    user message
        |
        v
    route: is this a complaint to log, or a question to answer?
        |                                   |
        v                                   v
    log_complaint tool                 answer directly
    + full agent graph
        |
        v
    conversational reply + form_update

The routing decision is the point of the tool: "log this complaint: ..."
should populate the form, "what does Major severity mean?" should not. The
model makes that call, and the answer is reported back to the UI as
`tool_called` so the operator can see which happened.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import BaseModel, Field

from app.agent import heuristics, prompts
from app.agent.llm import LLMUnavailable, structured_call
from app.agent.tools import should_log_complaint
from app.core.config import settings
from app.core.enums import MANDATORY_FIELDS
from app.schemas import ChatMessage, ChatResponse, CopilotResult
from app.services.copilot import run_copilot

logger = logging.getLogger(__name__)


class _Route(BaseModel):
    """Whether this turn should call the log_complaint tool."""

    call_log_complaint: bool = Field(
        ..., description="True if the message describes a complaint to be logged"
    )
    reason: str = Field("", description="One short clause explaining the choice")


class _Reply(BaseModel):
    reply: str


def _history_text(history: list[ChatMessage], limit: int = 6) -> str:
    if not history:
        return ""
    recent = history[-limit:]
    lines = [f"{m.role}: {m.content[:500]}" for m in recent]
    return "Recent conversation:\n" + "\n".join(lines) + "\n\n"


def _route(message: str, history: list[ChatMessage]) -> tuple[bool, bool]:
    """Return `(should_call_tool, degraded)`."""
    try:
        decision = structured_call(
            "You decide whether a message to a pharmaceutical QMS copilot is a "
            "customer complaint that should be logged, or something else (a "
            "question, a follow-up, a greeting).\n\n"
            "Call the tool when the message reports a product defect, quality "
            "issue or customer complaint - even if details are missing.\n"
            "Do not call it for questions about the QMS, requests to explain "
            "something, or messages about a complaint already logged.",
            _history_text(history) + f"Message:\n{message}",
            _Route,
            model=settings.groq_model,
        )
        logger.info(
            "Route: call_log_complaint=%s (%s)",
            decision.call_log_complaint, decision.reason,
        )
        return decision.call_log_complaint, False
    except LLMUnavailable as exc:
        logger.info("Routing degraded: %s", exc)
        return should_log_complaint(message), True


def _compose_reply(
    result: CopilotResult, missing: list[str], degraded: bool
) -> tuple[str, bool]:
    """Write the assistant's confirmation after a successful tool call."""
    extracted = result.extracted
    facts = {
        "product": extracted.product_name,
        "strength": extracted.product_strength,
        "batch": extracted.batch_number,
        "defect": extracted.complaint_category,
        "quantity": extracted.affected_quantity,
        "customer": extracted.customer_name,
        "severity": result.risk.severity,
        "still_missing": missing,
    }

    try:
        reply = structured_call(
            prompts.CHAT_REPLY_PROMPT,
            "Record just extracted:\n"
            + "\n".join(f"{k}: {v}" for k, v in facts.items() if v),
            _Reply,
            model=settings.groq_model,
        )
        return reply.reply, degraded
    except LLMUnavailable as exc:
        logger.info("Reply composition degraded: %s", exc)
        # Deterministic fallback, deliberately plain.
        bits = []
        if extracted.product_name:
            bits.append(extracted.product_name)
        if extracted.batch_number:
            bits.append(f"batch {extracted.batch_number}")
        subject = ", ".join(bits) or "the complaint"

        reply = f"Complaint parsed. I've populated the form from {subject}"
        if result.risk.severity:
            reply += f" and assessed it as {result.risk.severity}"
        reply += "."
        if missing:
            pretty = ", ".join(f.replace("_", " ") for f in missing[:2])
            reply += f" Still needed before this can be committed: {pretty}."
        return reply, True


def _answer_question(message: str, history: list[ChatMessage], form: dict) -> tuple[str, bool]:
    filled = {k: v for k, v in form.items() if v not in (None, "", False, [])}
    context = ""
    if filled:
        context = (
            "For reference, the form currently holds:\n"
            + "\n".join(f"  {k}: {v}" for k, v in list(filled.items())[:15])
            + "\n\n"
        )

    try:
        reply = structured_call(
            prompts.CHAT_GENERAL_PROMPT,
            _history_text(history) + context + f"Message:\n{message}",
            _Reply,
            model=settings.groq_model,
        )
        return reply.reply, False
    except LLMUnavailable as exc:
        logger.info("Answer degraded: %s", exc)
        return (
            "I can't reach the language model right now, so I can only run the "
            "rule-based extraction. Paste the complaint text - the product, batch "
            "number, what was observed and how many units - and I'll populate the "
            "form from it.",
            True,
        )


def handle_turn(
    message: str, history: list[ChatMessage], form: dict[str, Any]
) -> ChatResponse:
    """Process one chat turn."""
    started = time.perf_counter()

    should_call, route_degraded = _route(message, history)

    if not should_call:
        reply, degraded = _answer_question(message, history, form)
        return ChatResponse(
            reply=reply,
            tool_called=None,
            form_update={},
            copilot=None,
            form_complete=not _missing_mandatory({**form}),
            degraded=degraded or route_degraded,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    # Run the full agent: tool call, then completeness, duplicates, risk,
    # root cause, CAPA and summary.
    result = run_copilot(
        raw_text=message,
        source_type=form.get("source_type") or "Direct Customer",
        source_reference=form.get("source_reference"),
        existing={k: v for k, v in form.items() if v not in (None, "", False, [])},
    )

    if not result.is_complaint:
        # The graph's own triage disagreed with the router. Trust the graph -
        # it saw the extraction attempt - and do not touch the form.
        reply, degraded = _answer_question(message, history, form)
        return ChatResponse(
            reply=reply,
            tool_called=None,
            form_update={},
            copilot=result,
            form_complete=False,
            degraded=degraded or route_degraded or result.degraded,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    merged = {**form, **result.form_prefill}
    missing = _missing_mandatory(merged)
    reply, reply_degraded = _compose_reply(result, missing, result.degraded)

    return ChatResponse(
        reply=reply,
        tool_called="log_complaint",
        form_update=result.form_prefill,
        copilot=result,
        form_complete=not missing,
        degraded=result.degraded or reply_degraded or route_degraded,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def _missing_mandatory(form: dict[str, Any]) -> list[str]:
    return [f for f in MANDATORY_FIELDS if not form.get(f)]


def greeting() -> str:
    """Opening message shown when the chat panel loads."""
    return (
        "Ready to process new complaints. You can paste the raw email from the "
        "customer, or upload a PDF of the complaint report. I will extract the "
        "data and run the initial risk assessment."
    )
