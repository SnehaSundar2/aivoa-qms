"""Tools the copilot agent can call.

`log_complaint` is the mandatory tool: it takes the operator's free-text
message and returns the structured complaint record that populates the
"Log Customer Complaint" form.

Implemented as a real tool rather than a bare prompt for two reasons that
matter here:

* **The model decides whether to call it.** "Log this complaint: ..." should
  extract and populate; "what does Major severity mean?" should just be
  answered. A tool call is how that decision becomes explicit and inspectable,
  rather than something inferred from whether the JSON came back empty.
* **The arguments are the schema.** Tool arguments are validated against
  `ExtractedComplaint` before anything reaches the form, so a malformed
  extraction fails here rather than halfway through the UI.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.agent.llm import LLMUnavailable, structured_call
from app.agent.prompts import EDIT_PROMPT, EXTRACTION_PROMPT
from app.core.config import settings
from app.schemas import ComplaintEdit, ExtractedComplaint

logger = logging.getLogger(__name__)

LOG_COMPLAINT_TOOL = {
    "type": "function",
    "function": {
        "name": "log_complaint",
        "description": (
            "Extract a pharmaceutical customer complaint from free text and populate "
            "the Log Customer Complaint form. Call this whenever the user's message "
            "describes a product defect, quality issue or customer complaint - even "
            "if some details are missing. Do not call it for general questions about "
            "the QMS, or for messages that are not complaints."
        ),
        "parameters": ExtractedComplaint.model_json_schema(),
    },
}


def run_log_complaint(text: str, existing: dict[str, Any] | None = None) -> ExtractedComplaint:
    """Execute the tool: free text in, validated complaint record out.

    Raises `LLMUnavailable` so the calling node can fall back to rules.
    """
    hint = ""
    if existing:
        filled = {k: v for k, v in existing.items() if v not in (None, "", False, [])}
        if filled:
            hint = (
                "\n\nThe operator has already entered these values. Treat them as "
                "correct, do not contradict them, and extract only what is missing:\n"
                + json.dumps(filled, indent=2, default=str)
            )

    return structured_call(
        EXTRACTION_PROMPT,
        f"Customer complaint source:\n\n{text[:12000]}{hint}",
        ExtractedComplaint,
        model=settings.groq_model,
    )


def should_log_complaint(text: str) -> bool:
    """Cheap rule-based gate used when the model cannot be reached.

    Mirrors the tool description above: does this look like someone reporting a
    product problem, rather than asking a question?
    """
    low = (text or "").lower().strip()

    if low.endswith("?") and len(low) < 160:
        return False

    question_openers = (
        "what ", "why ", "how ", "when ", "who ", "which ", "can you", "could you",
        "explain", "tell me about", "define",
    )
    if any(low.startswith(q) for q in question_openers):
        return False

    complaint_signals = (
        "complaint", "defect", "discolor", "discolour", "damaged", "broken",
        "contaminat", "particle", "foreign", "out of specification", "oos",
        "batch", "lot ", "expiry", "reported", "log this", "customer",
        "pharmacy", "hospital", "distributor", "returned", "reject",
        "leak", "seal", "label", "missing", "short", "excursion",
    )
    return any(signal in low for signal in complaint_signals)


EDIT_COMPLAINT_TOOL = {
    "type": "function",
    "function": {
        "name": "edit_complaint",
        "description": (
            "Correct or update fields on the complaint already shown in the form, "
            "including the AI risk assessment. Call this when the user is amending "
            "an existing record - 'change the batch to X', 'the quantity is actually "
            "20', 'set severity to Critical', 'remove the expiry date'. Do not call "
            "it when the form is empty, or when the user is describing a new and "
            "different complaint."
        ),
        "parameters": ComplaintEdit.model_json_schema(),
    },
}

# Fields the operator may edit. Anything outside this set is refused - the tool
# must not be able to reach workflow state such as status or assignment.
EDITABLE_FIELDS = frozenset(ComplaintEdit.model_fields) - {
    "fields_to_clear",
    "reassess_risk",
    "change_summary",
}


def run_edit_complaint(message: str, current_form: dict[str, Any]) -> ComplaintEdit:
    """Execute the tool: an instruction plus the current record, changes out.

    Raises `LLMUnavailable` so the caller can report the failure rather than
    guessing at an edit. There is deliberately no rule-based fallback here:
    misreading "make it 20" without a model is far more likely to corrupt the
    record than to help.
    """
    shown = {
        field: value
        for field, value in current_form.items()
        if field in EDITABLE_FIELDS and value not in (None, "", [], False)
    }

    return structured_call(
        EDIT_PROMPT,
        "The complaint record currently on screen:\n"
        + json.dumps(shown, indent=2, default=str)
        + f"\n\nThe operator says:\n{message[:2000]}",
        ComplaintEdit,
        model=settings.groq_model,
    )


# Phrases that mean "change what is already there" rather than "log something
# new". Checked only when the form is already populated.
_EDIT_SIGNALS = (
    "change", "update", "correct", "fix", "amend", "revise", "edit",
    "actually", "instead", "should be", "should have", "not ", "isn't",
    "is wrong", "incorrect", "mistake", "typo", "make it", "set the",
    "set severity", "replace", "remove the", "clear the", "delete the",
    "re-assess", "reassess", "re-run", "rerun", "downgrade", "upgrade",
    "it is ", "it's ", "sorry",
)


# An amendment is an instruction: short and imperative. A complaint is a
# narrative. Anything past this length carrying complaint detail is the latter,
# whatever incidental words it contains - a customer email saying "this is not
# acceptable" must not be read as "correct the record".
_EDIT_LENGTH_CEILING = 320


def looks_like_a_complaint_document(text: str) -> bool:
    """True when the text reads as a complaint report rather than an instruction."""
    low = (text or "").lower()
    if len(low) < _EDIT_LENGTH_CEILING:
        return False
    narrative_markers = (
        "batch", "lot no", "expiry", "reported", "observed", "quantity",
        "dear", "subject:", "from:", "complaint",
    )
    return sum(marker in low for marker in narrative_markers) >= 2


def should_edit_complaint(text: str, current_form: dict[str, Any]) -> bool:
    """Decide whether this message edits the record on screen.

    Deterministic on purpose: an LLM router here would be a third model call
    per turn to answer a question the wording usually settles.
    """
    populated = any(
        current_form.get(field) for field in ("product_name", "batch_number", "customer_name")
    )
    if not populated:
        return False  # nothing to edit yet

    low = (text or "").lower()

    # A message carrying a whole complaint is a new log, not an edit, even with
    # a populated form - the operator has moved on to the next one. Checked by
    # shape rather than by keyword: two of the three sample complaint emails
    # contain "correct" or "not", and were being routed to the edit tool.
    if looks_like_a_complaint_document(text):
        return False
    if low.count("batch") and ("please log" in low or "log this" in low or "new complaint" in low):
        return False

    return any(signal in low for signal in _EDIT_SIGNALS)


# Fields that identify WHICH complaint this is. If an incoming document
# disagrees with the form on any of them, it is a different complaint.
IDENTITY_FIELDS = ("batch_number", "product_name")


def is_a_different_complaint(extracted: dict[str, Any], form: dict[str, Any]) -> bool:
    """True when the new source describes a complaint other than the one on screen.

    Without this check, log_complaint's gap-filling merges the two: the form
    keeps product A's name and takes product B's batch number, producing a
    record that describes no real event. That is worse than either input.
    """
    for field in IDENTITY_FIELDS:
        old_value = str(form.get(field) or "").strip().lower()
        new_value = str(extracted.get(field) or "").strip().lower()
        if old_value and new_value and old_value != new_value:
            return True
    return False
