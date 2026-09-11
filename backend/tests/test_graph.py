"""Tests for the agent graph and the deterministic nodes.

Runs with no GROQ_API_KEY, so every LLM-backed node takes its rule-based
fallback. That is deliberate: it proves the degradation path works, which is
the behaviour that keeps complaint intake alive during an outage.
"""
from __future__ import annotations

import pytest

from app.agent import heuristics
from app.agent.graph import build_graph, get_graph
from app.services.copilot import run_copilot

PARTICULATE_EMAIL = """
From: pharmacy@lakesidemedical.example
Subject: Particles found in Ondansetron vials, batch OND25B119

Our nursing staff found floating particles in two vials of Ondansetron
Injection USP 2 mg/mL, batch OND25B119. No product was administered. The
vials are quarantined and available for return.
"""

PURCHASE_ORDER = """
Subject: Purchase Order VD-2026-11042

Please find our purchase order for Q4 replenishment stock. Payment terms
remain net 45 days as per our supply agreement. Please confirm the despatch
date and include the Certificate of Analysis.
"""


def test_graph_compiles():
    """Guards against node names colliding with state keys, among other wiring bugs."""
    assert build_graph() is not None


def test_graph_is_compiled_once():
    assert get_graph() is get_graph()


def test_full_run_visits_every_node_in_order():
    result = run_copilot(PARTICULATE_EMAIL, source_type="Email")

    stages = [entry.split(" ")[0] for entry in result.trace]
    assert stages == [
        "triage", "log_complaint", "completeness", "duplicate_check",
        "risk_assessment", "root_cause", "capa", "summary",
    ]


def test_extraction_runs_as_a_named_tool():
    """The extraction step is a tool call, and says so in the trace."""
    result = run_copilot(PARTICULATE_EMAIL)
    assert any(node.startswith("log_complaint") for node in result.trace)


def test_non_complaint_short_circuits_to_reject():
    result = run_copilot(PURCHASE_ORDER, source_type="Email")

    assert result.is_complaint is False
    assert "reject" in result.trace
    # The expensive nodes must not have run.
    assert not result.root_causes
    assert not result.capa


def test_run_is_flagged_degraded_without_an_api_key(monkeypatch):
    """An operator must never mistake a rule-based result for an AI assessment.

    Forces the no-key condition rather than assuming it: a developer with a
    working .env would otherwise see this pass for the wrong reason, or fail.
    """
    from app.agent import llm

    monkeypatch.setattr(llm.settings, "groq_api_key", "")
    llm._client_cache.clear()

    result = run_copilot(PARTICULATE_EMAIL)
    assert result.degraded is True
    assert any("rules" in node for node in result.trace)


def test_operator_values_override_extraction_in_the_merged_record():
    """The operator owns the record; the agent fills gaps but never overrules."""
    from app.agent.nodes import _merged_record

    merged = _merged_record({
        "extracted": {"batch_number": "WRONG-FROM-MODEL", "product_name": "Model Guess",
                      "country": "India"},
        "existing": {"batch_number": "CORRECTED-99", "product_name": "Operator Value"},
    })

    assert merged["batch_number"] == "CORRECTED-99"
    assert merged["product_name"] == "Operator Value"
    # Values the operator did not supply still come through from extraction.
    assert merged["country"] == "India"


def test_blank_operator_values_do_not_erase_extracted_ones():
    from app.agent.nodes import _merged_record

    merged = _merged_record({
        "extracted": {"batch_number": "OND25B119"},
        "existing": {"batch_number": "", "product_name": None},
    })
    assert merged["batch_number"] == "OND25B119"


# --- heuristics -----------------------------------------------------------
def test_particulate_in_an_injectable_is_critical():
    risk = heuristics.assess_risk(PARTICULATE_EMAIL, "Foreign Matter / Particulate")
    assert risk.severity == "Critical"
    assert risk.regulatory_reportable is True


def test_cosmetic_defect_is_minor():
    risk = heuristics.assess_risk(
        "A few tablets had chipped edges, purely cosmetic, no other issue.",
        "Product Quality Defect",
    )
    assert risk.severity == "Minor"
    assert risk.regulatory_reportable is False


def test_unrecognised_text_defaults_to_major_not_minor():
    """Under-triage is the dangerous error, so the default must not be Minor."""
    risk = heuristics.assess_risk("Something unusual happened with the goods.", None)
    assert risk.severity == "Major"


def test_batch_number_is_extracted_verbatim():
    extracted = heuristics.extract("The affected material is batch OND25B119, please advise.")
    assert extracted.batch_number == "OND25B119"


def test_extraction_never_invents_a_batch_number():
    extracted = heuristics.extract("Some tablets looked broken. Please help.")
    assert extracted.batch_number is None
    assert "batch_number" in extracted.fields_not_found


@pytest.mark.parametrize(
    "text,expected",
    [
        ("visible fungal growth in the bottle", "Microbial Contamination"),
        ("black particles floating in the vial", "Foreign Matter / Particulate"),
        ("small floating particles in four vials", "Foreign Matter / Particulate"),
        ("visible particulate matter", "Foreign Matter / Particulate"),
        ("assay result out of specification", "Analytical / Out of Specification"),
        ("the expiry date on the label is illegible", "Labelling / Artwork Defect"),
        ("temperature excursion during transit", "Shipping, Storage & Logistics"),
        ("patient developed a rash after taking it", "Adverse Event / Medical"),
        # The defect decides the category, not the container it is found in.
        ("12 discolored capsules in a sealed bottle", "Product Quality Defect"),
        ("chipped tablets in the blister", "Product Quality Defect"),
        ("induction seal not adhered to the bottle neck", "Packaging Defect"),
        ("three bottles received with the seal loose", "Packaging Defect"),
    ],
)
def test_category_keyword_routing(text, expected):
    assert heuristics.extract(text).complaint_category == expected


@pytest.mark.parametrize(
    "text,must_not_be",
    [
        # "cap" once matched "capsules" and sent these to Packaging.
        ("discoloured capsules", "Packaging Defect"),
        ("the capsules were crushed", "Packaging Defect"),
        # "oos" once matched "loose".
        ("the closure was loose", "Analytical / Out of Specification"),
        ("loose powder in the carton", "Analytical / Out of Specification"),
    ],
)
def test_keywords_do_not_match_inside_other_words(text, must_not_be):
    """Keywords are matched on word boundaries, not as bare substrings."""
    assert heuristics.extract(text).complaint_category != must_not_be


def test_word_boundary_allows_stems_but_not_mid_word_matches():
    """Only the FRONT of a keyword is anchored.

    That is what the category table needs: stem keywords such as "contaminat"
    must still match "contamination", while "oos" must stop matching "loose".

    Note the boundary does NOT stop a keyword matching the start of a longer
    word - "cap" still matches "capsules" - so the capsule misclassification
    was fixed by dropping "cap" from the table, not by this anchor. Asserted
    here so the distinction is not lost.
    """
    from app.agent.heuristics import _matches

    # Stems keep working.
    assert _matches("visible contamination observed", ("contaminat",))
    assert _matches("the tablets were discoloured", ("discolour",))
    assert _matches("patient was hospitalised", ("hospitalis",))

    # Mid-word matches are gone: "oos" no longer fires inside "loose".
    assert not _matches("the seal was loose", ("oos",))
    assert _matches("the result was oos", ("oos",))

    # Word-START matches remain, which is why "cap" had to be removed.
    assert _matches("discoloured capsules", ("cap",))


def test_site_block_is_inferred_from_dosage_form():
    assert heuristics.extract("particles in the vial").originating_site_block == (
        "Block B - Sterile Injectables"
    )
    assert heuristics.extract("chipped tablets").originating_site_block == (
        "Block A - Oral Solids"
    )
    assert heuristics.extract("nothing identifiable here").originating_site_block == (
        "Not Determined"
    )


def test_completeness_flags_missing_mandatory_fields():
    result = heuristics.completeness({"product_name": "X"})
    assert result.is_complete is False
    assert "batch_number" in result.missing_mandatory
    assert "customer_name" in result.missing_mandatory
    assert result.clarifying_questions


def test_completeness_passes_a_full_record():
    from app.core.enums import MANDATORY_FIELDS

    record = {field: "value" for field in MANDATORY_FIELDS}
    result = heuristics.completeness(record)

    assert result.is_complete is True
    assert result.missing_mandatory == []
