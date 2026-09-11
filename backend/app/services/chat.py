"""The conversational copilot.

One turn looks like this:

    user message
        |
        v
    cheap deterministic gate: could this be a complaint at all?
        |                                   |
     no |                                   | maybe
        v                                   v
    answer directly                    the agent graph
                                   (triage decides for real,
                                    then log_complaint + assessment)
                                            |
                                            v
                                 conversational reply + form_update

Routing happens in two stages on purpose. The gate here is keyword-based and
only has to be right about the obvious cases - a plain question never reaches
the graph. The real decision belongs to the graph's `triage` node, which has
seen the extraction attempt. An LLM router at this level was duplicating that
call for no added accuracy, which matters: Groq's free tier allows 200,000
tokens per day and a full run makes several calls.

Whichever path runs is reported to the UI as `tool_called`, so the operator
can see whether the form was touched.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import BaseModel, Field

from app.agent import heuristics, prompts
from app.agent.llm import LLMUnavailable, structured_call
from app.agent.edit_parser import parse_edit_instruction
from app.agent.tools import (
    EDITABLE_FIELDS,
    run_edit_complaint,
    should_edit_complaint,
    should_log_complaint,
)
from app.core.config import settings
from app.core.enums import MANDATORY_FIELDS
from app.schemas import ChatMessage, ChatResponse, ComplaintEdit, CopilotResult
from app.services.copilot import run_copilot

logger = logging.getLogger(__name__)


class _Reply(BaseModel):
    reply: str


def _history_text(history: list[ChatMessage], limit: int = 6) -> str:
    if not history:
        return ""
    recent = history[-limit:]
    lines = [f"{m.role}: {m.content[:500]}" for m in recent]
    return "Recent conversation:\n" + "\n".join(lines) + "\n\n"


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


def _apply_edit(
    message: str, form: dict[str, Any]
) -> tuple[dict[str, Any], list[str], ComplaintEdit | None, str | None, bool]:
    """Run the edit tool.

    Returns (updates, changed_fields, edit, error, degraded).
    """
    degraded = False
    try:
        edit = run_edit_complaint(message, form)
    except LLMUnavailable as exc:
        # Fall back to the deterministic parser, which handles instructions
        # that name their field and value outright ("set severity to
        # Critical"). It returns None for anything looser, and then we refuse:
        # guessing at an edit to a regulated record is worse than declining it.
        edit = parse_edit_instruction(message)
        if edit is None:
            logger.info("Edit unavailable and instruction not parseable: %s", exc)
            return {}, [], None, str(exc), True
        logger.info("Edit applied by deterministic parser: %s", edit.change_summary)
        degraded = True

    updates: dict[str, Any] = {}

    for field, value in edit.model_dump().items():
        if field not in EDITABLE_FIELDS:
            continue
        if value in (None, ""):
            continue
        # Only count it as a change if it differs from what is on screen.
        if str(form.get(field) or "") == str(value):
            continue
        updates[field] = value

    # Explicit blanking is a separate instruction from "leave it alone".
    for field in edit.fields_to_clear:
        if field in EDITABLE_FIELDS and form.get(field):
            updates[field] = ""

    return updates, sorted(updates), edit, None, degraded


def _handle_edit(
    message: str, history: list[ChatMessage], form: dict[str, Any], started: float
) -> ChatResponse:
    updates, changed, edit, error, parse_degraded = _apply_edit(message, form)

    if error:
        return ChatResponse(
            reply=(
                "I couldn't apply that edit - the language model is unavailable, and "
                "guessing at which field you meant risks corrupting the record. "
                "Please edit the field directly, or try again shortly."
            ),
            tool_called=None,
            form_update={},
            fields_changed=[],
            copilot=None,
            form_complete=not _missing_mandatory(form),
            degraded=True,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    if not changed:
        # The tool understood the instruction but nothing moved - usually the
        # field already holds that value, or is already blank. Saying "I
        # couldn't tell which field you meant" there is simply wrong.
        named = edit is not None and (
            edit.fields_to_clear
            or any(
                value not in (None, "")
                for field, value in edit.model_dump().items()
                if field in EDITABLE_FIELDS
            )
        )
        if named:
            detail = edit.change_summary or "that field"
            message_text = (
                f"No change needed - {detail} already matches what you asked for."
            )
        else:
            message_text = (
                "I couldn't tell which field you wanted to change. Name it directly - "
                "for example \"set the affected quantity to 20 capsules\" or "
                "\"change the batch number to AMX240603\"."
            )

        return ChatResponse(
            reply=message_text,
            tool_called="edit_complaint",
            form_update={},
            fields_changed=[],
            copilot=None,
            form_complete=not _missing_mandatory(form),
            degraded=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    merged = {**form, **updates}
    copilot = None
    degraded = parse_degraded

    # Re-grade only when the defect itself moved. A corrected contact name must
    # not cost a full assessment run.
    reassessment_skipped = False
    if edit and edit.reassess_risk:
        logger.info("Edit triggered re-assessment: %s", edit.change_summary)
        copilot = run_copilot(
            raw_text=_record_as_text(merged),
            source_type=merged.get("source_type") or "Direct Customer",
            source_reference=merged.get("source_reference"),
            existing={k: v for k, v in merged.items() if v not in (None, "", False, [])},
        )
        degraded = degraded or copilot.degraded

        had_assessment = bool(form.get("initial_risk_assessment"))

        if copilot.degraded and had_assessment:
            # The record already carries a model-written assessment and this
            # re-run could only produce keyword output. Overwriting it would
            # replace reasoning with "Rule match on quality-defect indicators:
            # seal" - strictly worse information in a regulated field. Keep
            # what is there and tell the operator it needs another look.
            logger.warning(
                "Skipping re-assessment write: the re-run was rule-based and the "
                "record already holds a model-written assessment."
            )
            reassessment_skipped = True
        else:
            for field in ("severity", "risk_score", "suggested_next_action",
                          "initial_risk_assessment", "regulatory_reportable",
                          "regulatory_rationale", "due_date"):
                value = copilot.form_prefill.get(field)
                if value not in (None, "") and str(merged.get(field) or "") != str(value):
                    updates[field] = value

        changed = sorted(updates)
        merged = {**form, **updates}

    reply, reply_degraded = _compose_edit_reply(
        edit, changed, merged, bool(copilot) and not reassessment_skipped
    )
    if reassessment_skipped:
        reply += (
            " The defect changed, so the severity should be reviewed - but the "
            "language model is unavailable and I will not replace the existing "
            "assessment with a keyword-matched one."
        )

    return ChatResponse(
        reply=reply,
        tool_called="edit_complaint",
        form_update=updates,
        fields_changed=changed,
        # An edit is an explicit instruction, so it overwrites operator input.
        overwrite=True,
        copilot=copilot,
        form_complete=not _missing_mandatory(merged),
        degraded=degraded or reply_degraded,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def _record_as_text(form: dict[str, Any]) -> str:
    """Flatten the record so the graph can re-assess it as if it were a source."""
    parts = [
        f"Product: {form.get('product_name', 'not stated')} "
        f"{form.get('product_strength', '')}".strip(),
        f"Batch: {form.get('batch_number', 'not stated')}",
        f"Category: {form.get('complaint_category', 'not stated')}",
        f"Affected quantity: {form.get('affected_quantity', 'not stated')}",
        f"Customer: {form.get('customer_name', 'not stated')}",
        "",
        form.get("complaint_description") or "",
    ]
    return "\n".join(parts).strip()


def _compose_edit_reply(
    edit: ComplaintEdit | None,
    changed: list[str],
    merged: dict[str, Any],
    reassessed: bool,
) -> tuple[str, bool]:
    facts = {
        "changed_fields": ", ".join(changed),
        "new_values": {f: merged.get(f) for f in changed},
        "change_summary": edit.change_summary if edit else "",
        "risk_reassessed": reassessed,
        "severity_now": merged.get("severity"),
    }
    try:
        reply = structured_call(
            prompts.EDIT_REPLY_PROMPT,
            "\n".join(f"{k}: {v}" for k, v in facts.items() if v),
            _Reply,
            model=settings.groq_model,
        )
        return reply.reply, False
    except LLMUnavailable:
        pretty = ", ".join(f.replace("_", " ") for f in changed)
        reply = f"Updated {pretty}."
        if reassessed and merged.get("severity"):
            reply += f" Re-ran the assessment: this is now {merged['severity']}."
        return reply, True


def handle_turn(
    message: str, history: list[ChatMessage], form: dict[str, Any]
) -> ChatResponse:
    """Process one chat turn."""
    started = time.perf_counter()

    # Editing an existing record is checked first: with a populated form,
    # "the quantity is actually 20" is an amendment, not a new complaint.
    if should_edit_complaint(message, form):
        return _handle_edit(message, history, form, started)

    # Cheap deterministic gate next. It only has to be right about the obvious
    # cases - a clear question never reaches the graph, everything else does,
    # and the graph's own triage node makes the real decision. An LLM router
    # here duplicated that triage call for no added accuracy, and every avoided
    # call is budget back.
    if not should_log_complaint(message):
        reply, degraded = _answer_question(message, history, form)
        return ChatResponse(
            reply=reply,
            tool_called=None,
            form_update={},
            copilot=None,
            form_complete=not _missing_mandatory({**form}),
            degraded=degraded,
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
        # The graph's triage disagreed with the gate. Trust the graph - it saw
        # the extraction attempt - and leave the form alone.
        reply, degraded = _answer_question(message, history, form)
        return ChatResponse(
            reply=reply,
            tool_called=None,
            form_update={},
            copilot=result,
            form_complete=False,
            degraded=degraded or result.degraded,
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
        degraded=result.degraded or reply_degraded,
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
