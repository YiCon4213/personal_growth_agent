from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2b
from pathlib import Path
import math
import re
from typing import Any

from sqlalchemy import bindparam, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import RagChunk, RagDocument
from app.models.schemas import RagSource


class RagDocumentError(ValueError):
    pass


class RagSearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChunkingConfig:
    max_chars: int = 900
    overlap_chars: int = 120


@dataclass(frozen=True)
class RagSearchResult:
    sources: list[RagSource]
    no_match_reason: str | None = None


class DeterministicEmbeddingProvider:
    """Small local embedding substitute for deterministic tests and dev mode.

    It is not a semantic embedding model. It gives stable vectors so the RAG pipeline can be
    tested without calling an external LLM provider. Production can swap this class later.
    """

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def embed(self, text_value: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = tokenize_for_embedding(text_value)
        if not tokens:
            return vector
        for token in tokens:
            digest = blake2b(token.encode("utf-8"), digest_size=8).digest()
            raw = int.from_bytes(digest, byteorder="big", signed=False)
            index = raw % self.dimension
            sign = 1.0 if raw & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(item * item for item in vector))
        if norm == 0:
            return vector
        return [item / norm for item in vector]


def tokenize_for_embedding(text_value: str) -> list[str]:
    lower = text_value.lower()
    word_tokens = re.findall(r"[a-z0-9]+", lower)
    cjk_tokens = re.findall(r"[\u4e00-\u9fff]", lower)
    return word_tokens + cjk_tokens


def cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    score = dot / (left_norm * right_norm)
    return max(0.0, min(1.0, (score + 1.0) / 2.0))


def infer_source_type(filename_or_uri: str | None) -> str | None:
    if not filename_or_uri:
        return None
    suffix = Path(filename_or_uri).suffix.lower().lstrip(".")
    if suffix in {"md", "markdown"}:
        return "markdown"
    if suffix == "txt":
        return "txt"
    if suffix == "pdf":
        return "pdf"
    return suffix or None


def extract_text_from_file(path: Path) -> str:
    source_type = infer_source_type(str(path))
    if source_type in {"markdown", "txt"}:
        return path.read_text(encoding="utf-8")
    if source_type == "pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - dependency is declared, branch is defensive.
            raise RagDocumentError("PDF import requires the pypdf dependency.") from exc
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(page for page in pages if page.strip())
    raise RagDocumentError("Only Markdown, TXT, and PDF documents are supported.")


def split_text_into_chunks(content: str, config: ChunkingConfig | None = None) -> list[str]:
    resolved = config or ChunkingConfig()
    normalized = re.sub(r"\r\n?", "\n", content).strip()
    if not normalized:
        return []

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", normalized) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > resolved.max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(split_long_paragraph(paragraph, resolved))
            continue
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= resolved.max_chars:
            current = candidate
        else:
            chunks.append(current.strip())
            overlap = current[-resolved.overlap_chars :] if resolved.overlap_chars > 0 else ""
            current = f"{overlap}\n\n{paragraph}".strip()
    if current:
        chunks.append(current.strip())
    return chunks


def split_long_paragraph(paragraph: str, config: ChunkingConfig) -> list[str]:
    chunks: list[str] = []
    step = max(1, config.max_chars - config.overlap_chars)
    for start in range(0, len(paragraph), step):
        chunk = paragraph[start : start + config.max_chars].strip()
        if chunk:
            chunks.append(chunk)
    return chunks


class FitnessRagService:
    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        embedding_provider: DeterministicEmbeddingProvider | None = None,
        chunking_config: ChunkingConfig | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.embedding_provider = embedding_provider or DeterministicEmbeddingProvider(
            self.settings.embedding_dimension
        )
        self.chunking_config = chunking_config or ChunkingConfig()

    def import_text_document(
        self,
        *,
        user_id: str,
        title: str,
        content: str,
        source_uri: str | None = None,
        source_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RagDocument:
        chunks = split_text_into_chunks(content, self.chunking_config)
        if not chunks:
            raise RagDocumentError("Document content is empty after parsing.")
        resolved_source_type = source_type or infer_source_type(source_uri) or "text"
        document = RagDocument(
            user_id=user_id,
            title=title,
            source_uri=source_uri,
            source_type=resolved_source_type,
            embedding_model=self.settings.embedding_model,
            embedding_dimension=self.settings.embedding_dimension,
            chunk_count=len(chunks),
            metadata_json={
                "chunking": {
                    "max_chars": self.chunking_config.max_chars,
                    "overlap_chars": self.chunking_config.overlap_chars,
                },
                **(metadata or {}),
            },
        )
        self.session.add(document)
        self.session.flush()
        for index, chunk_text in enumerate(chunks):
            self.session.add(
                RagChunk(
                    document_id=document.id,
                    chunk_index=index,
                    content=chunk_text,
                    embedding=self.embedding_provider.embed(chunk_text),
                    embedding_model=self.settings.embedding_model,
                    metadata_json={"source_type": resolved_source_type},
                )
            )
        self.session.flush()
        return document

    def import_file_document(
        self,
        *,
        user_id: str,
        file_path: str,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RagDocument:
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise RagDocumentError(f"Document file does not exist: {file_path}")
        content = extract_text_from_file(path)
        return self.import_text_document(
            user_id=user_id,
            title=title or path.stem,
            content=content,
            source_uri=str(path),
            source_type=infer_source_type(str(path)),
            metadata=metadata,
        )

    def search(
        self,
        *,
        user_id: str,
        query: str,
        document_ids: list[str] | None = None,
        top_k: int = 4,
        min_relevance: float = 0.05,
    ) -> RagSearchResult:
        query_embedding = self.embedding_provider.embed(query)
        if not any(query_embedding):
            return RagSearchResult(sources=[], no_match_reason="Query has no searchable content.")

        dialect_name = self.session.bind.dialect.name if self.session.bind is not None else ""
        if dialect_name == "postgresql":
            sources = self._search_postgres(
                user_id=user_id,
                query_embedding=query_embedding,
                document_ids=document_ids,
                top_k=top_k,
                min_relevance=min_relevance,
            )
        else:
            sources = self._search_in_python(
                user_id=user_id,
                query_embedding=query_embedding,
                document_ids=document_ids,
                top_k=top_k,
                min_relevance=min_relevance,
            )
        if not sources:
            return RagSearchResult(
                sources=[],
                no_match_reason="No matching fitness knowledge chunks were found.",
            )
        return RagSearchResult(sources=sources)

    def _search_postgres(
        self,
        *,
        user_id: str,
        query_embedding: list[float],
        document_ids: list[str] | None,
        top_k: int,
        min_relevance: float,
    ) -> list[RagSource]:
        vector_literal = "[" + ",".join(str(float(item)) for item in query_embedding) + "]"
        document_filter = ""
        params: dict[str, Any] = {
            "user_id": user_id,
            "embedding": vector_literal,
            "top_k": top_k,
            "min_relevance": min_relevance,
        }
        if document_ids:
            document_filter = "AND d.id IN :document_ids"
            params["document_ids"] = document_ids
        statement = text(
            f"""
            SELECT
              d.id AS document_id,
              d.title AS title,
              d.source_uri AS source_uri,
              c.id AS chunk_id,
              c.content AS excerpt,
              GREATEST(0, LEAST(1, 1 - (c.embedding <=> CAST(:embedding AS vector)))) AS relevance_score
            FROM rag_chunks c
            JOIN rag_documents d ON d.id = c.document_id
            WHERE d.user_id = :user_id
              {document_filter}
              AND c.embedding IS NOT NULL
              AND GREATEST(0, LEAST(1, 1 - (c.embedding <=> CAST(:embedding AS vector)))) >= :min_relevance
            ORDER BY c.embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
            """
        )
        if document_ids:
            statement = statement.bindparams(bindparam("document_ids", expanding=True))
        rows = self.session.execute(statement, params).mappings().all()
        return [
            RagSource(
                document_id=row["document_id"],
                chunk_id=row["chunk_id"],
                title=row["title"],
                source_uri=row["source_uri"],
                relevance_score=float(row["relevance_score"]),
                excerpt=row["excerpt"],
                metadata={"retrieval": "pgvector_cosine"},
            )
            for row in rows
        ]

    def _search_in_python(
        self,
        *,
        user_id: str,
        query_embedding: list[float],
        document_ids: list[str] | None,
        top_k: int,
        min_relevance: float,
    ) -> list[RagSource]:
        statement = (
            select(RagChunk, RagDocument)
            .join(RagDocument, RagDocument.id == RagChunk.document_id)
            .where(RagDocument.user_id == user_id)
        )
        if document_ids:
            statement = statement.where(RagDocument.id.in_(document_ids))
        ranked: list[tuple[float, RagChunk, RagDocument]] = []
        for chunk, document in self.session.execute(statement).all():
            score = cosine_similarity(query_embedding, chunk.embedding)
            if score >= min_relevance:
                ranked.append((score, chunk, document))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [
            RagSource(
                document_id=document.id,
                chunk_id=chunk.id,
                title=document.title,
                source_uri=document.source_uri,
                relevance_score=score,
                excerpt=chunk.content,
                metadata={"retrieval": "python_cosine"},
            )
            for score, chunk, document in ranked[:top_k]
        ]
