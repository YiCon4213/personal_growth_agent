import asyncio
from types import SimpleNamespace
from typing import Any

import dashscope
import pytest

from app.core.config import Settings
from app.services.embedding_service import DashScopeEmbeddingProvider, EmbeddingServiceError


def test_dashscope_embedding_batches_orders_and_marks_text_type(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_call(**kwargs: Any):
        calls.append(kwargs)
        rows = [
            {"text_index": index, "embedding": [float(len(value)), float(index), *([0.0] * 62)]}
            for index, value in enumerate(kwargs["input"])
        ]
        return SimpleNamespace(
            status_code=200,
            output={"embeddings": list(reversed(rows))},
        )

    monkeypatch.setattr(dashscope.TextEmbedding, "call", fake_call)
    provider = DashScopeEmbeddingProvider(
        Settings(
            dashscope_api_key="test-key",
            dashscope_base_url="https://dashscope.example.test/compatible-mode/v1",
            embedding_model="text-embedding-v3",
            embedding_model_version="v3-64-test",
            embedding_dimension=64,
            embedding_batch_size=2,
            embedding_max_retries=0,
        )
    )

    document_vectors = asyncio.run(provider.embed_documents(["a", "bb", "ccc"]))
    query_vectors = asyncio.run(provider.embed_queries(["query"]))

    assert [vector[:2] for vector in document_vectors] == [[1.0, 0.0], [2.0, 1.0], [3.0, 0.0]]
    assert all(len(vector) == 64 for vector in document_vectors)
    assert query_vectors[0][:2] == [5.0, 0.0]
    assert len(query_vectors[0]) == 64
    assert len(calls) == 3
    assert all(call["model"] == "text-embedding-v3" for call in calls)
    assert all(call["dimension"] == 64 for call in calls)
    assert all(call["output_type"] == "dense" for call in calls)
    assert [call["text_type"] for call in calls].count("document") == 2
    assert [call["text_type"] for call in calls].count("query") == 1
    assert dashscope.base_http_api_url == "https://dashscope.example.test/api/v1"


def test_dashscope_text_embedding_v3_rejects_legacy_1536_dimension() -> None:
    with pytest.raises(EmbeddingServiceError, match="EMBEDDING_DIMENSION"):
        DashScopeEmbeddingProvider(
            Settings(
                dashscope_api_key="test-key",
                embedding_model="text-embedding-v3",
                embedding_dimension=1536,
            )
        )
