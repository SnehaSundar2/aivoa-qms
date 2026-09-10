"""Database engine / session wiring.

Tries PostgreSQL first and falls back to SQLite only when explicitly allowed,
so a reviewer can clone and run without provisioning a server.
"""
import logging
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def _build_engine() -> Engine:
    try:
        engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Connected to primary database: %s", engine.url.render_as_string())
        return engine
    except Exception as exc:  # noqa: BLE001 - we want any connection failure
        if not settings.allow_sqlite_fallback:
            raise
        logger.warning(
            "Primary database unavailable (%s). Falling back to SQLite at %s. "
            "This fallback is for local demo only - do not use in a validated environment.",
            exc.__class__.__name__,
            settings.sqlite_fallback_url,
        )
        return create_engine(
            settings.sqlite_fallback_url,
            connect_args={"check_same_thread": False},
            future=True,
        )


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables. A real QMS would use Alembic migrations under change control."""
    from app import models  # noqa: F401  (import registers the mappers)

    Base.metadata.create_all(bind=engine)
