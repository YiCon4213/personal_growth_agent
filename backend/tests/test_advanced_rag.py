from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import get_session
from app.db.models import Base
from app.main import create_app
from app.services.embedding_service import FakeEmbeddingProvider
from app.services.llm_service import FakeLLMService
from app.services.rag_service import FitnessRagService


def make_service(*, llm: FakeLLMService | None = None):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    provider = FakeEmbeddingProvider(64)
    service = FitnessRagService(
        factory(),
        settings=Settings(
            database_url="sqlite+pysqlite:///:memory:",
            embedding_dimension=64,
        ),
        embedding_provider=provider,
        llm_service=llm,
    )
    return service, provider


def test_advanced_pipeline_exposes_dense_bm25_and_direct_rrf_ranking() -> None:
    service, _ = make_service()
    for index, detail in enumerate(("动作标准", "渐进加量", "充分恢复", "记录负荷"), start=1):
        service.import_text_document(
            user_id="default_user",
            title=f"力量资料 {index}",
            content=f"力量训练需要{detail}，并根据疲劳调整训练量。",
        )
    service.session.commit()

    result = service.search(
        user_id="default_user",
        query="力量训练如何安排",
        top_k=3,
    )

    assert len(result.sources) == 3
    assert result.trace is not None
    stages = result.trace["stages"]
    assert stages["dense_retrieve"]["ranking_count"] >= 1
    assert stages["sparse_retrieve"]["engine"] == "okapi_bm25"
    assert stages["rrf_fuse"]["candidate_count"] >= 3
    assert stages["select_context"]["ranking_strategy"] == "rrf"
    assert stages["select_context"]["selected_count"] == 3
    assert any(
        route["route"] == "bm25"
        for source in result.sources
        for route in source.metadata["retrieval_routes"]
    )
    assert all(source.metadata["rrf_score"] > 0 for source in result.sources)


def test_history_rewrite_and_hyde_are_observable() -> None:
    service, _ = make_service(llm=FakeLLMService())
    service.import_text_document(
        user_id="default_user",
        title="深蹲指南",
        content="深蹲训练应保持动作标准并逐步增加负荷。",
    )
    service.session.commit()

    result = service.search(
        user_id="default_user",
        query="这个怎么安排？",
        history=[{"role": "user", "content": "我想学习深蹲训练"}],
    )

    stages = result.trace["stages"]
    assert "深蹲训练" in stages["rewrite_query"]["query"]
    assert stages["generate_hyde"]["passages"]
    assert len(stages["dense_retrieve"]["queries"]) >= 2


def test_embedding_cache_reuses_matching_model_and_content_hash() -> None:
    service, provider = make_service()
    content = "重复导入的力量训练知识。"
    first = service.import_text_document(
        user_id="default_user", title="第一份", content=content
    )
    service.session.commit()
    call_count = len(provider.calls)

    second = service.import_text_document(
        user_id="default_user", title="第二份", content=content
    )
    service.session.commit()

    assert len(provider.calls) == call_count
    assert first.content_hash == second.content_hash
    assert second.metadata_json["embedding_cache_hits"] == 1


def test_browser_multipart_txt_upload_uses_injected_fake() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def override() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app = create_app(
        embedding_provider=FakeEmbeddingProvider(),
    )
    app.dependency_overrides[get_session] = override
    client = TestClient(app)

    response = client.post(
        "/api/v1/rag/documents/upload",
        data={"title": "上传资料"},
        files={"file": ("fitness.txt", "力量训练需要循序渐进。", "text/plain")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == "default_user"
    assert payload["source_type"] == "txt"
    assert payload["embedding_provider"] == "fake"
    assert payload["index_status"] == "ready"
