import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import DatabaseConfigurationError, require_database_url
from app.db.init_db import create_all_tables
from app.db.models import Base
from app.models.schemas import MCPTransport, MessageRole, ProfileCategory
from app.services.data_store import DataStore


def make_store() -> DataStore:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return DataStore(
        session=session_factory(),
        settings=Settings(database_url="sqlite+pysqlite:///:memory:"),
    )


def test_missing_database_url_has_clear_error() -> None:
    with pytest.raises(DatabaseConfigurationError, match="DATABASE_URL is not configured"):
        require_database_url(Settings(database_url=None))


def test_create_all_tables_supports_non_postgres_engine() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    create_all_tables(engine)

    assert "threads" in Base.metadata.tables
    assert "rag_chunks" in Base.metadata.tables


def test_data_store_can_write_and_read_required_metadata_objects() -> None:
    store = make_store()

    thread = store.upsert_thread("thread_1", user_id="user_1", title="Planning")
    message = store.add_message(
        thread.id,
        MessageRole.USER,
        "I want a long-term learning plan.",
        user_id="user_1",
    )
    profile = store.create_profile_item(
        "user_1",
        ProfileCategory.LEARNING,
        "Prefers evening study sessions.",
        "User said evenings work best.",
        source_thread_id=thread.id,
    )
    skill = store.create_skill(
        "user_1",
        "Weekly learning review",
        "Summarize progress every Sunday.",
        applicable_scenarios=["learning planning"],
        source_thread_id=thread.id,
    )
    mcp_server = store.create_mcp_server(
        "user_1",
        "calendar",
        "https://mcp.example.com/sse",
        transport=MCPTransport.SSE,
    )
    rag_document = store.create_rag_document(
        "user_1",
        "Fitness notes",
        source_uri="file://fitness.md",
        source_type="markdown",
        chunk_count=0,
    )
    store.session.commit()

    assert store.get_thread("thread_1") is not None
    assert [item.id for item in store.list_messages("thread_1")] == [message.id]
    assert [item.id for item in store.list_profile_items("user_1")] == [profile.id]
    assert [item.id for item in store.list_skills("user_1")] == [skill.id]
    assert [item.id for item in store.list_mcp_servers("user_1")] == [mcp_server.id]
    assert [item.id for item in store.list_rag_documents("user_1")] == [rag_document.id]
    assert rag_document.embedding_dimension == 1536
