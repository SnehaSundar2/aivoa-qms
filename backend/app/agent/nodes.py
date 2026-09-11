"""The individual nodes of the complaint agent graph.

Every node follows the same contract:
  * take the shared state,
  * try the LLM,
  * fall back to a deterministic rule on `LLMUnavailable`,
  * return only the keys it owns, plus its trace entry.

Nodes never raise. A failed node degrades the run; it does not abort intake -
losing a customer complaint because a model timed out would be the worst
possible failure mode for this module.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel

from app.agent import heuristics, prompts
from app.agent.llm import LLMUnavailable, structured_call
from app.agent.state import ComplaintAgentState
from app.core.config import settings
from app.core.enums import MANDATORY_FIELDS, SEVERITY_TAT_DAYS, Severity
from app.schemas import (
    CapaAction,
    CompletenessResult,
    ExtractedComplaint,
    RiskAssessmentResult,
    RootCause,
)

logger = logging.getLogger(__name__)

FAST_MODEL = settings.groq_model                 # gemma2-9b-it
REASONING_MODEL = settings.groq_reasoning_model  # llama-3.3-70b-versatile


class _TriageVerdict(BaseModel):
    is_complaint: bool
    reason: str
    confidence: float = 0.5


class _RootCauseList(BaseModel):
    root_causes: list[RootCause]


class _CapaList(BaseModel):
    capa: list[CapaAction]


class _Summary(BaseModel):
    summary: str


def _merged_record(state: ComplaintAgentState) -> dict[str, Any]:
    """Extracted values overlaid with whatever the user already typed.

    User input always wins - the operator is the record owner, the model is an
    assistant.
    """
    merged = dict(state.get("extracted") or {})
    for key, value in (state.get("existing") or {}).items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# 1. Triage - is this actually a complaint?
# ---------------------------------------------------------------------------
def triage_node(state: ComplaintAgentState) -> dict[str, Any]:
    text = state.get("raw_text", "")

    try:
        verdict = structured_call(
            prompts.TRIAGE_PROMPT,
            f"Incoming document:\n\n{text[:6000]}",
            _TriageVerdict,
            model=FAST_MODEL,
        )
        return {
            "is_complaint": verdict.is_complaint,
            "rejection_reason": None if verdict.is_complaint else verdict.reason,
            "trace": ["triage"],
            "models_used": [FAST_MODEL],
        }
    except LLMUnavailable as exc:
        logger.info("triage_node degraded: %s", exc)
        ok = heuristics.looks_like_complaint(text)
        return {
            "is_complaint": ok,
            "rejection_reason": None if ok else "Rule-based triage found no alleged deficiency.",
            "degraded": True,
            "trace": ["triage (rules)"],
            "errors": [f"triage: {exc}"],
        }


# ---------------------------------------------------------------------------
# 2. Extraction - unstructured source to structured record
# ---------------------------------------------------------------------------
def extract_node(state: ComplaintAgentState) -> dict[str, Any]:
    """Run the `log_complaint` tool over the source text."""
    from app.agent.tools import run_log_complaint

    text = state.get("raw_text", "")
    existing = state.get("existing") or {}

    try:
        extracted = run_log_complaint(text, existing)
        return {
            "extracted": extracted.model_dump(),
            "tool_called": "log_complaint",
            "trace": ["log_complaint"],
            "models_used": [FAST_MODEL],
        }
    except LLMUnavailable as exc:
        logger.info("extract_node degraded: %s", exc)
        return {
            "extracted": heuristics.extract(text).model_dump(),
            "tool_called": "log_complaint",
            "degraded": True,
            "trace": ["log_complaint (rules)"],
            "errors": [f"extract: {exc}"],
        }


# ---------------------------------------------------------------------------
# 3. Completeness checker
# ---------------------------------------------------------------------------
def completeness_node(state: ComplaintAgentState) -> dict[str, Any]:
    record = _merged_record(state)

    # The presence check itself is deterministic - we know exactly which fields
    # are mandatory, so there is no reason to ask a model. The LLM is used only
    # to phrase the clarifying questions well.
    base = heuristics.completeness(record)

    if not base.missing_mandatory and not base.missing_recommended:
        return {"completeness": base.model_dump(), "trace": ["completeness"]}

    try:
        refined = structured_call(
            prompts.COMPLETENESS_PROMPT,
            "Complaint record so far:\n"
            + json.dumps(record, indent=2, default=str)
            + "\n\nMissing mandatory fields: "
            + ", ".join(base.missing_mandatory or ["none"])
            + "\nMissing recommended fields: "
            + ", ".join(base.missing_recommended or ["none"])
            + "\n\nReturn the completeness result with well-phrased clarifying questions.",
            CompletenessResult,
            model=FAST_MODEL,
        )
        # Trust our own arithmetic over the model's for the objective parts.
        refined.missing_mandatory = base.missing_mandatory
        refined.missing_recommended = base.missing_recommended
        refined.is_complete = base.is_complete
        refined.score = base.score
        return {
            "completeness": refined.model_dump(),
            "trace": ["completeness"],
            "models_used": [FAST_MODEL],
        }
    except LLMUnavailable as exc:
        logger.info("completeness_node degraded: %s", exc)
        return {
            "completeness": base.model_dump(),
            "degraded": True,
            "trace": ["completeness (rules)"],
            "errors": [f"completeness: {exc}"],
        }


# ---------------------------------------------------------------------------
# 4. Duplicate detection - deterministic, against the complaint history
# ---------------------------------------------------------------------------
def duplicate_node(state: ComplaintAgentState) -> dict[str, Any]:
    from app.services.duplicates import find_duplicates

    record = _merged_record(state)
    try:
        candidates = find_duplicates(record)
        return {
            "duplicates": [c.model_dump() for c in candidates],
            "trace": ["duplicate_check"],
        }
    except Exception as exc:  # noqa: BLE001 - a DB hiccup must not kill intake
        logger.warning("duplicate_node failed: %s", exc)
        return {"duplicates": [], "trace": ["duplicate_check (failed)"], "errors": [f"duplicates: {exc}"]}


# ---------------------------------------------------------------------------
# 5. Risk assessment - the reasoning-heavy node
# ---------------------------------------------------------------------------
def risk_node(state: ComplaintAgentState) -> dict[str, Any]:
    record = _merged_record(state)
    dupes = state.get("duplicates") or []

    context = "Structured complaint record:\n" + json.dumps(record, indent=2, default=str)
    if dupes:
        context += (
            f"\n\nNote: {len(dupes)} similar complaint(s) already exist for this "
            "product/batch. Recurrence raises the risk score - a repeat defect "
            "suggests an uncontrolled process:\n"
            + json.dumps(dupes, indent=2, default=str)
        )
    context += "\n\nOriginal source text:\n" + (state.get("raw_text") or "")[:4000]

    try:
        risk = structured_call(prompts.RISK_PROMPT, context, RiskAssessmentResult, model=REASONING_MODEL)
        if risk.recommended_due_days is None:
            risk.recommended_due_days = SEVERITY_TAT_DAYS.get(Severity(risk.severity), 30)
        return {"risk": risk.model_dump(), "trace": ["risk_assessment"], "models_used": [REASONING_MODEL]}
    except LLMUnavailable as exc:
        logger.info("risk_node degraded: %s", exc)
        fallback = heuristics.assess_risk(
            state.get("raw_text", "") + " " + (record.get("complaint_description") or ""),
            record.get("complaint_category"),
        )
        return {
            "risk": fallback.model_dump(),
            "degraded": True,
            "trace": ["risk_assessment (rules)"],
            "errors": [f"risk: {exc}"],
        }


# ---------------------------------------------------------------------------
# 6a / 6b - root cause and CAPA run in parallel off the risk node
# ---------------------------------------------------------------------------
def root_cause_node(state: ComplaintAgentState) -> dict[str, Any]:
    record = _merged_record(state)
    risk = state.get("risk") or {}

    try:
        result = structured_call(
            prompts.ROOT_CAUSE_PROMPT,
            "Complaint record:\n"
            + json.dumps(record, indent=2, default=str)
            + f"\n\nPreliminary severity: {risk.get('severity')} "
            f"(score {risk.get('risk_score')}).",
            _RootCauseList,
            model=REASONING_MODEL,
        )
        return {
            "root_causes": [rc.model_dump() for rc in result.root_causes],
            "trace": ["root_cause"],
            "models_used": [REASONING_MODEL],
        }
    except LLMUnavailable as exc:
        logger.info("root_cause_node degraded: %s", exc)
        return {
            "root_causes": [rc.model_dump() for rc in heuristics.root_causes(record.get("complaint_category"))],
            "degraded": True,
            "trace": ["root_cause (rules)"],
            "errors": [f"root_cause: {exc}"],
        }


def capa_node(state: ComplaintAgentState) -> dict[str, Any]:
    record = _merged_record(state)
    risk = state.get("risk") or {}

    try:
        result = structured_call(
            prompts.CAPA_PROMPT,
            "Complaint record:\n"
            + json.dumps(record, indent=2, default=str)
            + f"\n\nPreliminary severity: {risk.get('severity')}. "
            f"Regulatory reportable: {risk.get('regulatory_reportable')}.",
            _CapaList,
            model=REASONING_MODEL,
        )
        return {
            "capa": [c.model_dump() for c in result.capa],
            "trace": ["capa"],
            "models_used": [REASONING_MODEL],
        }
    except LLMUnavailable as exc:
        logger.info("capa_node degraded: %s", exc)
        return {
            "capa": [c.model_dump() for c in heuristics.capa(risk.get("severity"))],
            "degraded": True,
            "trace": ["capa (rules)"],
            "errors": [f"capa: {exc}"],
        }


# ---------------------------------------------------------------------------
# 7. Summary - the join point of the parallel branches
# ---------------------------------------------------------------------------
def summary_node(state: ComplaintAgentState) -> dict[str, Any]:
    record = _merged_record(state)
    risk = state.get("risk") or {}
    payload = {**record, "severity": risk.get("severity"), "risk_score": risk.get("risk_score")}

    try:
        result = structured_call(
            prompts.SUMMARY_PROMPT,
            "Complaint record:\n" + json.dumps(payload, indent=2, default=str),
            _Summary,
            model=FAST_MODEL,
        )
        return {"summary": result.summary, "trace": ["summary"], "models_used": [FAST_MODEL]}
    except LLMUnavailable as exc:
        logger.info("summary_node degraded: %s", exc)
        return {
            "summary": heuristics.summary(payload),
            "degraded": True,
            "trace": ["summary (rules)"],
            "errors": [f"summary: {exc}"],
        }


# ---------------------------------------------------------------------------
# Terminal node for non-complaints
# ---------------------------------------------------------------------------
def reject_node(state: ComplaintAgentState) -> dict[str, Any]:
    """Short-circuit: the source is not a complaint, so skip the expensive nodes."""
    return {
        "extracted": {},
        "completeness": CompletenessResult(
            is_complete=False,
            score=0,
            missing_mandatory=list(MANDATORY_FIELDS),
            clarifying_questions=[
                "This document does not appear to describe a product deficiency. "
                "Please confirm whether it should be logged as a complaint."
            ],
        ).model_dump(),
        "duplicates": [],
        "risk": RiskAssessmentResult(
            severity="Minor",
            risk_score=0,
            confidence=0.0,
            rationale="Not classified - the source was not identified as a customer complaint.",
        ).model_dump(),
        "root_causes": [],
        "capa": [],
        "summary": state.get("rejection_reason") or "Source was not identified as a customer complaint.",
        "trace": ["reject"],
    }
