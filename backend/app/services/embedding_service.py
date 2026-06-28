from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Sequence
from http import HTTPStatus
from typing import Any, Protocol

import dashscope

from app.core.config import Settings, get_settings


class EmbeddingServiceError(RuntimeError):
    pass


def normalize_dashscope_sdk_base_url(value: str) -> str:
    normalized = value.rstrip("/")
    compatible_suffix = "/compatible-mode/v1"
    if normalized.endswith(compatible_suffix):
        return normalized[: -len(compatible_suffix)] + "/api/v1"
    return normalized


class EmbeddingProvider(Protocol):
    provider_name: str
    model: str
    version: str
    dimension: int

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]: ...


class DashScopeEmbeddingProvider:
    """Async wrapper around DashScope's synchronous text embedding SDK."""

    provider_name = "dashscope"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.dashscope_api_key:
            raise EmbeddingServiceError(
                "DashScope embedding is not configured. Set DASHSCOPE_API_KEY in backend/.env."
            )
        self.model = self.settings.embedding_model
        self.version = self.settings.embedding_model_version
        self.dimension = self.settings.embedding_dimension
        if self.model == "text-embedding-v3" and self.dimension not in {64, 128, 256, 512, 768, 1024}:
            raise EmbeddingServiceError(
                "text-embedding-v3 requires EMBEDDING_DIMENSION to be one of 64, 128, 256, 512, 768, or 1024."
            )
        self._semaphore = asyncio.Semaphore(self.settings.embedding_max_concurrency)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed_batched(texts, text_type="document")

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed_batched(texts, text_type="query")

    async def _embed_batched(
        self, texts: Sequence[str], *, text_type: str
    ) -> list[list[float]]:
        if not texts:
            return []
        batches = [
            list(texts[index : index + self.settings.embedding_batch_size])
            for index in range(0, len(texts), self.settings.embedding_batch_size)
        ]
        results = await asyncio.gather(
            *(self._request(batch, text_type=text_type) for batch in batches)
        )
        return [vector for batch in results for vector in batch]

    async def _request(self, texts: list[str], *, text_type: str) -> list[list[float]]:
        last_error: Exception | None = None
        async with self._semaphore:
            for attempt in range(self.settings.embedding_max_retries + 1):
                try:
                    vectors = await asyncio.wait_for(
                        asyncio.to_thread(self._call_sync, texts, text_type=text_type),
                        timeout=self.settings.embedding_timeout_seconds,
                    )
                    self._validate(vectors, len(texts))
                    return vectors
                except (TimeoutError, KeyError, TypeError, ValueError, EmbeddingServiceError) as exc:
                    last_error = exc
                    if attempt >= self.settings.embedding_max_retries:
                        break
                    await asyncio.sleep(min(0.25 * (2**attempt), 2.0))
        error_name = last_error.__class__.__name__ if last_error is not None else "UnknownError"
        raise EmbeddingServiceError(
            f"DashScope embedding request failed after retries: {error_name}"
        ) from last_error

    def _call_sync(self, texts: list[str], *, text_type: str) -> list[list[float]]:
        dashscope.base_http_api_url = normalize_dashscope_sdk_base_url(self.settings.dashscope_base_url)
        response = dashscope.TextEmbedding.call(
            api_key=self.settings.dashscope_api_key,
            model=self.model,
            input=texts,
            dimension=self.dimension,
            output_type="dense",
            text_type=text_type,
        )
        if response.status_code != HTTPStatus.OK:
            raise EmbeddingServiceError(
                f"DashScope embedding provider returned status {response.status_code}."
            )
        rows = sorted(
            response.output["embeddings"],
            key=lambda item: int(item.get("text_index", 0)),
        )
        return [[float(value) for value in row["embedding"]] for row in rows]

    def _validate(self, vectors: list[list[float]], expected_count: int) -> None:
        if len(vectors) != expected_count:
            raise EmbeddingServiceError(
                "DashScope returned an unexpected embedding vector count."
            )
        if any(len(vector) != self.dimension for vector in vectors):
            raise EmbeddingServiceError(
                f"DashScope embedding dimension mismatch; configured dimension is {self.dimension}."
            )


class FakeEmbeddingProvider:
    """Deterministic offline fake. It never calls DashScope or consumes quota."""

    provider_name = "fake"

    def __init__(self, dimension: int = 1024, model: str = "fake-semantic-v1") -> None:
        self.dimension = dimension
        self.model = model
        self.version = "1"
        self.calls: list[list[str]] = []
        self.call_types: list[str] = []

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        self.call_types.append("document")
        return [self._embed(text) for text in texts]

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        self.call_types.append("query")
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        normalized = "".join(text.lower().split())
        tokens = [normalized[index : index + 2] for index in range(max(1, len(normalized) - 1))]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            vector[index] += -1.0 if digest[4] & 1 else 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector
