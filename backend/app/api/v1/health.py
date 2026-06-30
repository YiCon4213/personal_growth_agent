from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import DatabaseConfigurationError, create_database_engine

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health_check(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/ready")
def readiness_check(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    engine = None
    try:
        engine = create_database_engine(settings)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        raise HTTPException(status_code=503, detail="Database is not ready.") from exc
    finally:
        if engine is not None:
            engine.dispose()
    return {
        "status": "ready",
        "service": settings.app_name,
        "timestamp": datetime.now(UTC).isoformat(),
    }
