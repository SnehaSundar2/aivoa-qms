"""Duplicate complaint detection.

Deliberately deterministic. Asking an LLM "is this a duplicate?" against a
growing complaint history is slow, expensive and non-reproducible - and a QMS
needs the same input to give the same answer every time it is run. Instead we
score candidates on features that actually matter in a complaint context and
let a human confirm.

Scoring weights, and why:
  batch + product match     0.55  - the strongest signal by far; the same defect
                                    on the same batch is almost always one event
  product only              0.20  - same product, different batch is a trend,
                                    not necessarily a duplicate
  same category             0.10
  description similarity    0.25  - catches re-sent emails and follow-ups
  recency bonus             0.10  - complaints about the same batch weeks apart
                                    are more likely genuinely separate events
"""
from __future__ import annotations

from datetime import datetime, timedelta
from difflib import SequenceMatcher

from sqlalchemy import or_, select

from app.core.database import SessionLocal
from app.models import Complaint
from app.schemas import DuplicateCandidate

MATCH_THRESHOLD = 0.45
MAX_CANDIDATES = 5


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def _text_similarity(a: str | None, b: str | None) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a[:1500], b[:1500]).ratio()


def find_duplicates(record: dict, exclude_id: int | None = None) -> list[DuplicateCandidate]:
    """Return complaints that plausibly describe the same event as `record`."""
    batch = _norm(record.get("batch_number"))
    product = _norm(record.get("product_name"))

    if not batch and not product:
        return []

    with SessionLocal() as db:
        # Narrow the search in SQL, score in Python. On a large history this
        # would move into a Postgres trigram index or a pgvector search.
        stmt = select(Complaint)
        filters = []
        if batch:
            filters.append(Complaint.batch_number.ilike(f"%{record['batch_number']}%"))
        if product:
            filters.append(Complaint.product_name.ilike(f"%{record['product_name']}%"))
        stmt = stmt.where(or_(*filters)).order_by(Complaint.created_at.desc()).limit(50)

        rows = db.execute(stmt).scalars().all()

        candidates: list[DuplicateCandidate] = []
        for row in rows:
            if exclude_id and row.id == exclude_id:
                continue

            score = 0.0
            reasons: list[str] = []

            batch_match = batch and _norm(row.batch_number) == batch
            product_match = product and _norm(row.product_name) == product

            if batch_match and product_match:
                score += 0.55
                reasons.append(f"same product and batch ({row.batch_number})")
            elif batch_match:
                score += 0.40
                reasons.append(f"same batch ({row.batch_number})")
            elif product_match:
                score += 0.20
                reasons.append("same product")

            if record.get("complaint_category") and _norm(record["complaint_category"]) == _norm(row.complaint_category):
                score += 0.10
                reasons.append("same defect category")

            desc_sim = _text_similarity(record.get("complaint_description"), row.complaint_description)
            if desc_sim > 0.35:
                score += desc_sim * 0.25
                reasons.append(f"description {int(desc_sim * 100)}% similar")

            if row.created_at and row.created_at > datetime.utcnow() - timedelta(days=30):
                score += 0.10
                reasons.append("logged within the last 30 days")

            score = min(score, 1.0)
            if score >= MATCH_THRESHOLD:
                candidates.append(
                    DuplicateCandidate(
                        complaint_id=row.id,
                        complaint_number=row.complaint_number,
                        product_name=row.product_name,
                        batch_number=row.batch_number,
                        similarity=round(score, 2),
                        reason="Matched on " + ", ".join(reasons) + ".",
                    )
                )

        candidates.sort(key=lambda c: c.similarity, reverse=True)
        return candidates[:MAX_CANDIDATES]
