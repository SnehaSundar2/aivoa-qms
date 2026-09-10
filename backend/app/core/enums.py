"""Controlled vocabularies for the Customer Complaint module.

In a real QMS these live in configurable master data. They are hard-coded here
so the LLM, the API and the UI all agree on exactly one set of values.
"""
from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.value


class ProductType(StrEnum):
    API = "API"                 # Active Pharmaceutical Ingredient
    FDF = "FDF"                 # Finished Dosage Form
    EXCIPIENT = "Excipient"
    PACKAGING = "Packaging Material"
    UNKNOWN = "Unknown"


class ComplaintCategory(StrEnum):
    PRODUCT_QUALITY = "Product Quality Defect"
    PACKAGING = "Packaging Defect"
    LABELLING = "Labelling / Artwork Defect"
    ANALYTICAL = "Analytical / Out of Specification"
    MICROBIAL = "Microbial Contamination"
    FOREIGN_MATTER = "Foreign Matter / Particulate"
    ADVERSE_EVENT = "Adverse Event / Medical"
    SHIPPING = "Shipping, Storage & Logistics"
    DOCUMENTATION = "Documentation / CoA"
    COUNTERFEIT = "Suspected Falsified Product"
    OTHER = "Other"


class Severity(StrEnum):
    """Aligned to the classic GMP complaint triage used for recall decisions."""

    CRITICAL = "Critical"   # potentially life-threatening / Class I recall candidate
    MAJOR = "Major"         # may cause illness or mistreatment / Class II
    MINOR = "Minor"         # unlikely to cause harm / Class III or non-reportable


class ComplaintStatus(StrEnum):
    DRAFT = "Draft"
    OPEN = "Open"
    UNDER_INVESTIGATION = "Under Investigation"
    CAPA_INITIATED = "CAPA Initiated"
    PENDING_CLOSURE = "Pending Closure"
    CLOSED = "Closed"
    REJECTED = "Rejected / Not a Complaint"


class SourceType(StrEnum):
    EMAIL = "Email"
    PDF = "PDF Document"
    IMAGE = "Image / Photograph"
    PHONE = "Phone Call"
    PORTAL = "Customer Portal"
    MANUAL = "Manual Entry"


# Turnaround targets (calendar days) used to propose an investigation due date.
SEVERITY_TAT_DAYS = {
    Severity.CRITICAL: 3,
    Severity.MAJOR: 15,
    Severity.MINOR: 30,
}

# Fields a complaint must carry before it can leave Draft. Drives the
# Completeness Checker node in the agent graph.
MANDATORY_FIELDS = [
    "complainant_name",
    "complainant_organisation",
    "product_name",
    "batch_number",
    "complaint_category",
    "complaint_description",
    "date_of_complaint",
]
