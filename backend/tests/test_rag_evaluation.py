import json
import math
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.models import Base
from app.services.llm_service import FakeLLMService
from app.services.rag_service import FitnessRagService


CONCEPTS = (
    ("增肌", "肌肉增长"),
    ("恢复", "训练后恢复"),
    ("深蹲", "squat"),
    ("rpe", "主观用力程度"),
)


def concept_indexes(text: str) -> set[int]:
    lowered = text.lower()
    return {
        index
        for index, aliases in enumerate(CONCEPTS)
        if any(alias in lowered for alias in aliases)
    }


class EvaluationEmbeddingProvider:
    provider_name = "evaluation-fake"
    model = "evaluation-concepts-v1"
    version = "1"
    dimension = 5

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        indexes = concept_indexes(text)
        if indexes:
            for index in indexes:
                vector[index] = 1.0
        else:
            vector[-1] = 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector]


def test_deterministic_advanced_rag_evaluation_set() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    provider = EvaluationEmbeddingProvider()
    service = FitnessRagService(
        factory(),
        settings=Settings(
            database_url="sqlite+pysqlite:///:memory:",
            embedding_dimension=provider.dimension,
            rag_min_dense_score=0.1,
        ),
        embedding_provider=provider,
        llm_service=FakeLLMService(),
    )
    documents = {
        "增肌指南": "增肌训练需要渐进超负荷。",
        "恢复指南": "训练后恢复需要睡眠和合理安排负荷。",
        "深蹲指南": "深蹲需要保持动作标准。",
        "强度指南": "RPE 是主观用力程度量表。",
    }
    for title, content in documents.items():
        service.import_text_document(
            user_id="default_user", title=title, content=content
        )
    service.session.commit()

    cases = json.loads(
        (Path(__file__).parent / "fixtures" / "rag_evaluation_cases.json").read_text(
            encoding="utf-8"
        )
    )
    assert {case["name"] for case in cases} == {
        "semantic_match",
        "exact_keyword",
        "multi_part",
        "conversational",
        "no_answer",
    }

    for case in cases:
        result = service.search(
            user_id="default_user",
            query=case["query"],
            history=case.get("history", []),
        )
        titles = {source.title for source in result.sources}
        assert set(case["expected_titles"]).issubset(titles), case["name"]
        if not case["expected_titles"]:
            assert result.no_match_reason is not None
