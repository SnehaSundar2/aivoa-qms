"""Pydantic contracts.

These serve three purposes at once:
  1. FastAPI request/response validation,
  2. the JSON schema handed to the LLM for structured output,
  3. the shape the Redux store on the frontend mirrors.
Keeping one definition avoids the three drifting apart.
"""
from datetime import date, datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------
# Complaint CRUD
# --------------------------------------------------------------------------
class ComplaintBase(BaseModel):
    complainant_name: Optional[str] = None
    complainant_organisation: Optional[str] = None
    complainant_email: Optional[str] = None
    complainant_phone: Optional[str] = None
    country: Optional[str] = None

    product_name: Optional[str] = None
    product_code: Optional[str] = None
    product_type: Optional[str] = None
    dosage_form: Optional[str] = None
    strength: Optional[str] = None
    pack_size: Optional[str] = None
    batch_number: Optional[str] = None
    manufacturing_date: Optional[date] = None
    expiry_date: Optional[date] = None
    quantity_supplied: Optional[str] = None
    quantity_complained: Optional[str] = None

    date_of_complaint: Optional[date] = None
    date_received: Optional[date] = None
    complaint_category: Optional[str] = None
    complaint_subcategory: Optional[str] = None
    complaint_description: Optional[str] = None
    sample_available: bool = False
    sample_quantity: Optional[str] = None

    severity: Optional[str] = None
    risk_score: Optional[int] = None
    status: str = "Draft"
    assigned_to: Optional[str] = None
    department: Optional[str] = None
    investigation_required: bool = True
    due_date: Optional[date] = None
    regulatory_reportable: bool = False
    regulatory_rationale: Optional[str] = None

    source_type: Optional[str] = None
    source_reference: Optional[str] = None
    source_text: Optional[str] = None
    ai_assisted: bool = False
    ai_summary: Optional[str] = None


class ComplaintCreate(ComplaintBase):
    pass


class ComplaintUpdate(ComplaintBase):
    status: Optional[str] = None
    sample_available: Optional[bool] = None
    investigation_required: Optional[bool] = None
    regulatory_reportable: Optional[bool] = None
    ai_assisted: Optional[bool] = None


class ComplaintOut(ComplaintBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    complaint_number: str
    created_at: datetime
    updated_at: datetime


class ComplaintListOut(BaseModel):
    items: List[ComplaintOut]
    total: int


# --------------------------------------------------------------------------
# AI Copilot - structured outputs
# --------------------------------------------------------------------------
class ExtractedComplaint(BaseModel):
    """What the extraction node pulls out of an unstructured source."""

    complainant_name: Optional[str] = Field(None, description="Person who raised the complaint")
    complainant_organisation: Optional[str] = Field(None, description="Customer company, hospital or distributor")
    complainant_email: Optional[str] = None
    complainant_phone: Optional[str] = None
    country: Optional[str] = None

    product_name: Optional[str] = None
    product_code: Optional[str] = Field(None, description="Internal product or material code if quoted")
    product_type: Optional[str] = Field(None, description="One of: API, FDF, Excipient, Packaging Material, Unknown")
    dosage_form: Optional[str] = Field(None, description="e.g. Tablet, Capsule, Injection, Powder")
    strength: Optional[str] = None
    pack_size: Optional[str] = None
    batch_number: Optional[str] = Field(None, description="Batch or lot number exactly as quoted")
    manufacturing_date: Optional[str] = Field(None, description="ISO date YYYY-MM-DD if determinable")
    expiry_date: Optional[str] = Field(None, description="ISO date YYYY-MM-DD if determinable")
    quantity_supplied: Optional[str] = None
    quantity_complained: Optional[str] = Field(None, description="How many units are affected")

    date_of_complaint: Optional[str] = Field(None, description="ISO date the customer raised it")
    complaint_category: Optional[str] = Field(None, description="Must be one of the allowed categories")
    complaint_subcategory: Optional[str] = Field(None, description="Short free-text refinement, e.g. Chipped tablets")
    complaint_description: Optional[str] = Field(None, description="Factual restatement of the defect, no speculation")
    sample_available: Optional[bool] = Field(None, description="True only if the source says a sample is retained or returned")
    sample_quantity: Optional[str] = None

    extraction_confidence: float = Field(0.0, ge=0.0, le=1.0)
    fields_not_found: List[str] = Field(default_factory=list)


class RootCause(BaseModel):
    cause: str
    category: str = Field(..., description="Ishikawa bucket: Man, Machine, Material, Method, Measurement, Environment")
    likelihood: Literal["High", "Medium", "Low"] = "Medium"
    rationale: Optional[str] = None
    investigation_step: Optional[str] = Field(None, description="Concrete next check to confirm or rule this out")


class CapaAction(BaseModel):
    action: str
    type: Literal["Correction", "Corrective Action", "Preventive Action"] = "Corrective Action"
    owner_function: Optional[str] = Field(None, description="e.g. QA, QC, Production, Engineering, Warehouse")
    target_days: Optional[int] = None
    rationale: Optional[str] = None


class CompletenessResult(BaseModel):
    is_complete: bool = False
    score: int = Field(0, ge=0, le=100)
    missing_mandatory: List[str] = Field(default_factory=list)
    missing_recommended: List[str] = Field(default_factory=list)
    clarifying_questions: List[str] = Field(default_factory=list)


class DuplicateCandidate(BaseModel):
    complaint_id: int
    complaint_number: str
    product_name: Optional[str] = None
    batch_number: Optional[str] = None
    similarity: float = Field(0.0, ge=0.0, le=1.0)
    reason: str


class RiskAssessmentResult(BaseModel):
    severity: Literal["Critical", "Major", "Minor"] = "Minor"
    risk_score: int = Field(0, ge=0, le=100)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    patient_safety_impact: Optional[str] = None
    gxp_impact: Optional[str] = None
    regulatory_reportable: bool = False
    regulatory_rationale: Optional[str] = None
    rationale: Optional[str] = None
    recommended_due_days: Optional[int] = None


class CopilotResult(BaseModel):
    """The complete payload the AI Copilot panel renders."""

    extracted: ExtractedComplaint
    risk: RiskAssessmentResult
    completeness: CompletenessResult
    root_causes: List[RootCause] = Field(default_factory=list)
    capa: List[CapaAction] = Field(default_factory=list)
    duplicates: List[DuplicateCandidate] = Field(default_factory=list)
    summary: Optional[str] = None

    form_prefill: dict[str, Any] = Field(default_factory=dict)
    source_type: Optional[str] = None
    source_reference: Optional[str] = None
    source_text: Optional[str] = None
    is_complaint: bool = True
    rejection_reason: Optional[str] = None

    trace: List[str] = Field(default_factory=list, description="Ordered LangGraph nodes that executed")
    models_used: List[str] = Field(default_factory=list)
    latency_ms: int = 0
    degraded: bool = Field(False, description="True when the LLM was unavailable and heuristics were used")


class IntakeTextRequest(BaseModel):
    text: str = Field(..., min_length=10)
    source_type: Optional[str] = "Manual Entry"
    source_reference: Optional[str] = None


class ReassessRequest(BaseModel):
    """Re-run the copilot against whatever is currently in the form."""

    complaint: ComplaintBase
