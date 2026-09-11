"""Tests for the edit_complaint tool.

The interesting property is the precedence inversion between the two tools:

    log_complaint   fills gaps, never overwrites operator input
    edit_complaint  overwrites, because the operator asked for the change

Getting that backwards in either direction is a real failure - one silently
discards the operator's corrections, the other makes the edit tool useless
exactly when it is wanted.
"""
from __future__ import annotations

import pytest

from app.agent import llm
from app.agent.tools import EDITABLE_FIELDS, should_edit_complaint
from app.schemas import ComplaintEdit
from app.services import chat as chat_service

POPULATED = {
    "complaint_source": "Pharmacy",
    "customer_name": "Apollo Pharmacy",
    "product_name": "Amoxicillin Capsules",
    "product_strength": "500 mg",
    "batch_number": "AMX240602",
    "affected_quantity": "12 capsules",
    "complaint_category": "Product Defect - Discoloration",
    "complaint_description": "Apollo Pharmacy reported 12 discolored capsules.",
    "severity": "Major",
}


@pytest.fixture(autouse=True)
def _clean_breaker():
    llm.reset_breaker()
    yield
    llm.reset_breaker()


# --- routing ---------------------------------------------------------------
@pytest.mark.parametrize(
    "message",
    [
        "the affected quantity is actually 20 capsules",
        "change the batch number to AMX240603",
        "set severity to Critical",
        "remove the expiry date",
        "sorry, the customer is Ananya Medical",
        "correct the product strength to 250 mg",
        "re-assess the risk please",
    ],
)
def test_amendments_route_to_the_edit_tool(message):
    assert should_edit_complaint(message, POPULATED) is True


@pytest.mark.parametrize(
    "message",
    [
        "What does Major severity mean?",
        "Why is this graded Major?",
        "Who should investigate this?",
    ],
)
def test_questions_do_not_route_to_the_edit_tool(message):
    assert should_edit_complaint(message, POPULATED) is False


def test_a_new_complaint_is_logged_not_treated_as_an_edit():
    """With a populated form, a fresh complaint still means log, not amend."""
    message = (
        "City Hospital reported particles in 3 vials of Ondansetron, batch "
        "OND25B119. Please log this complaint"
    )
    assert should_edit_complaint(message, POPULATED) is False


def test_an_empty_form_is_never_edited():
    """There is nothing to amend before the first complaint is logged."""
    assert should_edit_complaint("change the batch to X", {}) is False


# --- applying the edit -----------------------------------------------------
def _stub_edit(monkeypatch, edit: ComplaintEdit):
    monkeypatch.setattr(
        chat_service, "run_edit_complaint", lambda message, form: edit
    )


def test_only_the_named_fields_change(monkeypatch):
    _stub_edit(monkeypatch, ComplaintEdit(affected_quantity="20 capsules"))

    updates, changed, _edit, error, _deg = chat_service._apply_edit("...", POPULATED)

    assert error is None
    assert updates == {"affected_quantity": "20 capsules"}
    assert changed == ["affected_quantity"]


def test_a_value_identical_to_the_current_one_is_not_a_change(monkeypatch):
    """Avoids flashing a field and writing an audit entry for a no-op."""
    _stub_edit(monkeypatch, ComplaintEdit(affected_quantity="12 capsules"))

    updates, changed, _edit, _error, _deg = chat_service._apply_edit("...", POPULATED)

    assert updates == {}
    assert changed == []


def test_fields_to_clear_blanks_a_populated_field(monkeypatch):
    _stub_edit(monkeypatch, ComplaintEdit(fields_to_clear=["affected_quantity"]))

    updates, changed, _edit, _error, _deg = chat_service._apply_edit("...", POPULATED)

    assert updates == {"affected_quantity": ""}
    assert changed == ["affected_quantity"]


def test_clearing_an_already_empty_field_is_a_no_op(monkeypatch):
    _stub_edit(monkeypatch, ComplaintEdit(fields_to_clear=["impacted_npm"]))

    updates, _changed, _edit, _error, _deg = chat_service._apply_edit("...", POPULATED)

    assert updates == {}


def test_the_tool_cannot_reach_workflow_fields():
    """Status and assignment are human decisions, not editable by the agent."""
    for field in ("status", "assigned_to", "department", "complaint_number", "id"):
        assert field not in EDITABLE_FIELDS


def test_risk_fields_are_editable():
    """The brief asks for the risk assessment to be updatable too."""
    for field in ("severity", "suggested_next_action", "initial_risk_assessment"):
        assert field in EDITABLE_FIELDS


def _break_the_model(monkeypatch):
    def _explode(message, form):
        raise llm.LLMUnavailable("quota exhausted")

    monkeypatch.setattr(chat_service, "run_edit_complaint", _explode)


def test_a_loose_instruction_is_refused_when_the_model_is_down(monkeypatch):
    """Without the model, "make it 20" cannot be resolved - so it is declined."""
    _break_the_model(monkeypatch)

    updates, changed, edit, error, _deg = chat_service._apply_edit(
        "make it 20", POPULATED
    )

    assert updates == {}
    assert changed == []
    assert edit is None
    assert "quota" in error


@pytest.mark.parametrize(
    "message,field,expected",
    [
        ("set severity to Critical", "severity", "Critical"),
        ("change the batch number to AMX240603", "batch_number", "AMX240603"),
        ("the affected quantity is actually 20 capsules", "affected_quantity", "20 capsules"),
    ],
)
def test_an_explicit_instruction_still_works_without_the_model(
    monkeypatch, message, field, expected
):
    """An instruction naming its field and value needs no LLM to understand."""
    _break_the_model(monkeypatch)

    updates, changed, _edit, error, degraded = chat_service._apply_edit(
        message, POPULATED
    )

    assert error is None
    assert updates[field] == expected
    assert changed == [field]
    assert degraded is True, "must be labelled rule-based, not passed off as AI"


def test_the_parser_refuses_a_value_outside_a_controlled_vocabulary(monkeypatch):
    """"set severity to Apocalyptic" must not reach the form."""
    _break_the_model(monkeypatch)

    updates, _changed, edit, error, _deg = chat_service._apply_edit(
        "set severity to Apocalyptic", POPULATED
    )

    assert updates == {}
    assert edit is None
    assert error is not None


def test_reassessment_is_requested_only_when_the_defect_moves():
    """A corrected contact name must not cost a full assessment run."""
    cosmetic = ComplaintEdit(customer_name="Ananya Medical", reassess_risk=False)
    material = ComplaintEdit(
        complaint_category="Foreign Matter - Particulate", reassess_risk=True
    )
    assert cosmetic.reassess_risk is False
    assert material.reassess_risk is True


def test_record_as_text_includes_the_fields_risk_depends_on():
    text = chat_service._record_as_text(POPULATED)
    assert "Amoxicillin Capsules" in text
    assert "AMX240602" in text
    assert "Product Defect - Discoloration" in text
    assert "12 capsules" in text


# --- re-assessment guards --------------------------------------------------
def test_a_degraded_reassessment_does_not_overwrite_a_model_assessment(monkeypatch):
    """Rule output must never replace reasoning already in the record.

    A keyword re-run produces things like "Rule match on quality-defect
    indicators: seal" - strictly worse information than the model's
    explanation of the probable mechanism. Overwriting is a data regression,
    so the existing assessment stands and the operator is told to review it.
    """
    from app.schemas import (
        CompletenessResult,
        CopilotResult,
        ExtractedComplaint,
        RiskAssessmentResult,
    )

    form = {
        **POPULATED,
        "initial_risk_assessment": "Potential moisture ingress or oxidative degradation.",
        "suggested_next_action": "Route to QA Investigation & Issue Replacement",
    }

    _stub_edit(
        monkeypatch,
        ComplaintEdit(affected_quantity="20 capsules", reassess_risk=True),
    )

    degraded_run = CopilotResult(
        extracted=ExtractedComplaint(),
        risk=RiskAssessmentResult(severity="Major", risk_score=62),
        completeness=CompletenessResult(),
        form_prefill={
            "initial_risk_assessment": "Rule-based triage only. Rule match on seal.",
            "suggested_next_action": "Route to QA Investigation & issue replacement",
            "risk_score": 62,
        },
        degraded=True,
    )
    monkeypatch.setattr(chat_service, "run_copilot", lambda **kwargs: degraded_run)

    response = chat_service._handle_edit("...", [], form, 0.0)

    assert "initial_risk_assessment" not in response.form_update
    assert "suggested_next_action" not in response.form_update
    assert response.form_update["affected_quantity"] == "20 capsules"
    assert "severity should be reviewed" in response.reply


def test_a_healthy_reassessment_does_update_the_risk_fields(monkeypatch):
    from app.schemas import CopilotResult, ExtractedComplaint, RiskAssessmentResult
    from app.schemas import CompletenessResult

    _stub_edit(
        monkeypatch,
        ComplaintEdit(
            complaint_category="Foreign Matter - Particulate", reassess_risk=True
        ),
    )
    healthy_run = CopilotResult(
        extracted=ExtractedComplaint(),
        risk=RiskAssessmentResult(severity="Critical", risk_score=90),
        completeness=CompletenessResult(),
        form_prefill={
            "severity": "Critical",
            "initial_risk_assessment": "Visible particulate indicates a sterility risk.",
        },
        degraded=False,
    )
    monkeypatch.setattr(chat_service, "run_copilot", lambda **kwargs: healthy_run)

    response = chat_service._handle_edit("...", [], POPULATED, 0.0)

    assert response.form_update["severity"] == "Critical"
    assert "particulate" in response.form_update["initial_risk_assessment"]


def test_a_no_op_edit_says_so_instead_of_claiming_confusion(monkeypatch):
    """The field was understood; it simply already held that value."""
    _stub_edit(monkeypatch, ComplaintEdit(customer_name="Apollo Pharmacy"))

    response = chat_service._handle_edit("...", [], POPULATED, 0.0)

    assert response.fields_changed == []
    assert "No change needed" in response.reply
    assert "couldn't tell which field" not in response.reply


# --- upload and multi-complaint sequences ----------------------------------
# Regression: two of the three sample complaint emails contain "correct" or
# "not", so with a populated form an UPLOAD was routed to edit_complaint and
# tried to amend the previous complaint with the new one's words.
def test_an_uploaded_complaint_document_is_never_an_edit():
    from pathlib import Path

    from app.agent.tools import looks_like_a_complaint_document

    samples = Path(__file__).resolve().parents[1] / "samples"
    for name in (
        "complaint_email_particulate.txt",
        "complaint_email_api_oos.txt",
        "complaint_email_incomplete.txt",
    ):
        document = (samples / name).read_text(encoding="utf-8")
        assert looks_like_a_complaint_document(document), name
        assert should_edit_complaint(document, POPULATED) is False, name


def test_short_amendments_are_still_edits():
    """The length heuristic must not swallow genuine instructions."""
    for message in (
        "change the batch number to AMX240603",
        "the affected quantity is actually 20 capsules",
        "set severity to Critical",
    ):
        assert should_edit_complaint(message, POPULATED) is True, message


# --- identity conflict -----------------------------------------------------
# Without this, log_complaint's gap-filling merges two complaints: the form
# keeps product A's name and takes product B's batch, describing an event that
# never happened.
def test_a_different_batch_is_a_different_complaint():
    from app.agent.tools import is_a_different_complaint

    assert is_a_different_complaint({"batch_number": "OND25B119"}, POPULATED) is True


def test_the_same_batch_is_the_same_complaint():
    from app.agent.tools import is_a_different_complaint

    assert is_a_different_complaint({"batch_number": "AMX240602"}, POPULATED) is False


def test_a_missing_value_on_either_side_is_not_a_conflict():
    """Absence is not disagreement - gap-filling is exactly what it is for."""
    from app.agent.tools import is_a_different_complaint

    assert is_a_different_complaint({"batch_number": "OND25B119"}, {}) is False
    assert is_a_different_complaint({}, POPULATED) is False
    assert is_a_different_complaint({"affected_quantity": "9 vials"}, POPULATED) is False


def test_case_and_whitespace_do_not_make_it_a_different_complaint():
    from app.agent.tools import is_a_different_complaint

    assert is_a_different_complaint({"batch_number": "  amx240602 "}, POPULATED) is False
