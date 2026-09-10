"""Seed the database with a realistic complaint history.

Run:  python seed.py [--reset]

The history matters for the demo: duplicate detection has nothing to match
against on an empty database. CC-2026-0004 below is deliberately the same
product and batch as the sample complaint email in `samples/`, so uploading
that email triggers a duplicate hit.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

from app.core.database import SessionLocal, init_db
from app.models import AuditEntry, Complaint, RiskAssessment

TODAY = date.today()


def d(days_ago: int) -> date:
    return TODAY - timedelta(days=days_ago)


COMPLAINTS = [
    dict(
        complaint_number="CC-2026-0001",
        complainant_name="Dr. Anita Rao",
        complainant_organisation="Meridian Hospital Pharmacy",
        complainant_email="a.rao@meridianhospital.example",
        complainant_phone="+91 22 4455 8890",
        country="India",
        product_name="Metformin Hydrochloride Tablets IP 500 mg",
        product_code="FDF-MET-500",
        product_type="FDF",
        dosage_form="Tablet",
        strength="500 mg",
        pack_size="10 x 15 tablets",
        batch_number="MTF23A014",
        manufacturing_date=d(400),
        expiry_date=TODAY + timedelta(days=330),
        quantity_supplied="500 packs",
        quantity_complained="14 tablets",
        date_of_complaint=d(58),
        date_received=d(57),
        complaint_category="Product Quality Defect",
        complaint_subcategory="Chipped and capped tablets",
        complaint_description=(
            "Pharmacy staff observed chipped edges and partial capping on tablets in "
            "three blister strips from the same carton. Tablets remain intact enough "
            "to identify the debossing. No discolouration or odour reported."
        ),
        sample_available=True,
        sample_quantity="14 tablets returned",
        severity="Minor",
        risk_score=28,
        status="Closed",
        assigned_to="S. Kulkarni",
        department="Quality Assurance",
        due_date=d(28),
        regulatory_reportable=False,
        regulatory_rationale="Cosmetic defect with no impact on dose delivery; no FAR required.",
        source_type="Email",
        ai_assisted=True,
        ai_summary=(
            "Meridian Hospital Pharmacy reported chipped and capped tablets in "
            "Metformin HCl 500 mg batch MTF23A014, affecting 14 tablets. Classified "
            "Minor - cosmetic defect with no impact on dose delivery."
        ),
    ),
    dict(
        complaint_number="CC-2026-0002",
        complainant_name="Marcus Feld",
        complainant_organisation="NordPharm Distribution GmbH",
        complainant_email="m.feld@nordpharm.example",
        country="Germany",
        product_name="Amoxicillin Sodium Sterile Powder",
        product_code="API-AMX-STR",
        product_type="API",
        dosage_form="Sterile Powder",
        pack_size="5 kg HDPE drum",
        batch_number="AMX24F007",
        manufacturing_date=d(210),
        expiry_date=TODAY + timedelta(days=520),
        quantity_supplied="20 drums",
        quantity_complained="1 drum",
        date_of_complaint=d(41),
        date_received=d(41),
        complaint_category="Analytical / Out of Specification",
        complaint_subcategory="Water content above specification",
        complaint_description=(
            "Incoming QC at the customer site reported water content of 1.8% w/w against "
            "a specification of NMT 1.0% w/w on drum 7 of 20. Other drums from the same "
            "consignment were within specification. Customer has quarantined the drum."
        ),
        sample_available=True,
        sample_quantity="100 g retained",
        severity="Major",
        risk_score=66,
        status="CAPA Initiated",
        assigned_to="R. Menon",
        department="Quality Control",
        due_date=d(-4),
        regulatory_reportable=True,
        regulatory_rationale=(
            "OOS on a released API batch - assess for Field Alert Report and notify "
            "affected customers if confirmed."
        ),
        source_type="Email",
        ai_assisted=True,
    ),
    dict(
        complaint_number="CC-2026-0003",
        complainant_name="Priya Nair",
        complainant_organisation="CarePlus Retail Pharmacy Chain",
        complainant_email="quality@careplus.example",
        country="India",
        product_name="Paracetamol Oral Suspension 250 mg/5 mL",
        product_code="FDF-PCM-SUS",
        product_type="FDF",
        dosage_form="Oral Suspension",
        strength="250 mg/5 mL",
        pack_size="60 mL bottle",
        batch_number="PCM24H221",
        manufacturing_date=d(150),
        expiry_date=TODAY + timedelta(days=400),
        quantity_complained="3 bottles",
        date_of_complaint=d(22),
        date_received=d(22),
        complaint_category="Packaging Defect",
        complaint_subcategory="Induction seal not adhered",
        complaint_description=(
            "Three bottles received with the induction seal loose and not adhered to the "
            "bottle neck. Contents appeared normal with no leakage, but seal integrity "
            "cannot be assured. Bottles were within the outer shrink wrap."
        ),
        sample_available=True,
        sample_quantity="3 bottles returned",
        severity="Major",
        risk_score=58,
        status="Under Investigation",
        assigned_to="V. Desai",
        department="Quality Assurance",
        due_date=d(-7),
        regulatory_reportable=False,
        source_type="Customer Portal",
        ai_assisted=True,
    ),
    dict(
        # Same product + batch as samples/complaint_email_particulate.txt,
        # so the duplicate detector fires when that email is ingested.
        complaint_number="CC-2026-0004",
        complainant_name="Thomas Bergstrom",
        complainant_organisation="Lakeside Regional Medical Center",
        complainant_email="pharmacy@lakesidemedical.example",
        country="United States",
        product_name="Ondansetron Injection USP 2 mg/mL",
        product_code="FDF-OND-INJ",
        product_type="FDF",
        dosage_form="Injection",
        strength="2 mg/mL",
        pack_size="2 mL single-dose vial",
        batch_number="OND25B119",
        manufacturing_date=d(120),
        expiry_date=TODAY + timedelta(days=610),
        quantity_supplied="200 vials",
        quantity_complained="2 vials",
        date_of_complaint=d(9),
        date_received=d(9),
        complaint_category="Foreign Matter / Particulate",
        complaint_subcategory="Visible particulate in a parenteral",
        complaint_description=(
            "Nursing staff identified small floating particles in two vials during "
            "pre-administration inspection. Vials were withheld from use. Particles "
            "described as translucent and fibre-like, visible against a black background."
        ),
        sample_available=True,
        sample_quantity="2 vials held at the site",
        severity="Critical",
        risk_score=91,
        status="Under Investigation",
        assigned_to="L. Fernandes",
        department="Quality Assurance",
        due_date=d(-6),
        regulatory_reportable=True,
        regulatory_rationale=(
            "Visible particulate in an injectable product - FDA Field Alert Report under "
            "21 CFR 314.81(b)(1)(ii) within 3 working days and a health hazard evaluation."
        ),
        source_type="Phone Call",
        ai_assisted=False,
    ),
    dict(
        complaint_number="CC-2026-0005",
        complainant_name="Sofia Almeida",
        complainant_organisation="Iberia Pharma Logistics SA",
        complainant_email="s.almeida@iberiapharma.example",
        country="Spain",
        product_name="Insulin Glargine Injection 100 IU/mL",
        product_code="FDF-INS-GLA",
        product_type="FDF",
        dosage_form="Injection",
        strength="100 IU/mL",
        pack_size="3 mL pre-filled pen",
        batch_number="ING25C042",
        manufacturing_date=d(75),
        expiry_date=TODAY + timedelta(days=450),
        quantity_supplied="1,200 pens",
        quantity_complained="1 pallet (300 pens)",
        date_of_complaint=d(15),
        date_received=d(14),
        complaint_category="Shipping, Storage & Logistics",
        complaint_subcategory="Cold chain excursion in transit",
        complaint_description=(
            "Data logger on pallet 2 recorded 11.4 degrees C for 6 hours 20 minutes "
            "during a customs hold, against a 2-8 degrees C storage requirement. Pallet "
            "quarantined on arrival pending a stability impact assessment."
        ),
        sample_available=False,
        severity="Major",
        risk_score=71,
        status="Open",
        assigned_to="R. Menon",
        department="Quality Assurance",
        due_date=d(-1),
        regulatory_reportable=False,
        regulatory_rationale="Reportability depends on the stability impact assessment outcome.",
        source_type="Email",
        ai_assisted=True,
    ),
    dict(
        complaint_number="CC-2026-0006",
        complainant_name="Kevin Osei",
        complainant_organisation="Accra Central Pharmacy",
        complainant_email="k.osei@accracentral.example",
        country="Ghana",
        product_name="Metformin Hydrochloride Tablets IP 500 mg",
        product_code="FDF-MET-500",
        product_type="FDF",
        dosage_form="Tablet",
        strength="500 mg",
        pack_size="10 x 15 tablets",
        batch_number="MTF25D088",
        expiry_date=TODAY + timedelta(days=500),
        quantity_complained="1 carton",
        date_of_complaint=d(5),
        date_received=d(5),
        complaint_category="Labelling / Artwork Defect",
        complaint_subcategory="Expiry date illegible on the carton",
        complaint_description=(
            "The overprinted batch number and expiry date on one carton are smudged and "
            "cannot be read. The blister foil inside carries legible details that match "
            "the despatch documentation."
        ),
        sample_available=True,
        sample_quantity="1 carton returned",
        severity="Major",
        risk_score=52,
        status="Open",
        assigned_to="S. Kulkarni",
        department="Quality Assurance",
        due_date=d(-3),
        regulatory_reportable=False,
        source_type="Email",
        ai_assisted=True,
    ),
]


def seed(reset: bool = False) -> None:
    init_db()

    with SessionLocal() as db:
        if reset:
            db.query(AuditEntry).delete()
            db.query(RiskAssessment).delete()
            db.query(Complaint).delete()
            db.commit()
            print("Cleared existing records.")

        existing = {c.complaint_number for c in db.query(Complaint).all()}
        added = 0

        for payload in COMPLAINTS:
            if payload["complaint_number"] in existing:
                continue
            row = Complaint(**payload)
            db.add(row)
            db.flush()
            db.add(
                AuditEntry(
                    complaint_id=row.id,
                    action="CREATED",
                    actor="seed.script",
                    detail=f"Seeded historical complaint via {row.source_type}",
                )
            )
            added += 1

        db.commit()
        total = db.query(Complaint).count()

    print(f"Seeded {added} new complaint(s). Database now holds {total}.")
    if added:
        print(
            "\nTip: ingest samples/complaint_email_particulate.txt - it describes the "
            "same product and batch as CC-2026-0004, so the duplicate detector will fire."
        )


if __name__ == "__main__":
    seed(reset="--reset" in sys.argv)
