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
    # 1. Origin & customer details
    complaint_source: Optional[str] = None
    customer_name: Optional[str] = None
    complainant_name: Optional[str] = None
    complainant_email: Optional[str] = None
    complainant_phone: Optional[str] = None
    country: Optional[str] = None

    # 2. Product & batch identification
    product_name: Optional[str] = None
    product_strength: Optional[str] = None
    product_code: Optional[str] = None
    product_type: Optional[str] = None
    dosage_form: Optional[str] = None
    pack_size: Optional[str] = None
    batch_number: Optional[str] = None
    affected_quantity: Optional[str] = None
    quantity_supplied: Optional[str] = None
    manufacturing_date: Optional[str] = None
    expiry_date: Optional[str] = None

    # 3. Facility & material impact
    originating_site_block: Optional[str] = None
    impacted_npm: Optional[str] = None

    # 4. Defect analysis
    date_of_complaint: Optional[date] = None
    date_received: Optional[date] = None
    complaint_category: Optional[str] = None
    complaint_subcategory: Optional[str] = None
    complaint_description: Optional[str] = None
    sample_available: bool = False
    sample_quantity: Optional[str] = None

    # AI Copilot risk assessment, shown inline on the form
    suggested_next_action: Optional[str] = None
    initial_risk_assessment: Optional[str] = None

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
    """Arguments of the `log_complaint` tool.

    This doubles as the JSON Schema handed to the model, so the field
    descriptions are the tool's documentation - they are what actually steers
    extraction quality. Field names match the form exactly so the frontend can
    apply the result without a mapping layer.
    """

    # --- 1. Origin & customer details ---
    complaint_source: Optional[str] = Field(
        None,
        description="The CHANNEL the complaint arrived through, not the customer's "
                    "name. Exactly one of: Pharmacy, Hospital, Distributor, "
                    "Wholesaler, Regulatory Authority, Direct Customer, Internal, "
                    "Other. If Apollo Pharmacy complains, this is 'Pharmacy' and "
                    "customer_name is 'Apollo Pharmacy'.",
    )
    customer_name: Optional[str] = Field(
        None, description="Name of the complaining organisation, e.g. 'Apollo Pharmacy'"
    )
    complainant_name: Optional[str] = Field(
        None, description="Named individual who raised it, if one is given"
    )
    complainant_email: Optional[str] = None
    complainant_phone: Optional[str] = None
    country: Optional[str] = None

    # --- 2. Product & batch identification ---
    product_name: Optional[str] = Field(
        None, description="Product name WITHOUT the strength, e.g. 'Amoxicillin Capsules'"
    )
    product_strength: Optional[str] = Field(
        None, description="Strength on its own, e.g. '500 mg', '2 mg/mL'"
    )
    product_code: Optional[str] = None
    product_type: Optional[str] = Field(
        None, description="One of: API, FDF, Excipient, Packaging Material, Unknown"
    )
    dosage_form: Optional[str] = Field(None, description="e.g. Capsule, Tablet, Injection")
    pack_size: Optional[str] = None
    batch_number: Optional[str] = Field(
        None, description="Batch or lot number transcribed EXACTLY as written"
    )
    affected_quantity: Optional[str] = Field(
        None, description="How much is affected, with units, e.g. '12 capsules', '2 vials'"
    )
    quantity_supplied: Optional[str] = None
    manufacturing_date: Optional[str] = Field(
        None,
        description="Manufacturing date exactly as the customer expressed it, e.g. "
                    "'March 2026'. Do NOT convert or invent a day.",
    )
    expiry_date: Optional[str] = Field(
        None, description="Expiry date exactly as expressed, e.g. 'February 2028'"
    )

    # --- 3. Facility & material impact ---
    originating_site_block: Optional[str] = Field(
        None,
        description="Which manufacturing block would produce this dosage form. Infer "
                    "from the dosage form when the source does not say. One of: "
                    "Block A - Oral Solids, Block B - Sterile Injectables, "
                    "Block C - API Synthesis, Block D - Liquids & Semi-solids, "
                    "Block E - Packaging & Labelling, External / Contract Site, "
                    "Not Determined",
    )
    impacted_npm: Optional[str] = Field(
        None,
        description="Non-product materials implicated, e.g. 'Primary packaging - HDPE "
                    "bottle and induction seal'. Empty if none is implied.",
    )

    # --- 4. Defect analysis ---
    date_of_complaint: Optional[str] = Field(None, description="ISO date YYYY-MM-DD if stated")
    complaint_category: Optional[str] = Field(
        None,
        description="Short formal category in the form 'Product Defect - Discoloration', "
                    "'Packaging Defect - Seal Failure', 'Labelling Defect - Illegible Print', "
                    "'Analytical - Out of Specification', 'Foreign Matter - Particulate', "
                    "'Microbial Contamination', 'Adverse Event - Medical', "
                    "'Shipping & Storage - Cold Chain Excursion', 'Documentation - CoA'",
    )
    complaint_subcategory: Optional[str] = None
    complaint_description: Optional[str] = Field(
        None,
        description="A formal QMS description synthesised from the customer's report: "
                    "who reported it, what was observed, how many units, and what they "
                    "are requesting. Two to three factual sentences, no speculation "
                    "about cause.",
    )
    sample_available: Optional[bool] = Field(
        None, description="True only if a sample is stated to be retained or returnable"
    )
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

    suggested_next_action: Optional[str] = Field(
        None,
        description="The single concrete next step for QA, phrased as an instruction, "
                    "e.g. 'Route to QA Investigation & Issue Replacement'. Max ~60 chars.",
    )
    initial_risk_assessment: Optional[str] = Field(
        None,
        description="Two sentences of reasoning about the most likely mechanism and what "
                    "it requires, e.g. 'Potential moisture ingress or primary packaging "
                    "seal failure leading to capsule discoloration. Requires retention "
                    "sample examination and batch record review.'",
    )


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


# --------------------------------------------------------------------------
# Conversational copilot
# --------------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """One turn of the copilot conversation.

    `form` carries the current state of the complaint form so the agent can see
    what the operator has already entered and fill only the gaps.
    """

    message: str = Field(..., min_length=1)
    history: List[ChatMessage] = Field(default_factory=list)
    form: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    """What the copilot sends back to the chat panel."""

    reply: str = Field(..., description="The assistant's conversational message")
    # Present only when the log_complaint tool ran on this turn.
    tool_called: Optional[str] = None
    form_update: dict[str, Any] = Field(default_factory=dict)
    copilot: Optional[CopilotResult] = None
    form_complete: bool = False
    degraded: bool = False
    latency_ms: int = 0
