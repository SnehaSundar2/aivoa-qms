"""Shared state for the complaint agent graph.

`trace`, `models_used`, `errors` and `degraded` carry reducers because the
root-cause and CAPA nodes run in parallel and both write to them in the same
superstep; without a reducer LangGraph raises InvalidUpdateError. The list keys
accumulate with `operator.add`, and `degraded` latches with `operator.or_` -
once any node has fallen back to rules, the whole run is degraded.

Every other key is written by exactly one node, so last-write-wins is correct.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, List, Optional, TypedDict


class ComplaintAgentState(TypedDict, total=False):
    # --- input ---
    raw_text: str
    source_type: Optional[str]
    source_reference: Optional[str]
    # Fields the user already typed into the form; the agent must not overwrite
    # them, only fill the gaps.
    existing: dict[str, Any]

    # --- triage ---
    is_complaint: bool
    rejection_reason: Optional[str]

    # --- node outputs (plain dicts so the state stays JSON-serialisable) ---
    extracted: dict[str, Any]
    completeness: dict[str, Any]
    duplicates: List[dict[str, Any]]
    risk: dict[str, Any]
    root_causes: List[dict[str, Any]]
    capa: List[dict[str, Any]]
    summary: Optional[str]

    # --- observability ---
    trace: Annotated[List[str], operator.add]
    models_used: Annotated[List[str], operator.add]
    errors: Annotated[List[str], operator.add]
    # Sticky: once any node has fallen back to rules the whole run is degraded,
    # and the parallel branches can both set it in the same step.
    degraded: Annotated[bool, operator.or_]
