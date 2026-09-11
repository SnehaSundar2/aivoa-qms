"""AI Copilot endpoints - the entry points into the LangGraph agent."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.agent.graph import render_mermaid
from app.agent.llm import check_models, llm_available
from app.core.config import settings
from app.schemas import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    CopilotResult,
    IntakeTextRequest,
    ReassessRequest,
)
from app.services.chat import greeting, handle_turn
from app.services.copilot import run_copilot
from app.services.documents import UnsupportedDocument, extract_text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["ai-copilot"])


@router.get("/health")
def ai_health() -> dict:
    """Lets the UI tell the operator up front whether the model is live.

    Reports model availability, not just whether a key is present: a key that
    points at a decommissioned model looks configured but produces rule-based
    output on every request.
    """
    if not llm_available():
        return {
            "llm_configured": False,
            "extraction_model": settings.groq_model,
            "reasoning_model": settings.groq_reasoning_model,
            "mode": "rule-based fallback",
            "models_available": False,
            "message": (
                "GROQ_API_KEY is not set - the copilot will run deterministic rules "
                "and every result will be labelled as rule-based."
            ),
        }

    status = check_models()

    if status["missing"]:
        message = (
            f"Configured model(s) not available on Groq: {', '.join(status['missing'])}. "
            "Every request will fall back to rules. "
            f"This key can use: {', '.join(status['available'][:8])}."
        )
        mode = "rule-based fallback (model unavailable)"
    elif not status["checked"]:
        message = f"Groq key set; could not verify models ({status['error']})."
        mode = "llm (unverified)"
    else:
        message = "Groq connected."
        mode = "llm"

    return {
        "llm_configured": True,
        "extraction_model": settings.groq_model,
        "reasoning_model": settings.groq_reasoning_model,
        "mode": mode,
        "models_available": status["ok"],
        "missing_models": status["missing"],
        "specified_by_brief": list(settings.specified_models),
        "message": message,
    }


@router.get("/graph")
def graph_definition() -> dict:
    """The compiled LangGraph topology, rendered as Mermaid for the UI."""
    return {"mermaid": render_mermaid()}


@router.post("/intake/text", response_model=CopilotResult)
def intake_text(payload: IntakeTextRequest) -> CopilotResult:
    """Run the agent over pasted text - an email body, a phone note, a prompt."""
    return run_copilot(
        raw_text=payload.text,
        source_type=payload.source_type,
        source_reference=payload.source_reference,
    )


@router.post("/intake/file", response_model=CopilotResult)
async def intake_file(
    file: UploadFile = File(...),
    source_type: str | None = Form(None),
) -> CopilotResult:
    """Run the agent over an uploaded PDF, .eml, image or text file."""
    data = await file.read()

    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(413, f"File exceeds the {settings.max_upload_mb} MB limit")
    if not data:
        raise HTTPException(400, "Uploaded file is empty")

    try:
        text, detected_type = extract_text(data, file.filename or "upload")
    except UnsupportedDocument as exc:
        # 422 rather than 500: the request was well-formed, the content was not
        # usable, and the message is written to be shown directly to the user.
        raise HTTPException(422, str(exc)) from exc

    logger.info("Extracted %s chars from %s (%s)", len(text), file.filename, detected_type)
    return run_copilot(
        raw_text=text,
        source_type=source_type or detected_type,
        source_reference=file.filename,
    )


@router.post("/reassess", response_model=CopilotResult)
def reassess(payload: ReassessRequest) -> CopilotResult:
    """Re-run the copilot against the form as the operator has edited it.

    This is the "the AI got it wrong, I fixed the batch number, try again"
    path. Whatever the operator typed is passed as `existing` and the agent is
    forbidden from overwriting it.
    """
    record = payload.complaint.model_dump(exclude_none=True)

    narrative_parts = [
        f"Product: {record.get('product_name', 'not stated')}",
        f"Batch: {record.get('batch_number', 'not stated')}",
        f"Category: {record.get('complaint_category', 'not stated')}",
        f"Complainant: {record.get('complainant_organisation', 'not stated')}",
        f"Quantity affected: {record.get('quantity_complained', 'not stated')}",
        "",
        record.get("complaint_description") or "",
    ]
    narrative = "\n".join(narrative_parts).strip()

    if len(narrative) < 40:
        raise HTTPException(
            400,
            "Not enough information to assess. Enter at least a product and a "
            "description of the defect.",
        )

    source_text = record.get("source_text") or narrative
    return run_copilot(
        raw_text=source_text if len(source_text) > len(narrative) else narrative,
        source_type=record.get("source_type") or "Manual Entry",
        source_reference=record.get("source_reference"),
        existing=record,
    )


# --------------------------------------------------------------------------
# Conversational copilot
# --------------------------------------------------------------------------
@router.get("/chat/greeting")
def chat_greeting() -> dict:
    """The copilot's opening message."""
    return {"reply": greeting()}


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    """One turn of conversation.

    The agent decides whether to call the `log_complaint` tool. When it does,
    `form_update` carries the fields to apply to the Log Customer Complaint
    form and `copilot` carries the full assessment.
    """
    return handle_turn(payload.message, payload.history, payload.form)


@router.post("/chat/upload", response_model=ChatResponse)
async def chat_upload(
    file: UploadFile = File(...),
    form: str = Form("{}"),
    history: str = Form("[]"),
) -> ChatResponse:
    """Same conversation, but the turn's content comes from an uploaded file.

    `form` and `history` arrive as JSON strings because this is multipart -
    a file upload cannot also carry a JSON body.
    """
    data = await file.read()

    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(413, f"File exceeds the {settings.max_upload_mb} MB limit")
    if not data:
        raise HTTPException(400, "Uploaded file is empty")

    try:
        text, detected_type = extract_text(data, file.filename or "upload")
    except UnsupportedDocument as exc:
        raise HTTPException(422, str(exc)) from exc

    try:
        form_state = json.loads(form) or {}
        past = [ChatMessage(**m) for m in (json.loads(history) or [])]
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise HTTPException(400, f"Malformed form or history payload: {exc}") from exc

    form_state.setdefault("source_type", detected_type)
    form_state.setdefault("source_reference", file.filename)

    logger.info("Chat upload: %s chars from %s (%s)", len(text), file.filename, detected_type)
    response = handle_turn(text, past, form_state)

    # Record where this came from, so the saved complaint keeps its provenance.
    if response.form_update:
        response.form_update.setdefault("source_type", detected_type)
        response.form_update.setdefault("source_reference", file.filename)
    return response
