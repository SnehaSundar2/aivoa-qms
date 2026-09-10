"""Tests for the coercion layer between the model and the complaint form.

This is the layer that stops a plausible-but-wrong model output from landing
in a regulated record, so it is worth testing hard.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.enums import ComplaintCategory, ProductType, Severity
from app.services.copilot import _build_prefill, _coerce_date, _snap_enum


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
        "complaint_category": "foreign matter / particulate",
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
    assert prefill["complaint_category"] == "Foreign Matter / Particulate"
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


def test_invented_category_is_dropped_rather_than_guessed():
    prefill = _build_prefill({"complaint_category": "Alien Interference"}, {}, None, {})
    assert "complaint_category" not in prefill
