"""CRUD + workflow endpoints for complaint records."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import (
    COMPLAINT_SOURCES,
    SITE_BLOCKS,
    ComplaintCategory,
    ComplaintStatus,
    ProductType,
    Severity,
    SourceType,
)
from app.models import AuditEntry, Complaint, RiskAssessment
from app.schemas import (
    ComplaintCreate,
    ComplaintListOut,
    ComplaintOut,
    ComplaintUpdate,
    CopilotResult,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/complaints", tags=["complaints"])


def _next_complaint_number(db: Session) -> str:
    """Sequential per calendar year: CC-2026-0001.

    Uses a count within the year prefix. A production system would use a DB
    sequence or a dedicated numbering table to stay safe under concurrency.
    """
    year = date.today().year
    prefix = f"CC-{year}-"
    count = db.scalar(
        select(func.count(Complaint.id)).where(Complaint.complaint_number.like(f"{prefix}%"))
    ) or 0

    # Guard against a gap-induced collision if records were deleted.
    for offset in range(1, 1000):
        candidate = f"{prefix}{count + offset:04d}"
        if not db.scalar(select(Complaint.id).where(Complaint.complaint_number == candidate)):
            return candidate
    raise HTTPException(500, "Could not allocate a complaint number")


def _audit(db: Session, complaint_id: int | None, action: str, detail: str = "", actor: str = "qa.officer") -> None:
    db.add(AuditEntry(complaint_id=complaint_id, action=action, detail=detail, actor=actor))


@router.get("/metadata")
def metadata() -> dict:
    """Controlled vocabularies for the form dropdowns.

    Served from the backend so the UI can never offer a value the API rejects.
    """
    return {
        "categories": [c.value for c in ComplaintCategory],
        "severities": [s.value for s in Severity],
        "statuses": [s.value for s in ComplaintStatus],
        "product_types": [p.value for p in ProductType],
        "source_types": [s.value for s in SourceType],
        "departments": ["Quality Assurance", "Quality Control", "Production",
                        "Regulatory Affairs", "Supply Chain", "Engineering"],
        "site_blocks": list(SITE_BLOCKS),
        "complaint_sources": list(COMPLAINT_SOURCES),
    }


@router.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    """Dashboard counters."""
    total = db.scalar(select(func.count(Complaint.id))) or 0

    by_severity = {
        row[0] or "Unclassified": row[1]
        for row in db.execute(
            select(Complaint.severity, func.count(Complaint.id)).group_by(Complaint.severity)
        ).all()
    }
    by_status = {
        row[0] or "Unknown": row[1]
        for row in db.execute(
            select(Complaint.status, func.count(Complaint.id)).group_by(Complaint.status)
        ).all()
    }
    by_category = {
        row[0] or "Uncategorised": row[1]
        for row in db.execute(
            select(Complaint.complaint_category, func.count(Complaint.id))
            .group_by(Complaint.complaint_category)
        ).all()
    }

    open_statuses = [
        ComplaintStatus.OPEN.value,
        ComplaintStatus.UNDER_INVESTIGATION.value,
        ComplaintStatus.CAPA_INITIATED.value,
        ComplaintStatus.PENDING_CLOSURE.value,
    ]
    overdue = db.scalar(
        select(func.count(Complaint.id)).where(
            Complaint.due_date.is_not(None),
            Complaint.due_date < date.today(),
            Complaint.status.in_(open_statuses),
        )
    ) or 0

    return {
        "total": total,
        "open": sum(by_status.get(s, 0) for s in open_statuses),
        "critical": by_severity.get(Severity.CRITICAL.value, 0),
        "overdue": overdue,
        "ai_assisted": db.scalar(select(func.count(Complaint.id)).where(Complaint.ai_assisted.is_(True))) or 0,
        "by_severity": by_severity,
        "by_status": by_status,
        "by_category": by_category,
    }


@router.get("", response_model=ComplaintListOut)
def list_complaints(
    db: Session = Depends(get_db),
    q: str | None = Query(None, description="Free-text search across product, batch and description"),
    status: str | None = None,
    severity: str | None = None,
    category: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
) -> ComplaintListOut:
    stmt = select(Complaint)

    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            Complaint.product_name.ilike(like)
            | Complaint.batch_number.ilike(like)
            | Complaint.complaint_description.ilike(like)
            | Complaint.complaint_number.ilike(like)
            | Complaint.complainant_organisation.ilike(like)
        )
    if status:
        stmt = stmt.where(Complaint.status == status)
    if severity:
        stmt = stmt.where(Complaint.severity == severity)
    if category:
        stmt = stmt.where(Complaint.complaint_category == category)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(Complaint.created_at.desc()).limit(limit).offset(offset)
    ).scalars().all()

    return ComplaintListOut(items=[ComplaintOut.model_validate(r) for r in rows], total=total)


@router.get("/{complaint_id}", response_model=ComplaintOut)
def get_complaint(complaint_id: int, db: Session = Depends(get_db)) -> ComplaintOut:
    row = db.get(Complaint, complaint_id)
    if not row:
        raise HTTPException(404, "Complaint not found")
    return ComplaintOut.model_validate(row)


@router.get("/{complaint_id}/assessments")
def get_assessments(complaint_id: int, db: Session = Depends(get_db)) -> list[dict]:
    """AI Copilot history for a complaint - newest first, never overwritten."""
    if not db.get(Complaint, complaint_id):
        raise HTTPException(404, "Complaint not found")

    rows = db.execute(
        select(RiskAssessment)
        .where(RiskAssessment.complaint_id == complaint_id)
        .order_by(RiskAssessment.created_at.desc())
    ).scalars().all()

    def _load(raw: str | None):
        try:
            return json.loads(raw) if raw else []
        except json.JSONDecodeError:
            return []

    return [
        {
            "id": r.id,
            "severity": r.severity,
            "risk_score": r.risk_score,
            "confidence": r.confidence,
            "patient_safety_impact": r.patient_safety_impact,
            "gxp_impact": r.gxp_impact,
            "regulatory_reportable": r.regulatory_reportable,
            "regulatory_rationale": r.regulatory_rationale,
            "rationale": r.rationale,
            "root_causes": _load(r.probable_root_causes),
            "capa": _load(r.capa_recommendations),
            "completeness": _load(r.completeness),
            "duplicates": _load(r.duplicates),
            "summary": r.summary,
            "model_used": r.model_used,
            "latency_ms": r.latency_ms,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/{complaint_id}/audit")
def get_audit(complaint_id: int, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(AuditEntry)
        .where(AuditEntry.complaint_id == complaint_id)
        .order_by(AuditEntry.created_at.desc())
    ).scalars().all()
    return [
        {"id": r.id, "action": r.action, "actor": r.actor, "detail": r.detail, "created_at": r.created_at}
        for r in rows
    ]


@router.post("", response_model=ComplaintOut, status_code=201)
def create_complaint(payload: ComplaintCreate, db: Session = Depends(get_db)) -> ComplaintOut:
    row = Complaint(**payload.model_dump(), complaint_number=_next_complaint_number(db))
    if not row.date_received:
        row.date_received = date.today()

    db.add(row)
    db.flush()
    _audit(
        db, row.id, "CREATED",
        f"Complaint logged via {row.source_type or 'Manual Entry'}"
        + (" with AI assistance" if row.ai_assisted else ""),
    )
    db.commit()
    db.refresh(row)
    logger.info("Created %s (severity=%s)", row.complaint_number, row.severity)
    return ComplaintOut.model_validate(row)


@router.post("/{complaint_id}/assessment", status_code=201)
def attach_assessment(
    complaint_id: int, payload: CopilotResult, db: Session = Depends(get_db)
) -> dict:
    """Persist a copilot run against a saved complaint, for the audit trail."""
    if not db.get(Complaint, complaint_id):
        raise HTTPException(404, "Complaint not found")

    row = RiskAssessment(
        complaint_id=complaint_id,
        severity=payload.risk.severity,
        risk_score=payload.risk.risk_score,
        confidence=payload.risk.confidence,
        patient_safety_impact=payload.risk.patient_safety_impact,
        gxp_impact=payload.risk.gxp_impact,
        regulatory_reportable=payload.risk.regulatory_reportable,
        regulatory_rationale=payload.risk.regulatory_rationale,
        rationale=payload.risk.rationale,
        probable_root_causes=json.dumps([rc.model_dump() for rc in payload.root_causes]),
        capa_recommendations=json.dumps([c.model_dump() for c in payload.capa]),
        completeness=json.dumps(payload.completeness.model_dump()),
        duplicates=json.dumps([d.model_dump() for d in payload.duplicates]),
        summary=payload.summary,
        model_used=", ".join(payload.models_used) or ("rule-based" if payload.degraded else None),
        latency_ms=payload.latency_ms,
    )
    db.add(row)
    db.flush()
    _audit(
        db, complaint_id, "AI_ASSESSMENT",
        f"Copilot run: severity={payload.risk.severity}, score={payload.risk.risk_score}, "
        f"nodes={' -> '.join(payload.trace)}",
        actor="ai.copilot",
    )
    db.commit()
    return {"id": row.id, "status": "saved"}


@router.patch("/{complaint_id}", response_model=ComplaintOut)
def update_complaint(
    complaint_id: int, payload: ComplaintUpdate, db: Session = Depends(get_db)
) -> ComplaintOut:
    row = db.get(Complaint, complaint_id)
    if not row:
        raise HTTPException(404, "Complaint not found")

    changes = payload.model_dump(exclude_unset=True)
    changed_fields = []
    for key, value in changes.items():
        if getattr(row, key, None) != value:
            changed_fields.append(key)
            setattr(row, key, value)

    if changed_fields:
        _audit(db, row.id, "UPDATED", "Fields changed: " + ", ".join(sorted(changed_fields)))
    db.commit()
    db.refresh(row)
    return ComplaintOut.model_validate(row)


# response_model=None is required: FastAPI would otherwise infer the model from
# the `-> None` return annotation, and NoneType is truthy, which trips its
# "204 must not have a response body" assertion at import time.
@router.delete("/{complaint_id}", status_code=204, response_model=None)
def delete_complaint(complaint_id: int, db: Session = Depends(get_db)) -> None:
    """Present for demo convenience only.

    A real QMS never hard-deletes a complaint record - it would be cancelled
    with a reason and retained for the statutory period.
    """
    row = db.get(Complaint, complaint_id)
    if not row:
        raise HTTPException(404, "Complaint not found")
    db.delete(row)
    db.commit()
