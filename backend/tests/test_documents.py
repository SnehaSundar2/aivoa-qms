"""Tests for document intake: PDF, email and image.

All offline. The email and image paths had never been exercised against real
inputs, and both turned out to be broken in ways that only show up with a
genuine MIME message or a real photograph.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.services.documents import UnsupportedDocument, extract_text

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def _sample(name: str) -> bytes:
    path = SAMPLES / name
    if not path.exists():
        pytest.skip(f"{name} not generated; run make_sample_*.py")
    return path.read_bytes()


# --- PDF -------------------------------------------------------------------
def test_a_digital_pdf_yields_its_text():
    text, kind = extract_text(_sample("complaint_email_particulate.pdf"), "c.pdf")

    assert kind == "PDF Document"
    assert "OND25B119" in text
    assert "Ondansetron" in text


def test_a_pdf_with_no_text_layer_is_refused_with_advice():
    """A scan has no text layer; say so instead of returning silence."""
    import sys

    sys.path.insert(0, str(SAMPLES.parent))
    from make_sample_pdfs import build_pdf

    blank = build_pdf("")  # valid PDF, nothing readable on it

    with pytest.raises(UnsupportedDocument, match="scan"):
        extract_text(blank, "scanned.pdf")


def test_a_corrupt_pdf_is_refused_rather_than_crashing():
    """Regression: a file pypdf cannot open at all became a 500."""
    with pytest.raises(UnsupportedDocument, match="corrupt or incomplete"):
        extract_text(b"%PDF-1.4\nthis is not really a pdf", "broken.pdf")


# --- Email -----------------------------------------------------------------
def test_a_plain_text_email_keeps_its_headers_and_body():
    text, kind = extract_text(_sample("complaint_plain.eml"), "c.eml")

    assert kind == "Email"
    assert "Subject:" in text
    assert "AMX240602" in text
    assert "12 capsules" in text


def test_an_html_only_email_is_flattened_to_text():
    """Regression: a single-part text/html message leaked raw tags.

    The original code only stripped HTML on multipart messages, so a
    single-part text/html email - which plenty of corporate clients send -
    arrived with <p> and <b> intact, and those went into the complaint
    description.
    """
    text, _ = extract_text(_sample("complaint_html_only.eml"), "c.eml")

    for tag in ("<p>", "<b>", "<html", "</p>", "style="):
        assert tag not in text, f"{tag} leaked into the extracted text"

    # ...and the content still survives the stripping.
    assert "OND25B119" in text
    assert "4 vials" in text
    assert "Ondansetron Injection USP 2 mg/mL" in text


def test_html_block_elements_become_line_breaks():
    """Without this every paragraph runs into the next one."""
    from app.services.documents import _html_to_text

    text = _html_to_text("<p>First para.</p><p>Second para.</p>")
    assert "First para." in text
    assert "Second para." in text
    assert "\n" in text, "paragraphs must not be concatenated"


def test_html_entities_are_decoded():
    from app.services.documents import _html_to_text

    assert "&amp;" not in _html_to_text("<p>QA &amp; QC</p>")
    assert "QA & QC" in _html_to_text("<p>QA &amp; QC</p>")


def test_script_and_style_contents_are_dropped():
    from app.services.documents import _html_to_text

    text = _html_to_text("<style>.x{color:red}</style><p>Real content</p>")
    assert "color:red" not in text
    assert "Real content" in text


def test_attachments_are_listed_so_the_operator_knows_what_arrived():
    text, _ = extract_text(_sample("complaint_with_attachment.eml"), "c.eml")

    assert "Attachments:" in text
    assert "AZD25E063_analytical_report.pdf" in text
    assert "AZD25E063" in text


# --- Image preprocessing ---------------------------------------------------
def _png(size=(800, 600), mode="RGB"):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new(mode, size, (200, 180, 150) if mode == "RGB" else (0, 0, 0, 0)).save(
        buffer, format="PNG"
    )
    return buffer.getvalue()


def test_a_large_photo_is_downscaled_before_it_is_sent():
    """Image tokens scale with area, and the daily budget is 200k."""
    from PIL import Image

    from app.services.vision import MAX_EDGE, _encode

    buffer = io.BytesIO()
    Image.new("RGB", (4032, 3024), (200, 180, 150)).save(buffer, format="JPEG")

    _mime, encoded = _encode(buffer.getvalue(), "phone.jpg")

    import base64

    result = Image.open(io.BytesIO(base64.b64decode(encoded)))
    assert max(result.size) == MAX_EDGE


def test_transparency_is_flattened_onto_white():
    """An alpha screenshot otherwise composites onto black and loses its text."""
    import base64

    from PIL import Image

    from app.services.vision import _encode

    _mime, encoded = _encode(_png(mode="RGBA"), "shot.png")
    result = Image.open(io.BytesIO(base64.b64decode(encoded)))

    assert result.mode == "RGB"
    assert result.getpixel((0, 0)) == (255, 255, 255)


def test_a_one_pixel_image_is_rejected():
    """The vision API rejects these too, but with a far less useful message."""
    from app.services.vision import _encode

    with pytest.raises(ValueError, match="too small"):
        _encode(_png(size=(1, 1)), "tiny.png")


def test_a_corrupt_image_is_rejected_clearly():
    from app.services.vision import _encode

    with pytest.raises(ValueError, match="not a readable image"):
        _encode(b"this is not an image", "junk.png")


# --- routing ---------------------------------------------------------------
def test_an_unsupported_extension_names_what_is_accepted():
    with pytest.raises(UnsupportedDocument, match="Accepted"):
        extract_text(b"x" * 50, "report.docx")


def test_images_without_any_reader_are_refused_not_silently_empty(monkeypatch):
    """No vision model and no Tesseract must refuse, never return blank text."""
    import app.services.vision as vision_module

    monkeypatch.setattr(vision_module.settings, "groq_vision_model", "")

    with pytest.raises(UnsupportedDocument):
        extract_text(_png(), "defect.png")
