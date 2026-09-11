"""Read complaint images with a Groq vision model.

Two kinds of image arrive at a QA mailbox, and they need different handling:

* **A photographed or scanned document** - a complaint form, a printed email,
  a CoA. Here the job is transcription: get the text out verbatim so the
  normal extraction path can work on it.
* **A photograph of the defect itself** - discoloured capsules in a bottle,
  particles in a vial, a damaged carton. There is no text to transcribe. The
  job is to describe what is visible, precisely and without diagnosing.

The prompt covers both, because the operator will not tell us which they
uploaded.

Preferred over local OCR because it needs no system dependency - Tesseract is
a separate install, and a Tesseract transcription of a photographed defect
would be empty anyway.
"""
from __future__ import annotations

import base64
import io
import logging

from app.agent.llm import LLMUnavailable, breaker_state, record_usage
from app.core.config import settings

logger = logging.getLogger(__name__)

# Long edge in pixels. A phone photo is ~4000px, and image tokens scale with
# area - downscaling is the difference between a few hundred tokens and several
# thousand, which matters on a 200k/day budget. Defect detail survives this
# comfortably; so does printed text at document distance.
MAX_EDGE = 1400
JPEG_QUALITY = 82

VISION_PROMPT = """You are reading an image submitted to a pharmaceutical \
Quality Assurance team as part of a customer complaint.

If the image shows a DOCUMENT - a complaint form, a printed email, a letter, a \
certificate, a label - transcribe all legible text verbatim. Preserve batch \
numbers, dates, quantities and product names exactly as printed. Mark anything \
you cannot read confidently as [illegible] rather than guessing at it.

If the image shows a PRODUCT or a DEFECT - capsules, tablets, a vial, a \
blister, a bottle, a carton - describe precisely what is visible:
- the dosage form and its appearance
- the defect: what is wrong, where, and how many units show it
- any text legible on labels or packaging, transcribed exactly
- the container and closure, if visible

Rules:
- Report only what is visible. Do not infer a batch number, a product name or a \
quantity that is not shown.
- Do not diagnose the cause. "The capsules are brown at one end" is an \
observation; "the capsules show moisture damage" is a conclusion, and that is \
the investigator's job.
- If the image is too blurred or dark to read, say so plainly.

Reply as plain prose. No markdown, no headings."""


def _encode(data: bytes, filename: str) -> tuple[str, str]:
    """Validate, downscale and re-encode an image. Returns (mime, base64)."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise LLMUnavailable(f"Pillow is not installed: {exc}") from exc

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"'{filename}' is not a readable image: {exc}") from exc

    width, height = image.size
    if width < 2 or height < 2:
        raise ValueError(
            f"'{filename}' is {width}x{height} pixels - too small to contain a complaint."
        )

    # Flatten transparency onto white; a PNG screenshot with an alpha channel
    # otherwise composites against black and loses dark text.
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        backdrop = Image.new("RGB", image.size, (255, 255, 255))
        backdrop.paste(image, mask=image.split()[-1])
        image = backdrop
    elif image.mode != "RGB":
        image = image.convert("RGB")

    if max(width, height) > MAX_EDGE:
        scale = MAX_EDGE / max(width, height)
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        image = image.resize(new_size, Image.LANCZOS)
        logger.info("Downscaled %s from %sx%s to %sx%s", filename, width, height, *new_size)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return "image/jpeg", base64.b64encode(buffer.getvalue()).decode()


def read_image(data: bytes, filename: str) -> str:
    """Return what the vision model reads in the image.

    Raises `LLMUnavailable` when no vision model is configured or reachable, so
    the caller can fall back to local OCR or refuse.
    """
    if not settings.groq_api_key:
        raise LLMUnavailable("GROQ_API_KEY is not set")
    if not settings.groq_vision_model:
        raise LLMUnavailable("No vision model configured (GROQ_VISION_MODEL)")

    state = breaker_state()
    if state["open"]:
        raise LLMUnavailable(
            f"{state['reason']} - retrying in {state['seconds_remaining']}s"
        )

    mime, encoded = _encode(data, filename)

    try:
        from groq import Groq
    except ImportError as exc:  # pragma: no cover
        raise LLMUnavailable(f"groq SDK not installed: {exc}") from exc

    client = Groq(api_key=settings.groq_api_key, timeout=settings.llm_timeout_seconds)

    try:
        completion = client.chat.completions.create(
            model=settings.groq_vision_model,
            temperature=0,
            max_tokens=900,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VISION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{encoded}"},
                        },
                    ],
                }
            ],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vision call failed (%s): %s", settings.groq_vision_model, exc)
        raise LLMUnavailable(str(exc)) from exc

    usage = getattr(completion, "usage", None)
    if usage:
        record_usage(
            settings.groq_vision_model,
            getattr(usage, "prompt_tokens", 0),
            getattr(usage, "completion_tokens", 0),
        )

    text = (completion.choices[0].message.content or "").strip()
    if len(text) < 20:
        raise LLMUnavailable(
            f"The vision model returned almost nothing for '{filename}'."
        )

    logger.info("Vision read %s chars from %s", len(text), filename)
    return text


def vision_available() -> bool:
    return bool(settings.groq_api_key and settings.groq_vision_model)
