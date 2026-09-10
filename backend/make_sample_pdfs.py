"""Turn the sample .txt complaints into digital PDFs for the upload demo.

Run:  python make_sample_pdfs.py

Deliberately dependency-free: it emits a minimal but valid PDF 1.4 with a text
layer, using the standard Helvetica font. That is exactly what the intake path
needs - a PDF pypdf can extract text from - without pulling reportlab into the
project just to build demo fixtures.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

SAMPLES = Path(__file__).parent / "samples"

PAGE_W, PAGE_H = 595, 842      # A4 in points
MARGIN_X, MARGIN_TOP = 56, 790
LEADING = 14                   # line height
FONT_SIZE = 10
WRAP_COLS = 88
LINES_PER_PAGE = int((MARGIN_TOP - 56) / LEADING)


def _escape(line: str) -> str:
    """Escape the three characters that are special inside a PDF string."""
    return line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _wrap(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if not raw.strip():
            lines.append("")
            continue
        # Preserve the leading indentation of aligned key/value blocks.
        indent = len(raw) - len(raw.lstrip())
        wrapped = textwrap.wrap(raw.strip(), width=WRAP_COLS - indent) or [""]
        lines.extend(" " * indent + piece for piece in wrapped)
    return lines


def _content_stream(lines: list[str]) -> bytes:
    parts = [f"BT /F1 {FONT_SIZE} Tf {LEADING} TL {MARGIN_X} {MARGIN_TOP} Td"]
    for line in lines:
        parts.append(f"({_escape(line)}) Tj T*" if line else "T*")
    parts.append("ET")
    return "\n".join(parts).encode("latin-1", errors="replace")


def build_pdf(text: str) -> bytes:
    pages = [
        _wrap(text)[i : i + LINES_PER_PAGE]
        for i in range(0, max(len(_wrap(text)), 1), LINES_PER_PAGE)
    ] or [[""]]

    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)  # 1-based object number

    # Object numbering is fixed up front so /Kids and /Parent can reference it.
    catalog_no, pages_no, font_no = 1, 2, 3
    objects.extend([b"", b"", b""])  # placeholders for the three above

    page_nos: list[int] = []
    for page_lines in pages:
        stream = _content_stream(page_lines)
        content_no = add(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
        page_nos.append(
            add(
                f"<< /Type /Page /Parent {pages_no} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                f"/Resources << /Font << /F1 {font_no} 0 R >> >> "
                f"/Contents {content_no} 0 R >>".encode()
            )
        )

    objects[catalog_no - 1] = f"<< /Type /Catalog /Pages {pages_no} 0 R >>".encode()
    kids = " ".join(f"{n} 0 R" for n in page_nos)
    objects[pages_no - 1] = (
        f"<< /Type /Pages /Count {len(page_nos)} /Kids [{kids}] >>".encode()
    )
    objects[font_no - 1] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )

    # --- assemble with a correct xref table ---
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_no} 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()

    return bytes(out)


def main() -> None:
    sources = sorted(SAMPLES.glob("*.txt"))
    if not sources:
        print(f"No .txt samples found in {SAMPLES}")
        return

    for src in sources:
        pdf_path = src.with_suffix(".pdf")
        pdf_path.write_bytes(build_pdf(src.read_text(encoding="utf-8")))
        print(f"  {src.name}  ->  {pdf_path.name}  ({pdf_path.stat().st_size:,} bytes)")

    print(f"\nWrote {len(sources)} PDF(s) to {SAMPLES}")


if __name__ == "__main__":
    main()
