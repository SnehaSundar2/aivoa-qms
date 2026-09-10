"""The LangGraph workflow for complaint intake.

                        ┌──────────┐
                        │  triage  │   is this a complaint at all?
                        └────┬─────┘
                  not a complaint │ complaint
                   ┌─────────────┴──────────────┐
                   ▼                            ▼
              ┌────────┐                   ┌─────────┐
              │ reject │                   │ extract │  unstructured -> fields
              └───┬────┘                   └────┬────┘
                  │                             ▼
                  │                     ┌──────────────┐
                  │                     │ completeness │  what is missing?
                  │                     └──────┬───────┘
                  │                            ▼
                  │                     ┌──────────────┐
                  │                     │  duplicates  │  seen this before?
                  │                     └──────┬───────┘
                  │                            ▼
                  │                        ┌──────┐
                  │                        │ risk │  ICH Q9 triage
                  │                        └──┬───┘
                  │                  ┌────────┴────────┐   (parallel fan-out)
                  │                  ▼                 ▼
                  │            ┌───────────┐      ┌──────┐
                  │            │ root_cause│      │ capa │
                  │            └─────┬─────┘      └───┬──┘
                  │                  └────────┬───────┘   (join)
                  │                           ▼
                  │                      ┌─────────┐
                  │                      │ summary │
                  │                      └────┬────┘
                  └───────────────┬────────────┘
                                  ▼
                                 END

Why a graph rather than one big prompt:

* **Separation of concerns.** Extraction must be literal and conservative;
  risk assessment must reason and infer. Those are opposite instructions, and
  a single prompt asking for both produces a model that fabricates fields to
  justify its risk score.
* **Model routing.** Cheap, fast `gemma2-9b-it` handles extraction and
  triage; `llama-3.3-70b-versatile` handles the judgement calls.
* **Independent failure.** If CAPA generation fails, the operator still gets
  the extracted record and the risk assessment.
* **Auditability.** Each node's contribution is separately recorded, so a QA
  reviewer can see which step produced which value.
"""
from __future__ import annotations

import functools
import logging

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    capa_node,
    completeness_node,
    duplicate_node,
    extract_node,
    reject_node,
    risk_node,
    root_cause_node,
    summary_node,
    triage_node,
)
from app.agent.state import ComplaintAgentState

logger = logging.getLogger(__name__)


def _route_after_triage(state: ComplaintAgentState) -> str:
    """Conditional edge: skip the expensive path for non-complaints."""
    return "extract" if state.get("is_complaint", True) else "reject"


def build_graph():
    graph = StateGraph(ComplaintAgentState)

    graph.add_node("triage", triage_node)
    graph.add_node("reject", reject_node)
    graph.add_node("extract", extract_node)
    graph.add_node("check_completeness", completeness_node)
    graph.add_node("detect_duplicates", duplicate_node)
    graph.add_node("assess_risk", risk_node)
    graph.add_node("analyse_root_cause", root_cause_node)
    graph.add_node("recommend_capa", capa_node)
    graph.add_node("write_summary", summary_node)

    graph.add_edge(START, "triage")
    graph.add_conditional_edges(
        "triage", _route_after_triage, {"extract": "extract", "reject": "reject"}
    )

    graph.add_edge("extract", "check_completeness")
    graph.add_edge("check_completeness", "detect_duplicates")
    graph.add_edge("detect_duplicates", "assess_risk")

    # Fan out: root cause analysis and CAPA drafting are independent of each
    # other but both need the severity, so they branch off the risk node and
    # LangGraph runs them concurrently.
    graph.add_edge("assess_risk", "analyse_root_cause")
    graph.add_edge("assess_risk", "recommend_capa")

    # Join: summary waits for both branches before it runs.
    graph.add_edge("analyse_root_cause", "write_summary")
    graph.add_edge("recommend_capa", "write_summary")

    graph.add_edge("write_summary", END)
    graph.add_edge("reject", END)

    return graph.compile()


@functools.lru_cache(maxsize=1)
def get_graph():
    """Compile once and reuse - compilation is not free and the graph is stateless."""
    compiled = build_graph()
    logger.info("Complaint agent graph compiled")
    return compiled


def render_mermaid() -> str:
    """Expose the graph shape for the UI / documentation."""
    try:
        return get_graph().get_graph().draw_mermaid()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not render graph: %s", exc)
        return ""
