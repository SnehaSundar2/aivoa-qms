"""Deterministic parsing for unambiguous edit instructions.

The `edit_complaint` tool prefers the model, because most corrections are
phrased loosely ("make it 20", "no, it was the other batch") and resolving
them needs the record in context.

But a useful subset is not loose at all:

    set severity to Critical
    change the batch number to AMX240603
    the affected quantity is actually 20 capsules
    remove the expiry date

Those name their field and their value explicitly. Parsing them here means the
edit tool still works when the model is unreachable - which matters, because
Groq's free tier runs out - and it costs nothing when the model is available.

The bar is deliberately high: if the instruction does not match one of these
shapes, this returns None and the caller refuses rather than guessing. A wrong
edit to a regulated record is worse than no edit.
"""
from __future__ import annotations

import re
from typing import Any

from app.core.enums import COMPLAINT_SOURCES, SITE_BLOCKS, Severity
from app.schemas import ComplaintEdit

# Field labels as an operator would say them, longest first so that
# "batch number" wins over "number" and "product strength" over "product".
FIELD_ALIASES: list[tuple[str, str]] = [
    ("originating site block", "originating_site_block"),
    ("suggested next action", "suggested_next_action"),
    ("initial risk assessment", "initial_risk_assessment"),
    ("impacted non-product materials", "impacted_npm"),
    ("non-product materials", "impacted_npm"),
    ("structured defect summary", "complaint_description"),
    ("complaint description", "complaint_description"),
    ("complaint category", "complaint_category"),
    ("manufacturing date", "manufacturing_date"),
    ("affected quantity", "affected_quantity"),
    ("product strength", "product_strength"),
    ("complaint source", "complaint_source"),
    ("customer name", "customer_name"),
    ("contact name", "complainant_name"),
    ("batch number", "batch_number"),
    ("product name", "product_name"),
    ("lot number", "batch_number"),
    ("next action", "suggested_next_action"),
    ("description", "complaint_description"),
    ("site block", "originating_site_block"),
    ("expiry date", "expiry_date"),
    ("mfg date", "manufacturing_date"),
    ("quantity", "affected_quantity"),
    ("strength", "product_strength"),
    ("severity", "severity"),
    ("category", "complaint_category"),
    ("customer", "customer_name"),
    ("product", "product_name"),
    ("batch", "batch_number"),
    ("expiry", "expiry_date"),
    ("source", "complaint_source"),
    ("country", "country"),
    ("email", "complainant_email"),
    ("phone", "complainant_phone"),
    ("npm", "impacted_npm"),
]

_FIELD_PATTERN = "|".join(re.escape(label) for label, _ in FIELD_ALIASES)

# "set the batch number to AMX240603"
_SET_RE = re.compile(
    rf"\b(?:set|change|update|correct|make|fix|amend)\s+(?:the\s+)?"
    rf"(?P<field>{_FIELD_PATTERN})\s+(?:to|as|=)\s+(?P<value>.+)",
    re.I,
)

# "the affected quantity is actually 20 capsules"
_IS_RE = re.compile(
    rf"\b(?:the\s+)?(?P<field>{_FIELD_PATTERN})\s+(?:is|was|should be)\s+"
    rf"(?:actually\s+|really\s+)?(?P<value>.+)",
    re.I,
)

# "remove the expiry date"
_CLEAR_RE = re.compile(
    rf"\b(?:remove|clear|delete|blank|erase)\s+(?:the\s+)?(?P<field>{_FIELD_PATTERN})\b",
    re.I,
)

# Fields where a free-text value would be wrong; they must match a vocabulary.
_CONTROLLED = {
    "severity": [s.value for s in Severity],
    "complaint_source": list(COMPLAINT_SOURCES),
    "originating_site_block": list(SITE_BLOCKS),
}

# Changing any of these alters the defect, so severity has to be reconsidered.
_MATERIAL_FIELDS = {
    "complaint_category",
    "complaint_description",
    "product_name",
    "affected_quantity",
}


def _clean_value(raw: str) -> str:
    value = raw.strip().strip(".!,;").strip()
    # Drop a trailing clause: "20 capsules, and the batch is X" -> "20 capsules"
    value = re.split(r",\s*(?:and|also|plus)\b", value, maxsplit=1)[0]
    return value.strip().strip("\"'").strip()


def _snap_controlled(field: str, value: str) -> str | None:
    """Controlled fields accept only their own vocabulary."""
    options = _CONTROLLED.get(field)
    if options is None:
        return value

    for option in options:
        if option.lower() == value.lower():
            return option
    # A partial match is enough for site blocks ("block b" -> "Block B - ...").
    for option in options:
        if value.lower() in option.lower() or option.lower().startswith(value.lower()):
            return option
    return None


def parse_edit_instruction(text: str) -> ComplaintEdit | None:
    """Return a ComplaintEdit for an unambiguous instruction, else None."""
    if not text:
        return None
    message = " ".join(text.split())

    clear = _CLEAR_RE.search(message)
    if clear:
        field = dict(FIELD_ALIASES)[clear.group("field").lower()]
        return ComplaintEdit(
            fields_to_clear=[field],
            change_summary=f"cleared {field.replace('_', ' ')}",
        )

    match = _SET_RE.search(message) or _IS_RE.search(message)
    if not match:
        return None

    field = dict(FIELD_ALIASES)[match.group("field").lower()]
    value = _clean_value(match.group("value"))
    if not value:
        return None

    snapped = _snap_controlled(field, value)
    if snapped is None:
        # Named a controlled field but not one of its allowed values - refuse
        # rather than writing something the dropdown cannot show.
        return None

    payload: dict[str, Any] = {
        field: snapped,
        "change_summary": f"{field.replace('_', ' ')} -> {snapped}",
        # Only the model should decide to re-grade off a free-text edit; here
        # we flag it and let the caller run the assessment.
        "reassess_risk": field in _MATERIAL_FIELDS,
    }
    return ComplaintEdit(**payload)
