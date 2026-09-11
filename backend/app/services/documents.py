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
from html import unescape

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1>", re.I | re.S)
# Block-level elements become line breaks so paragraphs do not run together.
_BLOCK_RE = re.compile(
    r"</?(p|div|br|tr|li|h[1-6]|table|blockquote)\b[^>]*>", re.I
)
_WS_RE = re.compile(r"\n{3,}")


class UnsupportedDocument(ValueError):
    pass


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    return _WS_RE.sub("\n\n", text).strip()


def _from_pdf(data: bytes, filename: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise UnsupportedDocument(f"pypdf is not installed: {exc}") from exc

    # Opening can fail outright on a corrupt, truncated or encrypted file. The
    # per-page guard below does not cover that, so without this a damaged
    # upload became a 500 instead of a message the operator can act on.
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            # An empty password unlocks most "protected" PDFs; if it does not,
            # we genuinely cannot read it.
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001
                raise UnsupportedDocument(
                    f"'{filename}' is password-protected and cannot be read. "
                    "Remove the protection, or paste the complaint text instead."
                ) from exc
    except UnsupportedDocument:
        raise
    except Exception as exc:  # noqa: BLE001
        raise UnsupportedDocument(
            f"'{filename}' could not be opened as a PDF - it may be corrupt or "
            f"incomplete ({type(exc).__name__}). Try re-exporting it, or paste "
            "the complaint text instead."
        ) from exc

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
            f"No text layer found in '{filename}' - it is most likely a scan. "
            "Upload it as an image instead so the vision model can read it, or "
            "paste the complaint text into the chat."
        )
    return text


def _html_to_text(html: str) -> str:
    """Flatten an HTML email body into readable plain text.

    Not a general HTML renderer - just enough that a complaint written in a
    corporate mail client survives intact. Block elements become line breaks
    (otherwise every paragraph runs together), script and style contents are
    dropped, and entities are decoded so "&amp;" does not reach the record.
    """
    text = _SCRIPT_STYLE_RE.sub(" ", html)
    text = _BLOCK_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    text = unescape(text)
    # Collapse the runs of spaces that tag removal leaves behind, without
    # destroying the line breaks just introduced.
    text = "\n".join(" ".join(line.split()) for line in text.split("\n"))
    return text


def _part_to_text(part) -> str:
    """Decode one message part, converting HTML to text if that is what it is."""
    content = part.get_content()
    if not isinstance(content, str):
        return ""
    if part.get_content_type() == "text/html":
        return _html_to_text(content)
    return content


def _from_eml(data: bytes) -> str:
    message = BytesParser(policy=policy.default).parsebytes(data)

    header_lines = [
        f"From: {message.get('From', '')}",
        f"To: {message.get('To', '')}",
        f"Date: {message.get('Date', '')}",
        f"Subject: {message.get('Subject', '')}",
    ]

    # get_body walks multipart trees and returns the message itself when there
    # is only one part, so both shapes are handled the same way. The earlier
    # version special-cased multipart and let a single-part text/html message
    # through untouched, leaking <p> and <b> into the complaint description.
    body = ""
    preferred = message.get_body(preferencelist=("plain", "html"))
    if preferred is not None:
        body = _part_to_text(preferred)

    if not body.strip():
        # Nothing usable from the preferred part; take any text part there is.
        for part in message.walk():
            if part.get_content_maintype() == "text":
                body = _part_to_text(part)
                if body.strip():
                    break

    attachments = [
        part.get_filename()
        for part in message.iter_attachments()
        if part.get_filename()
    ]
    if attachments:
        header_lines.append("Attachments: " + ", ".join(attachments))

    return _clean("\n".join(header_lines) + "\n\n" + (body or ""))


def _from_image(data: bytes, filename: str) -> str:
    """Read an image, preferring the vision model over local OCR.

    Order matters. A photographed defect - discoloured capsules in a bottle -
    contains no text at all, so Tesseract returns nothing useful for the single
    most likely kind of complaint image. A vision model describes it. Tesseract
    stays as a fallback for sites that cannot or will not call out to a model.
    """
    from app.agent.llm import LLMUnavailable
    from app.services.vision import read_image, vision_available

    vision_error = None
    if vision_available():
        try:
            return _clean(read_image(data, filename))
        except LLMUnavailable as exc:
            vision_error = str(exc)
            logger.info("Vision unavailable for %s, trying local OCR: %s", filename, exc)
        except ValueError as exc:
            # A corrupt or absurdly small image will not read any better with
            # OCR, so report it directly.
            raise UnsupportedDocument(str(exc)) from exc

    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        if vision_error:
            raise UnsupportedDocument(
                f"Could not read '{filename}': the vision model is unavailable "
                f"({vision_error}) and no local OCR engine is installed. Describe "
                "the defect in the chat instead."
            ) from None
        raise UnsupportedDocument(
            f"'{filename}' is an image, but no image reader is configured. Set "
            "GROQ_VISION_MODEL, or install pytesseract + Tesseract for local OCR."
        ) from None

    try:
        text = _clean(pytesseract.image_to_string(Image.open(io.BytesIO(data))))
    except Exception as exc:  # noqa: BLE001
        raise UnsupportedDocument(f"OCR failed for '{filename}': {exc}") from exc

    if len(text) < 20:
        raise UnsupportedDocument(
            f"OCR of '{filename}' produced almost no text. If this is a photograph of a "
            "defect rather than a document, describe it in the chat instead - local OCR "
            "reads text, not pictures of tablets."
        )
    return text


def extract_text(data: bytes, filename: str) -> tuple[str, str]:
    """Return `(text, source_type)` for an uploaded file."""
    name = (filename or "").lower()

    if name.endswith(".pdf"):
        return _from_pdf(data, filename), "PDF Document"
    if name.endswith((".eml", ".msg")):
        return _from_eml(data), "Email"
    if name.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")):
        return _from_image(data, filename), "Image / Photograph"
    if name.endswith((".txt", ".md", ".text")):
        return _clean(data.decode("utf-8", errors="replace")), "Email"

    raise UnsupportedDocument(
        f"Unsupported file type: '{filename}'. Accepted: PDF, EML, TXT, PNG, JPG."
    )
