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
from app.agent.prompts import EXTRACTION_PROMPT
from app.core.config import settings
from app.schemas import ExtractedComplaint

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
