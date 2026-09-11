"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.graph import get_graph
from app.agent.llm import check_models, llm_available
from app.core.config import settings
from app.core.database import engine, init_db
from app.routers import ai, complaints

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    logger.info("Database ready: %s", engine.url.render_as_string(hide_password=True))

    # Compile the agent graph now rather than on the first request. A wiring
    # error is a programming bug, and it must stop the process at boot instead
    # of quietly turning every intake into a degraded run.
    get_graph()
    if llm_available():
        logger.info(
            "Groq configured | extraction=%s | reasoning=%s",
            settings.groq_model, settings.groq_reasoning_model,
        )
        # Confirm the models are actually served. A decommissioned model would
        # otherwise turn every request into a silent rule-based fallback.
        status = check_models()
        if status["ok"]:
            logger.info("Groq models verified as available")
        elif status["missing"]:
            logger.error(
                "CONFIGURED MODEL NOT AVAILABLE: %s. The copilot will fall back to "
                "rules on every request. Models this key can use: %s",
                ", ".join(status["missing"]),
                ", ".join(status["available"]) or "none",
            )
        else:
            logger.warning(
                "Could not verify Groq models (%s). Continuing; failures will "
                "surface per request.",
                status["error"],
            )
    else:
        logger.warning(
            "GROQ_API_KEY not set - the copilot will run in rule-based fallback mode. "
            "Set it in backend/.env to enable the LLM path."
        )
    yield
    logger.info("Shutting down")


app = FastAPI(
    title=settings.app_name,
    description=(
        "AI-assisted Customer Complaint intake and triage for pharmaceutical "
        "(API and FDF) manufacturing. LangGraph agent over Groq."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(complaints.router, prefix=settings.api_prefix)
app.include_router(ai.router, prefix=settings.api_prefix)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {
        "status": "ok",
        "database": engine.dialect.name,
        "llm_configured": llm_available(),
    }
