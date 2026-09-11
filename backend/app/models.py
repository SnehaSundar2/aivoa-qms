"""SQLAlchemy ORM models for the Customer Complaint module."""
from datetime import date, datetime

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Complaint(Base):
    """A customer complaint record (21 CFR 211.198 / EU GMP Ch.8 style)."""

    __tablename__ = "complaints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    complaint_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)

    # --- 1. Origin & customer details ---
    complaint_source: Mapped[str | None] = mapped_column(String(80))
    customer_name: Mapped[str | None] = mapped_column(String(200), index=True)
    complainant_name: Mapped[str | None] = mapped_column(String(160))
    complainant_email: Mapped[str | None] = mapped_column(String(160))
    complainant_phone: Mapped[str | None] = mapped_column(String(60))
    country: Mapped[str | None] = mapped_column(String(80))

    # --- 2. Product & batch identification ---
    product_name: Mapped[str | None] = mapped_column(String(200), index=True)
    product_strength: Mapped[str | None] = mapped_column(String(80))
    product_code: Mapped[str | None] = mapped_column(String(80))
    product_type: Mapped[str | None] = mapped_column(String(40))
    dosage_form: Mapped[str | None] = mapped_column(String(80))
    pack_size: Mapped[str | None] = mapped_column(String(80))
    batch_number: Mapped[str | None] = mapped_column(String(80), index=True)
    affected_quantity: Mapped[str | None] = mapped_column(String(80))
    quantity_supplied: Mapped[str | None] = mapped_column(String(80))

    # Stored as free text, not Date. The customer writes "March 2026" or
    # "03/2026" and a complaint record must transcribe what they actually
    # said - inventing a day to satisfy a DATE column would be a data
    # integrity problem, and month precision is normal for batch dates.
    manufacturing_date: Mapped[str | None] = mapped_column(String(40))
    expiry_date: Mapped[str | None] = mapped_column(String(40))

    # --- 3. Facility & material impact ---
    originating_site_block: Mapped[str | None] = mapped_column(String(120))
    impacted_npm: Mapped[str | None] = mapped_column(String(300))

    # --- 4. Defect analysis ---
    date_of_complaint: Mapped[date | None] = mapped_column(Date)
    date_received: Mapped[date | None] = mapped_column(Date)
    complaint_category: Mapped[str | None] = mapped_column(String(120), index=True)
    complaint_subcategory: Mapped[str | None] = mapped_column(String(120))
    complaint_description: Mapped[str | None] = mapped_column(Text)
    sample_available: Mapped[bool] = mapped_column(Boolean, default=False)
    sample_quantity: Mapped[str | None] = mapped_column(String(80))

    # --- AI Copilot risk assessment (shown inline on the form) ---
    suggested_next_action: Mapped[str | None] = mapped_column(String(300))
    initial_risk_assessment: Mapped[str | None] = mapped_column(Text)

    # --- Triage / workflow ---
    severity: Mapped[str | None] = mapped_column(String(20), index=True)
    risk_score: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="Draft", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(120))
    department: Mapped[str | None] = mapped_column(String(120))
    investigation_required: Mapped[bool] = mapped_column(Boolean, default=True)
    due_date: Mapped[date | None] = mapped_column(Date)
    regulatory_reportable: Mapped[bool] = mapped_column(Boolean, default=False)
    regulatory_rationale: Mapped[str | None] = mapped_column(Text)

    # --- Provenance ---
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_reference: Mapped[str | None] = mapped_column(String(300))
    source_text: Mapped[str | None] = mapped_column(Text)
    ai_assisted: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_summary: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    assessments: Mapped[list["RiskAssessment"]] = relationship(
        back_populates="complaint", cascade="all, delete-orphan"
    )
    audit_entries: Mapped[list["AuditEntry"]] = relationship(
        back_populates="complaint", cascade="all, delete-orphan"
    )

    @property
    def searchable_text(self) -> str:
        parts = [
            self.product_name, self.batch_number, self.complaint_category,
            self.complaint_description, self.customer_name,
        ]
        return " ".join(p for p in parts if p)


class RiskAssessment(Base):
    """One AI Copilot run against a complaint. Kept as history, never overwritten."""

    __tablename__ = "risk_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    complaint_id: Mapped[int | None] = mapped_column(
        ForeignKey("complaints.id", ondelete="CASCADE"), index=True
    )

    severity: Mapped[str | None] = mapped_column(String(20))
    risk_score: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    patient_safety_impact: Mapped[str | None] = mapped_column(Text)
    gxp_impact: Mapped[str | None] = mapped_column(Text)
    regulatory_reportable: Mapped[bool] = mapped_column(Boolean, default=False)
    regulatory_rationale: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)

    # JSON-encoded lists, stored as text to stay portable across MySQL/Postgres/SQLite
    probable_root_causes: Mapped[str | None] = mapped_column(Text)
    capa_recommendations: Mapped[str | None] = mapped_column(Text)
    completeness: Mapped[str | None] = mapped_column(Text)
    duplicates: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)

    model_used: Mapped[str | None] = mapped_column(String(80))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    complaint: Mapped["Complaint"] = relationship(back_populates="assessments")


class AuditEntry(Base):
    """Minimal ALCOA+ style audit trail: who did what, when, and why."""

    __tablename__ = "audit_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    complaint_id: Mapped[int | None] = mapped_column(
        ForeignKey("complaints.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(80))
    actor: Mapped[str] = mapped_column(String(120), default="system")
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    complaint: Mapped["Complaint"] = relationship(back_populates="audit_entries")
