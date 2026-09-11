"""Generate a sample complaint image for the upload demo.

Run:  python make_sample_image.py

Produces a photographed-looking complaint form. Real demos are better served by
an actual photograph of a defect, but this gives the image path something to
read without needing a camera, and it exercises the transcription half of the
vision prompt.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SAMPLES = Path(__file__).parent / "samples"

WIDTH, HEIGHT = 1240, 1600
PAPER = (250, 249, 245)
INK = (28, 32, 40)
FAINT = (120, 126, 138)
RULE = (206, 210, 218)


def _font(size: int, bold: bool = False):
    """Use a real font if one is available; Pillow's default is tiny."""
    candidates = (
        ["arialbd.ttf", "Arialbd.ttf", "DejaVuSans-Bold.ttf"]
        if bold
        else ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"]
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def build() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)

    h1, h2, body, small = _font(38, True), _font(23, True), _font(22), _font(18)
    y = 70

    draw.text((70, y), "CUSTOMER COMPLAINT FORM", font=h1, fill=INK)
    y += 52
    draw.text((70, y), "Meridian Hospital Pharmacy  ·  Quality Department", font=small, fill=FAINT)
    y += 44
    draw.line([(70, y), (WIDTH - 70, y)], fill=RULE, width=3)
    y += 40

    def section(title: str) -> None:
        nonlocal y
        draw.text((70, y), title, font=h2, fill=INK)
        y += 36

    def field(label: str, value: str) -> None:
        nonlocal y
        draw.text((70, y), label, font=small, fill=FAINT)
        draw.text((430, y - 2), value, font=body, fill=INK)
        y += 40

    section("1. Complainant")
    field("Organisation", "Meridian Hospital Pharmacy")
    field("Contact", "Dr. Anita Rao, Chief Pharmacist")
    field("Telephone", "+91 22 4455 8890")
    field("Date raised", "09 September 2026")
    y += 18

    section("2. Product")
    field("Product name", "Metformin Hydrochloride Tablets IP")
    field("Strength", "500 mg")
    field("Batch / Lot No.", "MTF25K713")
    field("Manufacturing date", "January 2026")
    field("Expiry date", "December 2027")
    field("Pack size", "10 x 15 tablets")
    field("Quantity affected", "23 tablets")
    y += 18

    section("3. Nature of complaint")
    for line in [
        "On dispensing from a sealed carton, staff observed that 23 tablets",
        "across three blister strips were cracked and partially crumbled.",
        "Several tablets had separated into two halves within the blister",
        "pocket. The blister foil itself was intact with no visible puncture.",
        "The remaining strips in the carton appear unaffected.",
        "",
        "Affected tablets have been withdrawn from dispensing and are held",
        "for return. We request investigation and replacement stock.",
    ]:
        draw.text((70, y), line, font=body, fill=INK)
        y += 33

    y += 26
    draw.line([(70, y), (WIDTH - 70, y)], fill=RULE, width=2)
    y += 26
    draw.text((70, y), "Signed:  A. Rao", font=body, fill=INK)
    draw.text((WIDTH - 420, y), "Ref: MHP-CC-2026-0412", font=small, fill=FAINT)

    # A slight rotation so it reads as a photographed page rather than a render.
    return image.rotate(-0.6, resample=Image.BICUBIC, fillcolor=PAPER)


def main() -> None:
    SAMPLES.mkdir(exist_ok=True)
    path = SAMPLES / "complaint_form_photo.jpg"
    build().save(path, format="JPEG", quality=88)
    print(f"  {path.name}  ({path.stat().st_size:,} bytes)")
    print(f"\nWrote the sample image to {SAMPLES}")


if __name__ == "__main__":
    main()
