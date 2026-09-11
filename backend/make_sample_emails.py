"""Generate realistic .eml complaint emails for the upload demo.

Run:  python make_sample_emails.py

The .txt samples are plain text, which exercises none of what makes real email
awkward: MIME multipart, an HTML alternative with no plain-text part, quoted
headers, and attachments. These produce genuine RFC 5322 messages so the
intake path is tested against what actually arrives in a QA mailbox.
"""
from __future__ import annotations

from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

SAMPLES = Path(__file__).parent / "samples"


def _base(subject: str, sender: str, to: str = "complaints@aivoapharma.example") -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = to
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain="aivoapharma.example")
    return message


def plain_text_complaint() -> EmailMessage:
    """The easy case: a single text/plain body."""
    message = _base(
        "Complaint - discoloured capsules, Amoxicillin 500 mg batch AMX240602",
        "Rohit Sharma <quality@apollopharmacy.example>",
    )
    message.set_content(
        "Dear Quality Assurance team,\n\n"
        "We wish to raise a formal complaint regarding Amoxicillin Capsules "
        "500 mg, batch AMX240602, manufactured March 2026 with expiry February "
        "2028.\n\n"
        "On opening a sealed bottle from this batch, our pharmacist found 12 "
        "capsules with visible discolouration - a brownish tint compared with "
        "the usual off-white. The remaining capsules in the bottle appear "
        "normal. The induction seal was intact when opened.\n\n"
        "The affected capsules have been withdrawn from dispensing and are "
        "held at our premises. They can be returned for examination on "
        "request. We received 200 bottles of this batch on 14 August 2026.\n\n"
        "We request an investigation and a replacement supply.\n\n"
        "Regards,\n"
        "Rohit Sharma\n"
        "Chief Pharmacist, Apollo Pharmacy\n"
        "+91 44 2829 3456"
    )
    return message


def html_only_complaint() -> EmailMessage:
    """The awkward case: HTML body with no plain-text alternative.

    Plenty of corporate mail clients send this. Without the tag-stripping
    fallback the body would come through empty.
    """
    message = _base(
        "URGENT: Particulate matter in Ondansetron Injection batch OND25B119",
        "Thomas Bergstrom <pharmacy@lakesidemedical.example>",
    )
    message.set_content("")  # replaced below
    message.clear_content()
    message.set_content(
        """<html><body style="font-family:Arial,sans-serif">
        <p>Dear Quality Assurance,</p>
        <p>During pre-administration inspection this morning, our oncology
        nursing staff identified <b>small translucent fibre-like particles</b>
        floating in <b>4 vials</b> of <b>Ondansetron Injection USP 2 mg/mL</b>,
        2 mL single-dose vials, <b>batch OND25B119</b>, expiry May 2028.</p>
        <p>No product from this carton has been administered to any patient.
        All 25 vials have been quarantined in the pharmacy. The four affected
        vials are available for return.</p>
        <p>Given this is an injectable administered to oncology patients, we
        consider this extremely serious and request a response within 24
        hours.</p>
        <p>Regards,<br>Thomas Bergstrom, PharmD<br>
        Director of Pharmacy, Lakeside Regional Medical Center</p>
        </body></html>""",
        subtype="html",
    )
    return message


def multipart_with_attachment() -> EmailMessage:
    """Plain text plus HTML plus a PDF attachment, as most real mail arrives."""
    message = _base(
        "Out of specification result - Azithromycin Dihydrate batch AZD25E063",
        "Ling Chen <qc.incoming@sinopharm-formulations.example>",
    )
    message.set_content(
        "Dear Sir/Madam,\n\n"
        "We notify you of an out of specification result obtained during "
        "incoming quality control testing of Azithromycin Dihydrate USP, "
        "batch AZD25E063, received at our Suzhou facility on 21 August 2026.\n\n"
        "Total impurities: 2.34% w/w against a specification of NMT 2.0% w/w. "
        "The test was performed in duplicate by two analysts on separate days "
        "and both results exceeded the limit.\n\n"
        "The full consignment of 12 drums (300 kg) is quarantined pending your "
        "response. We have retained 200 g from drum 4 for joint investigation.\n\n"
        "The full analytical report is attached.\n\n"
        "Best regards,\n"
        "Ling Chen\n"
        "Manager, Incoming Quality Control\n"
        "Sinopharm Formulations (Suzhou) Co. Ltd"
    )
    message.add_alternative(
        "<html><body><p>Dear Sir/Madam,</p><p>We notify you of an "
        "<b>out of specification</b> result for Azithromycin Dihydrate USP, "
        "batch <b>AZD25E063</b>. Total impurities 2.34% w/w against NMT 2.0% "
        "w/w.</p><p>The full consignment of 12 drums is quarantined. Report "
        "attached.</p><p>Ling Chen, Incoming QC</p></body></html>",
        subtype="html",
    )

    attachment = SAMPLES / "complaint_email_api_oos.pdf"
    if attachment.exists():
        message.add_attachment(
            attachment.read_bytes(),
            maintype="application",
            subtype="pdf",
            filename="AZD25E063_analytical_report.pdf",
        )
    return message


def main() -> None:
    SAMPLES.mkdir(exist_ok=True)
    emails = {
        "complaint_plain.eml": plain_text_complaint(),
        "complaint_html_only.eml": html_only_complaint(),
        "complaint_with_attachment.eml": multipart_with_attachment(),
    }
    for name, message in emails.items():
        path = SAMPLES / name
        path.write_bytes(message.as_bytes())
        print(f"  {name}  ({path.stat().st_size:,} bytes)")

    print(f"\nWrote {len(emails)} .eml file(s) to {SAMPLES}")


if __name__ == "__main__":
    main()
