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
    # Primary extraction/classification model required by the assignment.
    groq_model: str = "gemma2-9b-it"
    # Larger model used for the reasoning-heavy nodes (risk, RCA, CAPA).
    groq_reasoning_model: str = "llama-3.3-70b-versatile"
    llm_temperature: float = 0.1
    llm_max_retries: int = 2
    llm_timeout_seconds: int = 60

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
