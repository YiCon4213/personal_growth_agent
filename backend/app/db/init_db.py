from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.models import Base


def enable_pgvector(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


def create_all_tables(engine: Engine) -> None:
    enable_pgvector(engine)
    Base.metadata.create_all(bind=engine)
