from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.models import Base, RagChunk
from app.services.rag_service import FitnessRagService, split_text_into_chunks


def make_service() -> FitnessRagService:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = session_factory()
    return FitnessRagService(
        session=session,
        settings=Settings(
            database_url="sqlite+pysqlite:///:memory:",
            embedding_dimension=64,
            embedding_model="local-test-embedding",
        ),
    )


def test_split_text_into_chunks_keeps_content() -> None:
    chunks = split_text_into_chunks("第一段讲力量训练。\n\n第二段讲有氧训练。")

    assert chunks
    assert "力量训练" in chunks[0]


def test_import_text_document_writes_chunks_and_embeddings() -> None:
    service = make_service()

    document = service.import_text_document(
        user_id="user_1",
        title="健身基础",
        content="力量训练要逐步加量。\n\n减脂训练可以结合力量和有氧。",
        source_uri="fitness.md",
        source_type="markdown",
    )
    service.session.commit()

    chunks = service.session.query(RagChunk).filter_by(document_id=document.id).all()
    assert document.chunk_count == 1
    assert len(chunks) == 1
    assert chunks[0].embedding
    assert document.embedding_model == "local-test-embedding"


def test_search_returns_sources_with_relevance() -> None:
    service = make_service()
    document = service.import_text_document(
        user_id="user_1",
        title="减脂训练指南",
        content="减脂训练建议每周进行力量训练，并结合适量有氧。动作标准优先于重量。",
        source_uri="fitness.md",
        source_type="markdown",
    )
    service.session.commit()

    result = service.search(user_id="user_1", query="减脂力量训练", top_k=2, min_relevance=0.0)

    assert result.no_match_reason is None
    assert len(result.sources) == 1
    assert result.sources[0].document_id == document.id
    assert result.sources[0].chunk_id
    assert result.sources[0].relevance_score is not None
    assert "减脂训练" in result.sources[0].excerpt


def test_search_no_match_does_not_fabricate_sources() -> None:
    service = make_service()

    result = service.search(user_id="user_1", query="减脂", top_k=2, min_relevance=0.0)

    assert result.sources == []
    assert result.no_match_reason == "No matching fitness knowledge chunks were found."
