from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings


class DatabaseConfigurationError(RuntimeError):
    """Raised when database access is requested without a usable DATABASE_URL."""


def require_database_url(settings: Settings | None = None) -> str:
    resolved = settings or get_settings()
    if not resolved.database_url:
        raise DatabaseConfigurationError(
            "DATABASE_URL is not configured. Set it in personal_growth_agent/backend/.env "
            "or use the local Postgres service in personal_growth_agent/infra/docker-compose.yml."
        )
    return resolved.database_url


def create_database_engine(settings: Settings | None = None) -> Engine:
    resolved = settings or get_settings()
    database_url = require_database_url(resolved)
    return create_engine(database_url, echo=resolved.database_echo, future=True)


def create_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    resolved_engine = engine or create_database_engine()
    return sessionmaker(bind=resolved_engine, expire_on_commit=False, autoflush=False, future=True)


SessionLocal = create_session_factory


def get_session() -> Generator[Session, None, None]:
    session_factory = create_session_factory()
    with session_factory() as session:
        yield session
