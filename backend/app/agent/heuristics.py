"""Deterministic fallbacks used when Groq is unavailable.

These are not a second-rate copy of the LLM - they exist so the workflow is
demonstrable without an API key, and so a network outage degrades the product
instead of breaking it. Anything produced here is flagged `degraded=True` and
the UI labels it as rule-based, never as an AI assessment.
"""
from __future__ import annotations

import re
from datetime import date

from app.core.enums import ComplaintCategory, ProductType, Severity
from app.schemas import (
    CapaAction,
    CompletenessResult,
    ExtractedComplaint,
    RiskAssessmentResult,
    RootCause,
)

# ---------------------------------------------------------------------------
# Keyword tables
# ---------------------------------------------------------------------------
CATEGORY_KEYWORDS: list[tuple[ComplaintCategory, tuple[str, ...]]] = [
    (ComplaintCategory.ADVERSE_EVENT, ("adverse event", "hospitalis", "hospitaliz", "rash", "anaphyla", "side effect", "patient harm", "injury", "nausea", "lack of efficacy")),
    (ComplaintCategory.COUNTERFEIT, ("counterfeit", "falsified", "tamper", "suspect product", "not genuine")),
    (ComplaintCategory.MICROBIAL, ("microbial", "fungal", "mould", "mold", "bacterial", "sterility", "growth observed", "contaminat")),
    # "particle" (singular stem) deliberately covers particle/particles; it does
    # not cover "particulate", which is listed separately.
    (ComplaintCategory.FOREIGN_MATTER, ("foreign matter", "particle", "particulate", "metal", "glass", "fibre", "fiber", "hair", "insect")),
    (ComplaintCategory.ANALYTICAL, ("out of specification", "oos", "assay", "dissolution", "impurity", "potency", "fails the specification", "result of", "% w/w")),
    (ComplaintCategory.LABELLING, ("label", "artwork", "misprint", "illegible", "wrong text", "mismatch", "barcode")),
    (ComplaintCategory.PACKAGING, ("packaging", "blister", "seal", "cap", "closure", "leak", "container", "carton damaged", "bottle")),
    (ComplaintCategory.SHIPPING, ("cold chain", "temperature excursion", "in transit", "shipment", "logistics", "pallet", "short shipped", "damaged on arrival")),
    (ComplaintCategory.DOCUMENTATION, ("certificate of analysis", "coa", "msds", "missing document", "batch record")),
    (ComplaintCategory.PRODUCT_QUALITY, ("chipped", "broken", "cracked", "discolour", "discolor", "capping", "lamination", "sticking", "mottling", "odour", "odor", "clump", "caking", "crumbl")),
]

CRITICAL_KEYWORDS = (
    "wrong product", "wrong active", "wrong strength", "wrong drug", "mix-up", "mixup",
    "cross-contamination", "cross contamination", "sterility", "sterile", "injection",
    "injectable", "parenteral", "vial", "ampoule", "infusion", "anaphyla",
    "hospitalis", "hospitaliz", "death", "fatal", "counterfeit", "falsified",
    "undeclared allergen", "penicillin",
)
MAJOR_KEYWORDS = (
    "out of specification", "oos", "assay", "dissolution", "impurity", "degradation",
    "microbial", "fungal", "mould", "mold", "foreign matter", "particulate",
    "illegible", "missing tablet", "temperature excursion", "cold chain",
    "seal", "leak", "container closure", "expiry", "potency",
)
MINOR_KEYWORDS = (
    "chipped", "cosmetic", "scratch", "carton", "shipper", "print quality",
    "minor", "outer box", "shade",
)

BATCH_RE = re.compile(r"\b(?:batch|lot|b\.?no\.?|lot\s*no\.?)[\s:#-]*([A-Z0-9][A-Z0-9\-/]{3,})\b", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{7,}\d")
ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
QTY_RE = re.compile(r"\b(\d{1,6})\s*(tablets?|capsules?|vials?|bottles?|units?|packs?|strips?|blisters?|kg|g|ml|l)\b", re.I)


def _find_category(text: str) -> str:
    low = text.lower()
    for category, keywords in CATEGORY_KEYWORDS:
        if any(k in low for k in keywords):
            return category.value
    return ComplaintCategory.OTHER.value


def _find_product_type(text: str) -> str:
    low = text.lower()
    if any(k in low for k in ("api", "active pharmaceutical ingredient", "drug substance", "kg drum", "intermediate")):
        return ProductType.API.value
    if any(k in low for k in ("tablet", "capsule", "syrup", "injection", "vial", "cream", "ointment", "suspension", "blister")):
        return ProductType.FDF.value
    return ProductType.UNKNOWN.value


def extract(text: str) -> ExtractedComplaint:
    """Regex/keyword extraction. Populates only what it can literally find."""
    batch = BATCH_RE.search(text)
    email = EMAIL_RE.search(text)
    phone = PHONE_RE.search(text)
    iso_date = ISO_DATE_RE.search(text)
    qty = QTY_RE.search(text)

    found = {
        "batch_number": batch.group(1) if batch else None,
        "complainant_email": email.group(0) if email else None,
        "complainant_phone": phone.group(0).strip() if phone else None,
        "date_of_complaint": iso_date.group(0) if iso_date else None,
        "quantity_complained": qty.group(0) if qty else None,
        "complaint_category": _find_category(text),
        "product_type": _find_product_type(text),
        "complaint_description": " ".join(text.split())[:1200],
    }
    populated = sum(1 for v in found.values() if v)
    missing = [k for k, v in found.items() if not v]

    return ExtractedComplaint(
        **found,
        extraction_confidence=round(min(0.55, populated / 12), 2),
        fields_not_found=missing,
    )


def assess_risk(text: str, category: str | None) -> RiskAssessmentResult:
    low = (text or "").lower()
    cat = category or ""

    critical_hits = [k for k in CRITICAL_KEYWORDS if k in low]
    major_hits = [k for k in MAJOR_KEYWORDS if k in low]
    minor_hits = [k for k in MINOR_KEYWORDS if k in low]

    if critical_hits or cat in (ComplaintCategory.ADVERSE_EVENT.value, ComplaintCategory.COUNTERFEIT.value):
        severity, score = Severity.CRITICAL, 88
        reason = f"Rule match on high-harm indicators: {', '.join(critical_hits[:4]) or cat}."
        reportable = True
        reg = ("Potential FDA Field Alert Report under 21 CFR 314.81(b)(1)(ii) "
               "(3 working days) and a recall health-hazard evaluation.")
    elif major_hits or cat in (
        ComplaintCategory.ANALYTICAL.value,
        ComplaintCategory.MICROBIAL.value,
        ComplaintCategory.FOREIGN_MATTER.value,
    ):
        severity, score = Severity.MAJOR, 62
        reason = f"Rule match on quality-defect indicators: {', '.join(major_hits[:4]) or cat}."
        reportable = True
        reg = "Assess for Field Alert Report; confirm during investigation."
    elif minor_hits:
        severity, score = Severity.MINOR, 25
        reason = f"Rule match on cosmetic indicators: {', '.join(minor_hits[:4])}."
        reportable = False
        reg = "No health-authority notification expected for a cosmetic defect."
    else:
        severity, score = Severity.MAJOR, 50
        reason = ("No decisive keyword match. Defaulted to Major so the complaint is "
                  "not under-triaged; QA must classify manually.")
        reportable = False
        reg = "Reportability undetermined - requires QA review."

    from app.core.enums import SEVERITY_TAT_DAYS

    return RiskAssessmentResult(
        severity=severity.value,
        risk_score=score,
        confidence=0.35,
        patient_safety_impact="Not evaluated by rules - requires QA assessment.",
        gxp_impact="GMP-relevant: complaint records are subject to 21 CFR 211.198.",
        regulatory_reportable=reportable,
        regulatory_rationale=reg,
        rationale=f"Rule-based triage (Groq unavailable). {reason}",
        recommended_due_days=SEVERITY_TAT_DAYS[severity],
    )


GENERIC_ROOT_CAUSES: dict[str, list[tuple[str, str, str, str]]] = {
    ComplaintCategory.PRODUCT_QUALITY.value: [
        ("Compression parameters drifted, producing low tablet hardness", "Machine", "High",
         "Review in-process hardness, friability and compression force data for the batch"),
        ("Granulation moisture outside the target range", "Method", "Medium",
         "Check LOD results at the drying step in the batch record"),
        ("Mechanical damage during packaging or transport", "Machine", "Medium",
         "Inspect the retention sample and the packaging line deduster settings"),
        ("Excipient lot variability affecting binding", "Material", "Medium",
         "Compare the excipient lot CoA against previous batches"),
    ],
    ComplaintCategory.PACKAGING.value: [
        ("Sealing temperature or dwell time outside validated range", "Machine", "High",
         "Review blister/induction sealer parameter logs for the batch"),
        ("Container closure component out of dimensional tolerance", "Material", "Medium",
         "Check incoming inspection records for the closure lot"),
        ("Line clearance or changeover not fully effective", "Method", "Medium",
         "Review line clearance records for the shift"),
    ],
    ComplaintCategory.FOREIGN_MATTER.value: [
        ("Wear debris from equipment contact parts", "Machine", "High",
         "Inspect sieves, punches and contact parts; review the preventive maintenance log"),
        ("Environmental contamination in the manufacturing area", "Environment", "Medium",
         "Review environmental monitoring and differential pressure records for the date"),
        ("Contaminant present in an incoming raw material", "Material", "Medium",
         "Re-test the retained raw material sample"),
        ("Operator-borne contamination (fibre, hair)", "Man", "Low",
         "Review gowning compliance records for the shift"),
    ],
    ComplaintCategory.ANALYTICAL.value: [
        ("Analytical method not performed as validated at the customer site", "Measurement", "High",
         "Request the customer's raw analytical data and method version"),
        ("Degradation from storage or transport conditions after despatch", "Environment", "High",
         "Review the shipping temperature record and the stability data at that time point"),
        ("Genuine process variability affecting content uniformity", "Method", "Medium",
         "Re-test the retention sample against the same specification"),
    ],
    ComplaintCategory.SHIPPING.value: [
        ("Cold-chain packaging configuration inadequate for the transit duration", "Method", "High",
         "Review the shipper qualification data against the actual transit profile"),
        ("Data logger placement or excursion during a handover", "Measurement", "Medium",
         "Retrieve the full logger trace and the courier handover timestamps"),
        ("Pallet stacking or handling damage in transit", "Machine", "Medium",
         "Review the carrier proof-of-delivery photographs and damage report"),
    ],
}

DEFAULT_ROOT_CAUSES = [
    ("Manufacturing process parameter outside the validated range", "Method", "Medium",
     "Review the batch manufacturing record against the validated parameters"),
    ("Raw material or component quality variation", "Material", "Medium",
     "Review incoming material CoA and the retained sample"),
    ("Equipment malfunction or inadequate maintenance", "Machine", "Medium",
     "Review the equipment log and preventive maintenance history for the period"),
    ("Handling or storage deviation after despatch", "Environment", "Medium",
     "Request the customer's storage and handling records since receipt"),
]


def root_causes(category: str | None) -> list[RootCause]:
    table = GENERIC_ROOT_CAUSES.get(category or "", DEFAULT_ROOT_CAUSES)
    return [
        RootCause(
            cause=c,
            category=bucket,
            likelihood=likelihood,
            rationale="Rule-based suggestion from the standard cause library for this defect type.",
            investigation_step=step,
        )
        for c, bucket, likelihood, step in table
    ]


def capa(severity: str | None) -> list[CapaAction]:
    urgent = severity == Severity.CRITICAL.value
    return [
        CapaAction(
            action="Quarantine all remaining stock of the affected batch at the site and in the distribution chain",
            type="Correction", owner_function="QA", target_days=1 if urgent else 3,
            rationale="Contain the effect before the investigation concludes.",
        ),
        CapaAction(
            action="Retrieve and examine the retention sample against the original specification",
            type="Correction", owner_function="QC", target_days=3 if urgent else 7,
            rationale="Establish whether the defect is present in the retained material.",
        ),
        CapaAction(
            action="Extend the assessment to all batches manufactured on the same line and campaign",
            type="Preventive Action", owner_function="QA", target_days=14 if urgent else 30,
            rationale="Determine the true scope before deciding on field action.",
        ),
        CapaAction(
            action="Confirm the root cause and revise the affected SOP or process parameter under change control",
            type="Corrective Action", owner_function="Production", target_days=30 if urgent else 60,
            rationale="Address recurrence once the investigation identifies the cause.",
        ),
        CapaAction(
            action="Verify effectiveness by trending the same defect type for three subsequent batches",
            type="Preventive Action", owner_function="QA", target_days=90,
            rationale="ICH Q10 requires CAPA effectiveness to be demonstrated, not assumed.",
        ),
    ]


def summary(data: dict) -> str:
    org = data.get("complainant_organisation") or data.get("complainant_name") or "An unidentified complainant"
    product = data.get("product_name") or "an unspecified product"
    batch = data.get("batch_number")
    batch_txt = f"batch {batch}" if batch else "an unrecorded batch number"
    qty = data.get("quantity_complained")
    qty_txt = f" affecting {qty}" if qty else ""
    category = data.get("complaint_category") or "an unclassified defect"
    severity = data.get("severity") or "unclassified"
    return (
        f"{org} reported {category.lower()} for {product} ({batch_txt}){qty_txt}. "
        f"Preliminary rule-based triage classifies this as {severity}. "
        "This summary was generated without the language model and must be reviewed by QA."
    )


def completeness(data: dict) -> CompletenessResult:
    from app.core.enums import MANDATORY_FIELDS

    recommended = ["complainant_email", "quantity_complained", "expiry_date", "dosage_form", "country"]
    missing_mandatory = [f for f in MANDATORY_FIELDS if not data.get(f)]
    missing_recommended = [f for f in recommended if not data.get(f)]

    question_bank = {
        "batch_number": "Please provide the batch/lot number printed on the carton and on the immediate container.",
        "product_name": "Please confirm the exact product name and strength as printed on the pack.",
        "complainant_organisation": "Please confirm the name and address of the organisation raising the complaint.",
        "complainant_name": "Please provide the name and contact details of the person reporting the issue.",
        "complaint_description": "Please describe what was observed, when it was first noticed, and how many units are affected.",
        "date_of_complaint": "On what date was the problem first observed?",
        "complaint_category": "Please clarify the nature of the defect so it can be categorised.",
        "quantity_complained": "How many units are affected, and out of what total quantity received?",
        "expiry_date": "Please provide the expiry date printed on the pack.",
    }
    questions = [question_bank[f] for f in (missing_mandatory + missing_recommended) if f in question_bank][:5]

    total = len(MANDATORY_FIELDS) + len(recommended)
    present = total - len(missing_mandatory) - len(missing_recommended)
    return CompletenessResult(
        is_complete=not missing_mandatory,
        score=int(round(present / total * 100)),
        missing_mandatory=missing_mandatory,
        missing_recommended=missing_recommended,
        clarifying_questions=questions,
    )


def looks_like_complaint(text: str) -> bool:
    low = (text or "").lower()
    negative = ("purchase order", "request for quotation", "rfq", "invoice", "newsletter", "unsubscribe")
    positive = ("complaint", "defect", "damaged", "contaminat", "not acceptable", "issue with",
                "problem with", "failed", "out of specification", "return", "reject")
    if any(n in low for n in negative) and not any(p in low for p in positive):
        return False
    return True
