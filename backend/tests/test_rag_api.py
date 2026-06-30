from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.rag import get_session
from app.db.models import Base
from app.main import create_app
from app.services.embedding_service import FakeEmbeddingProvider


def make_session_override() -> tuple[sessionmaker[Session], object]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def override_get_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    return session_factory, override_get_session


def test_rag_api_imports_and_searches_document() -> None:
    _, override = make_session_override()
    app = create_app(embedding_provider=FakeEmbeddingProvider())
    app.dependency_overrides[get_session] = override
    client = TestClient(app)

    import_response = client.post(
        "/api/v1/rag/documents",
        json={
            "user_id": "default_user",
            "title": "减脂训练指南",
            "content": "减脂训练建议结合力量训练和有氧训练。动作标准优先。",
            "source_uri": "fitness.md",
            "source_type": "markdown",
        },
    )

    assert import_response.status_code == 200
    document = import_response.json()
    assert document["chunk_count"] == 1

    search_response = client.post(
        "/api/v1/rag/search",
        json={"user_id": "default_user", "query": "减脂力量训练", "top_k": 2, "min_relevance": 0},
    )

    assert search_response.status_code == 200
    payload = search_response.json()
    assert payload["no_match_reason"] is None
    assert payload["sources"][0]["document_id"] == document["id"]
    assert payload["sources"][0]["relevance_score"] is not None

    app.dependency_overrides.clear()


def test_rag_api_reports_empty_search_without_fake_sources() -> None:
    _, override = make_session_override()
    app = create_app(embedding_provider=FakeEmbeddingProvider())
    app.dependency_overrides[get_session] = override
    client = TestClient(app)

    response = client.post(
        "/api/v1/rag/search",
        json={"user_id": "default_user", "query": "深蹲", "top_k": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sources"] == []
    assert payload["no_match_reason"] == "No sufficiently relevant fitness knowledge evidence was found."

    app.dependency_overrides.clear()
