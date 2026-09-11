"""Orchestration between the API layer and the LangGraph agent.

Responsibilities:
  * invoke the compiled graph,
  * coerce the model's loose output into values the form can actually accept,
  * assemble the `form_prefill` dict the Redux store applies to the
    "Log Customer Complaint" form.

The coercion step matters more than it looks. A model asked for a category will
occasionally return "Packaging defect" or "packaging" instead of the exact
enum member. Rather than reject the whole run we snap it to the nearest legal
value, and drop it if nothing is close - a blank field an operator fills in is
far better than a plausible wrong one they do not notice.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from difflib import get_close_matches
from typing import Any

from app.agent.graph import get_graph
from app.core.enums import (
    SEVERITY_TAT_DAYS,
    ComplaintCategory,
    ProductType,
    Severity,
)
from app.schemas import (
    CapaAction,
    CompletenessResult,
    CopilotResult,
    DuplicateCandidate,
    ExtractedComplaint,
    RiskAssessmentResult,
    RootCause,
)

logger = logging.getLogger(__name__)

_DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d %b %Y",
    "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d", "%d.%m.%Y",
)

# Fields that must never be auto-filled into the form from model output.
# The workflow status and assignment are human decisions.
_NON_PREFILLABLE = {"status", "assigned_to", "department", "id", "complaint_number"}


def _coerce_date(value: Any) -> str | None:
    """Return an ISO date string, or None if the value is not a usable date."""
    if not value:
        return None
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()

    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        # Guard against a model hallucinating a far-future or ancient date.
        if 1990 <= parsed.year <= date.today().year + 10:
            return parsed.isoformat()
    logger.debug("Discarded unparseable date: %r", value)
    return None


def _snap_enum(value: Any, enum_cls) -> str | None:
    """Snap a loose string to an exact enum value, or drop it."""
    if not value:
        return None
    text = str(value).strip()
    allowed = [member.value for member in enum_cls]

    for option in allowed:
        if option.lower() == text.lower():
            return option

    match = get_close_matches(text.lower(), [o.lower() for o in allowed], n=1, cutoff=0.75)
    if match:
        snapped = next(o for o in allowed if o.lower() == match[0])
        logger.info("Snapped %r to %r", text, snapped)
        return snapped

    logger.info("Dropped unrecognised value %r for %s", text, enum_cls.__name__)
    return None


def _build_prefill(extracted: dict, risk: dict, summary: str | None, source: dict) -> dict[str, Any]:
    """Map agent output onto the exact field names of the complaint form."""
    prefill: dict[str, Any] = {}

    passthrough = (
        # 1. Origin & customer
        "complaint_source", "customer_name", "complainant_name",
        "complainant_email", "complainant_phone", "country",
        # 2. Product & batch
        "product_name", "product_strength", "product_code", "dosage_form",
        "pack_size", "batch_number", "affected_quantity", "quantity_supplied",
        # Dates stay verbatim: "March 2026" is what the customer wrote and what
        # the record must show.
        "manufacturing_date", "expiry_date",
        # 3. Facility & material impact
        "originating_site_block", "impacted_npm",
        # 4. Defect analysis
        "complaint_category", "complaint_subcategory", "complaint_description",
        "sample_quantity",
    )
    for field in passthrough:
        value = extracted.get(field)
        if value not in (None, "", []):
            prefill[field] = value

    # Only the complaint date is a real DATE column, so only it gets coerced.
    coerced = _coerce_date(extracted.get("date_of_complaint"))
    if coerced:
        prefill["date_of_complaint"] = coerced

    product_type = _snap_enum(extracted.get("product_type"), ProductType)
    if product_type and product_type != ProductType.UNKNOWN.value:
        prefill["product_type"] = product_type

    if extracted.get("sample_available") is not None:
        prefill["sample_available"] = bool(extracted["sample_available"])

    # Risk-derived fields.
    severity = _snap_enum(risk.get("severity"), Severity)
    if severity:
        prefill["severity"] = severity
        due_days = risk.get("recommended_due_days") or SEVERITY_TAT_DAYS[Severity(severity)]
        prefill["due_date"] = (date.today() + timedelta(days=int(due_days))).isoformat()

    if risk.get("risk_score") is not None:
        prefill["risk_score"] = int(risk["risk_score"])
    if risk.get("regulatory_reportable") is not None:
        prefill["regulatory_reportable"] = bool(risk["regulatory_reportable"])
    if risk.get("regulatory_rationale"):
        prefill["regulatory_rationale"] = risk["regulatory_rationale"]
    if risk.get("suggested_next_action"):
        prefill["suggested_next_action"] = risk["suggested_next_action"]
    if risk.get("initial_risk_assessment"):
        prefill["initial_risk_assessment"] = risk["initial_risk_assessment"]

    # Intake defaults the operator can still change.
    prefill["date_received"] = date.today().isoformat()
    prefill["ai_assisted"] = True
    if summary:
        prefill["ai_summary"] = summary
    prefill.update({k: v for k, v in source.items() if v})

    return {k: v for k, v in prefill.items() if k not in _NON_PREFILLABLE}


def run_copilot(
    raw_text: str,
    source_type: str | None = None,
    source_reference: str | None = None,
    existing: dict | None = None,
) -> CopilotResult:
    """Run the full agent graph over a source document and return the UI payload."""
    started = time.perf_counter()

    initial = {
        "raw_text": raw_text,
        "source_type": source_type,
        "source_reference": source_reference,
        "existing": existing or {},
        "trace": [],
        "models_used": [],
        "errors": [],
        "degraded": False,
    }

    try:
        final = get_graph().invoke(initial)
    except Exception as exc:  # noqa: BLE001 - never lose the intake
        logger.exception("Agent graph failed outright")
        from app.agent import heuristics

        from app.services.duplicates import find_duplicates

        extracted = heuristics.extract(raw_text)
        risk = heuristics.assess_risk(raw_text, extracted.complaint_category)

        # Duplicate detection is pure SQL and independent of whatever broke,
        # so it is still worth running here.
        try:
            dupes = [d.model_dump() for d in find_duplicates(extracted.model_dump())]
        except Exception:  # noqa: BLE001
            dupes = []

        final = {
            "extracted": extracted.model_dump(),
            "risk": risk.model_dump(),
            "completeness": heuristics.completeness(extracted.model_dump()).model_dump(),
            "duplicates": dupes,
            "root_causes": [rc.model_dump() for rc in heuristics.root_causes(extracted.complaint_category)],
            "capa": [c.model_dump() for c in heuristics.capa(risk.severity)],
            "summary": heuristics.summary({**extracted.model_dump(), "severity": risk.severity}),
            "trace": ["graph_failure_fallback"],
            "models_used": [],
            "errors": [str(exc)],
            "degraded": True,
            "is_complaint": True,
        }

    extracted = final.get("extracted") or {}
    risk = final.get("risk") or {}
    summary = final.get("summary")

    source = {
        "source_type": source_type,
        "source_reference": source_reference,
        "source_text": raw_text[:20000],
    }

    result = CopilotResult(
        extracted=ExtractedComplaint(**extracted) if extracted else ExtractedComplaint(),
        risk=RiskAssessmentResult(**risk) if risk else RiskAssessmentResult(),
        completeness=(
            CompletenessResult(**final["completeness"])
            if final.get("completeness")
            else CompletenessResult()
        ),
        root_causes=[RootCause(**rc) for rc in (final.get("root_causes") or [])],
        capa=[CapaAction(**c) for c in (final.get("capa") or [])],
        duplicates=[DuplicateCandidate(**d) for d in (final.get("duplicates") or [])],
        summary=summary,
        form_prefill=_build_prefill(extracted, risk, summary, source),
        source_type=source_type,
        source_reference=source_reference,
        source_text=raw_text[:20000],
        is_complaint=final.get("is_complaint", True),
        rejection_reason=final.get("rejection_reason"),
        trace=final.get("trace") or [],
        models_used=sorted(set(final.get("models_used") or [])),
        latency_ms=int((time.perf_counter() - started) * 1000),
        degraded=bool(final.get("degraded")),
    )

    logger.info(
        "Copilot run finished in %sms | nodes=%s | degraded=%s | severity=%s",
        result.latency_ms, " -> ".join(result.trace), result.degraded, result.risk.severity,
    )
    return result
