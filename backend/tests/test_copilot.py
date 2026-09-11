"""Tests for the coercion layer between the model and the complaint form.

This is the layer that stops a plausible-but-wrong model output from landing
in a regulated record, so it is worth testing hard.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.enums import ComplaintCategory, ProductType, Severity
from app.services.copilot import (
    _build_prefill,
    _coerce_date,
    _snap_enum,
    _snap_list,
)


# --- date coercion --------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-03-04", "2026-03-04"),
        ("04/03/2026", "2026-03-04"),   # first matching format wins (D/M/Y)
        ("4 Mar 2026", "2026-03-04"),
        ("March 4, 2026", "2026-03-04"),
        ("04.03.2026", "2026-03-04"),
        (date(2026, 3, 4), "2026-03-04"),
    ],
)
def test_coerce_date_accepts_common_formats(raw, expected):
    assert _coerce_date(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [None, "", "not a date", "sometime last week", "0001-01-01", "3025-01-01"],
)
def test_coerce_date_drops_unusable_values(raw):
    """A blank field an operator fills in beats a hallucinated date."""
    assert _coerce_date(raw) is None


# --- enum snapping --------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Packaging Defect", "Packaging Defect"),
        ("packaging defect", "Packaging Defect"),
        ("PACKAGING DEFECT", "Packaging Defect"),
        ("Packaging Defects", "Packaging Defect"),      # near miss, snapped
        ("Adverse Event / Medical", "Adverse Event / Medical"),
    ],
)
def test_snap_enum_normalises_near_misses(raw, expected):
    assert _snap_enum(raw, ComplaintCategory) == expected


@pytest.mark.parametrize("raw", [None, "", "Completely Invented Category", "xyz"])
def test_snap_enum_drops_values_it_cannot_recognise(raw):
    assert _snap_enum(raw, ComplaintCategory) is None


def test_snap_enum_works_across_vocabularies():
    assert _snap_enum("critical", Severity) == "Critical"
    assert _snap_enum("api", ProductType) == "API"


# --- prefill assembly -----------------------------------------------------
def test_prefill_maps_extraction_and_risk_onto_form_fields():
    extracted = {
        "complainant_name": "T. Bergstrom",
        "product_name": "Ondansetron Injection USP 2 mg/mL",
        "batch_number": "OND25B119",
        "complaint_category": "Foreign Matter - Particulate in Parenteral",
        "product_type": "FDF",
        "date_of_complaint": "08/09/2026",
        "sample_available": True,
    }
    risk = {
        "severity": "Critical",
        "risk_score": 91,
        "regulatory_reportable": True,
        "regulatory_rationale": "FAR under 21 CFR 314.81(b)(1)(ii).",
        "recommended_due_days": 3,
    }

    prefill = _build_prefill(extracted, risk, "A summary.", {"source_type": "Email"})

    assert prefill["batch_number"] == "OND25B119"
    # Free text now, so it passes through verbatim rather than snapping.
    assert prefill["complaint_category"] == "Foreign Matter - Particulate in Parenteral"
    assert prefill["severity"] == "Critical"
    assert prefill["risk_score"] == 91
    assert prefill["regulatory_reportable"] is True
    assert prefill["sample_available"] is True
    assert prefill["ai_assisted"] is True
    assert prefill["ai_summary"] == "A summary."
    assert prefill["date_received"] == date.today().isoformat()


def test_due_date_is_derived_from_severity():
    prefill = _build_prefill({}, {"severity": "Critical", "recommended_due_days": 3}, None, {})
    assert prefill["due_date"] == (date.today() + timedelta(days=3)).isoformat()


def test_due_date_falls_back_to_the_severity_tat_table():
    """A model that omits recommended_due_days must not leave the date blank."""
    prefill = _build_prefill({}, {"severity": "Minor"}, None, {})
    assert prefill["due_date"] == (date.today() + timedelta(days=30)).isoformat()


def test_workflow_fields_are_never_auto_filled():
    """Status and assignment are human decisions, not model output."""
    prefill = _build_prefill(
        {"complaint_description": "x"},
        {"severity": "Major"},
        None,
        {},
    )
    for field in ("status", "assigned_to", "department", "complaint_number"):
        assert field not in prefill


def test_unknown_product_type_is_not_prefilled():
    """'Unknown' is a real enum member but a useless thing to put in the form."""
    prefill = _build_prefill({"product_type": "Unknown"}, {}, None, {})
    assert "product_type" not in prefill


def test_category_is_free_text_and_passes_through():
    """complaint_category is model-authored prose, matching the reference UI.

    Trade-off, recorded deliberately: the form shows labels like "Product
    Defect - Discoloration" that no fixed enum contains, so this field is no
    longer snapped to a controlled vocabulary. It is therefore NOT safe to
    trend on directly - severity and product_type remain the controlled fields
    for that. If category-level trending is needed later, derive a normalised
    column from the description rather than constraining this one.
    """
    prefill = _build_prefill(
        {"complaint_category": "Product Defect - Discoloration"}, {}, None, {}
    )
    assert prefill["complaint_category"] == "Product Defect - Discoloration"


def test_severity_is_still_snapped_to_the_controlled_vocabulary():
    """Severity drives the workflow, so it stays constrained."""
    assert _build_prefill({}, {"severity": "critical"}, None, {})["severity"] == "Critical"
    assert "severity" not in _build_prefill({}, {"severity": "Apocalyptic"}, None, {})


# --- dropdown-backed fields ------------------------------------------------
# Regression: the model returned complaint_source="Apollo Pharmacy" (the
# customer, not the channel). "Apollo Pharmacy" is not an option, so the
# <select> rendered BLANK while the value still counted as populated - the
# operator saw an empty field and the record would have committed a value they
# never read. Anything backed by a dropdown must be snapped or dropped.
def test_snap_list_accepts_exact_and_cased_variants():
    from app.core.enums import COMPLAINT_SOURCES

    options = list(COMPLAINT_SOURCES)
    assert _snap_list("Pharmacy", options) == "Pharmacy"
    assert _snap_list("pharmacy", options) == "Pharmacy"
    assert _snap_list("  PHARMACY  ", options) == "Pharmacy"


def test_snap_list_drops_a_value_outside_the_vocabulary():
    from app.core.enums import COMPLAINT_SOURCES

    assert _snap_list("Apollo Pharmacy", list(COMPLAINT_SOURCES)) is None
    assert _snap_list("", list(COMPLAINT_SOURCES)) is None
    assert _snap_list(None, list(COMPLAINT_SOURCES)) is None


def test_customer_name_is_not_leaked_into_complaint_source():
    """The exact failure that motivated this: the pharmacy's NAME is not a source."""
    prefill = _build_prefill(
        {"complaint_source": "Apollo Pharmacy", "customer_name": "Apollo Pharmacy"},
        {},
        None,
        {},
    )
    assert "complaint_source" not in prefill
    assert prefill["customer_name"] == "Apollo Pharmacy"


def test_site_block_is_snapped_and_not_determined_is_left_blank():
    prefill = _build_prefill(
        {"originating_site_block": "block a - oral solids"}, {}, None, {}
    )
    assert prefill["originating_site_block"] == "Block A - Oral Solids"

    # "Not Determined" is a real option but a useless thing to prefill.
    blank = _build_prefill({"originating_site_block": "Not Determined"}, {}, None, {})
    assert "originating_site_block" not in blank

    invented = _build_prefill({"originating_site_block": "Block Z - Wizardry"}, {}, None, {})
    assert "originating_site_block" not in invented


def test_provenance_dict_still_reaches_the_prefill():
    """Guards the shadowing bug: a local named `source` broke this silently."""
    prefill = _build_prefill(
        {"complaint_source": "Pharmacy"},
        {},
        None,
        {"source_type": "Email", "source_reference": "complaint.pdf"},
    )
    assert prefill["source_type"] == "Email"
    assert prefill["source_reference"] == "complaint.pdf"
    assert prefill["complaint_source"] == "Pharmacy"
