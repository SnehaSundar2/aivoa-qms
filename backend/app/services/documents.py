"""Turn an uploaded file into plain text for the agent.

Scope note: the assignment explicitly says production-grade OCR is not
required, so this module aims at "good enough to demonstrate the workflow".

  * PDF   - pypdf text layer. Native/digital PDFs work well; a scanned PDF has
            no text layer and returns a clear message rather than silence.
  * EML   - parsed with the stdlib email package, preferring text/plain and
            falling back to a crude tag-strip of the HTML part. Attachments are
            listed by name so the operator knows what came in.
  * Image - Tesseract via pytesseract IF it is installed; otherwise we return a
            explicit placeholder. We never pretend to have read an image.
  * TXT   - passthrough.
"""
from __future__ import annotations

import io
import logging
import re
from email import policy
from email.parser import BytesParser

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\n{3,}")


class UnsupportedDocument(ValueError):
    pass


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    return _WS_RE.sub("\n\n", text).strip()


def _from_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise UnsupportedDocument(f"pypdf is not installed: {exc}") from exc

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            pages.append(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001 - one bad page must not fail the file
            logger.warning("PDF page %s failed to extract: %s", index, exc)
            pages.append("")

    text = _clean("\n\n".join(pages))
    if len(text) < 30:
        raise UnsupportedDocument(
            "No text layer found in this PDF - it is most likely a scan. "
            "Paste the complaint text into the intake box instead, or upload a digital PDF."
        )
    return text


def _from_eml(data: bytes) -> str:
    message = BytesParser(policy=policy.default).parsebytes(data)

    header_lines = [
        f"From: {message.get('From', '')}",
        f"To: {message.get('To', '')}",
        f"Date: {message.get('Date', '')}",
        f"Subject: {message.get('Subject', '')}",
    ]

    body = ""
    if message.is_multipart():
        plain = message.get_body(preferencelist=("plain",))
        html = message.get_body(preferencelist=("html",))
        if plain is not None:
            body = plain.get_content()
        elif html is not None:
            body = _TAG_RE.sub(" ", html.get_content())
    else:
        body = message.get_content()

    attachments = [
        part.get_filename()
        for part in message.iter_attachments()
        if part.get_filename()
    ]
    if attachments:
        header_lines.append("Attachments: " + ", ".join(attachments))

    return _clean("\n".join(header_lines) + "\n\n" + (body or ""))


def _from_image(data: bytes, filename: str) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        raise UnsupportedDocument(
            f"'{filename}' is an image and no OCR engine is installed on this server. "
            "Install pytesseract + Tesseract, or type the complaint text into the intake box."
        ) from None

    try:
        text = _clean(pytesseract.image_to_string(Image.open(io.BytesIO(data))))
    except Exception as exc:  # noqa: BLE001
        raise UnsupportedDocument(f"OCR failed for '{filename}': {exc}") from exc

    if len(text) < 20:
        raise UnsupportedDocument(
            f"OCR of '{filename}' produced almost no text. If this is a photograph of a "
            "defect rather than a document, describe it in the intake box and attach the "
            "image to the complaint record."
        )
    return text


def extract_text(data: bytes, filename: str) -> tuple[str, str]:
    """Return `(text, source_type)` for an uploaded file."""
    name = (filename or "").lower()

    if name.endswith(".pdf"):
        return _from_pdf(data), "PDF Document"
    if name.endswith((".eml", ".msg")):
        return _from_eml(data), "Email"
    if name.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")):
        return _from_image(data, filename), "Image / Photograph"
    if name.endswith((".txt", ".md", ".text")):
        return _clean(data.decode("utf-8", errors="replace")), "Email"

    raise UnsupportedDocument(
        f"Unsupported file type: '{filename}'. Accepted: PDF, EML, TXT, PNG, JPG."
    )
