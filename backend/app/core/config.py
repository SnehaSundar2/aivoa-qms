"""Application configuration.

Everything is driven by environment variables so the same image can run in dev
and in a validated environment without code changes (a GxP-friendly habit).
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "AIVOA QMS - Customer Complaint Management"
    api_prefix: str = "/api"
    debug: bool = True

    # --- Database -----------------------------------------------------------
    # Primary target is PostgreSQL. If the server is unreachable at startup we
    # fall back to a local SQLite file so the demo is runnable with zero setup;
    # the fallback is logged loudly and never happens silently.
    database_url: str = "postgresql+psycopg://qms:qms@localhost:5432/qms_complaints"
    sqlite_fallback_url: str = "sqlite:///./qms_complaints.db"
    allow_sqlite_fallback: bool = True

    # --- Groq / LLM ---------------------------------------------------------
    groq_api_key: str = ""

    # The assignment specifies `gemma2-9b-it` for extraction and mentions
    # `llama-3.3-70b-versatile` for the reasoning nodes. Both are gone from
    # Groq as of this build:
    #
    #   gemma2-9b-it           -> 400 model_decommissioned
    #                             "has been decommissioned and is no longer
    #                              supported" (console.groq.com/docs/deprecations)
    #   llama-3.3-70b-versatile-> 404 model_not_found
    #
    # The two-tier split they were chosen for still holds, so the defaults map
    # onto the closest currently-served equivalents: a small fast model for
    # extraction and triage, a large one for the judgement calls. Both are
    # overridable from .env, so pointing this back at the original names is a
    # one-line change if Groq ever restores them.
    groq_model: str = "openai/gpt-oss-20b"
    groq_reasoning_model: str = "openai/gpt-oss-120b"
    # Reads uploaded images - photographed complaint forms, and photographs
    # of the defect itself. Of the models this key can reach, only the Qwen
    # ones accept image content; the gpt-oss family rejects it outright.
    # Blank disables the vision path and images fall back to local OCR.
    groq_vision_model: str = "qwen/qwen3.8-27b"

    # The model names the brief asked for, kept so the startup check can say
    # explicitly why it is not using them.
    specified_models: tuple[str, str] = ("gemma2-9b-it", "llama-3.3-70b-versatile")
    llm_temperature: float = 0.1
    # Retries for transient Groq failures (json_validate_failed, 429, 5xx).
    llm_max_retries: int = 3
    llm_timeout_seconds: int = 60
    # Use an LLM call to rephrase the completeness questions. The
    # deterministic question bank already covers every mandatory field, so
    # this is off by default to conserve the daily token budget.
    llm_phrase_questions: bool = False

    # --- Uploads ------------------------------------------------------------
    upload_dir: str = "./uploads"
    max_upload_mb: int = 15

    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
