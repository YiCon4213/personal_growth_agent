from __future__ import annotations

import asyncio
import hashlib
import math
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from pypdf import PdfReader
from sqlalchemy import bindparam, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import RagChunk, RagDocument
from app.models.schemas import RagSource
from app.services.embedding_service import DashScopeEmbeddingProvider, EmbeddingProvider
from app.services.llm_service import LLMService

DEFAULT_USER_ID = "default_user"


class RagDocumentError(ValueError):
    pass


class RagSearchError(ValueError):
    pass


@dataclass(frozen=True)
class ChunkingConfig:
    max_chars: int = 900
    overlap_chars: int = 120


@dataclass
class RagSearchResult:
    sources: list[RagSource]
    no_match_reason: str | None = None
    trace: dict[str, Any] | None = None


class RagQueryPlan(BaseModel):
    retrieval_required: bool = True
    standalone_query: str
    constraints: list[str] = Field(default_factory=list)
    subqueries: list[str] = Field(default_factory=list, max_length=4)
    hyde_passages: list[str] = Field(default_factory=list, max_length=2)


class RagPipelineState(TypedDict, total=False):
    user_id: str
    query: str
    history: list[dict[str, str]]
    document_ids: list[str]
    plan: RagQueryPlan
    rewritten_query: str
    subqueries: list[str]
    hyde_passages: list[str]
    rankings: list[dict[str, Any]]
    candidates: dict[str, dict[str, Any]]
    fused: list[dict[str, Any]]
    selected: list[RagSource]
    no_match_reason: str | None
    trace: dict[str, Any]


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def split_text_into_chunks(text_value: str, config: ChunkingConfig | None = None) -> list[str]:
    config = config or ChunkingConfig()
    normalized = text_value.replace("\r\n", "\n").strip()
    if not normalized:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", normalized) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > config.max_chars:
            if current:
                chunks.append(current)
                current = ""
            step = max(1, config.max_chars - config.overlap_chars)
            chunks.extend(paragraph[i : i + config.max_chars] for i in range(0, len(paragraph), step))
        elif not current:
            current = paragraph
        elif len(current) + len(paragraph) + 2 <= config.max_chars:
            current += "\n\n" + paragraph
        else:
            chunks.append(current)
            overlap = current[-config.overlap_chars :] if config.overlap_chars else ""
            current = (overlap + "\n\n" + paragraph).strip()
    if current:
        chunks.append(current)
    return chunks


def infer_source_type(source_uri: str | None) -> str | None:
    if not source_uri:
        return None
    suffix = Path(source_uri).suffix.lower()
    return {".md": "markdown", ".markdown": "markdown", ".txt": "txt", ".pdf": "pdf"}.get(suffix)


def extract_text_from_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown", ".txt"}:
        return path.read_text(encoding="utf-8")
    if suffix == ".pdf":
        return "\n\n".join((page.extract_text() or "").strip() for page in PdfReader(str(path)).pages).strip()
    raise RagDocumentError("Only Markdown, TXT, and text-based PDF files are supported.")


def cosine_similarity(left: list[float], right: list[float] | None) -> float:
    if not right or len(left) != len(right):
        return 0.0
    denominator = math.sqrt(sum(v * v for v in left)) * math.sqrt(sum(v * v for v in right))
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator if denominator else 0.0


def tokenize(text_value: str) -> list[str]:
    lowered = text_value.lower()
    words = re.findall(r"[a-z0-9]+", lowered)
    cjk = "".join(re.findall(r"[\u3400-\u9fff]", lowered))
    return words + [cjk[i : i + 2] for i in range(max(0, len(cjk) - 1))]


class BM25SparseRetriever:
    """Replaceable in-process Okapi BM25 over the user-scoped database corpus."""

    def rank(self, query: str, rows: list[tuple[RagChunk, RagDocument]], limit: int) -> list[tuple[float, RagChunk, RagDocument]]:
        tokenized = [tokenize(chunk.content) for chunk, _ in rows]
        query_tokens = tokenize(query)
        if not rows or not query_tokens:
            return []
        document_frequency = Counter(token for tokens in tokenized for token in set(tokens))
        average_length = sum(map(len, tokenized)) / len(tokenized) or 1
        ranked = []
        for (chunk, document), tokens in zip(rows, tokenized, strict=True):
            frequencies = Counter(tokens)
            score = 0.0
            for token in query_tokens:
                frequency = frequencies[token]
                if not frequency:
                    continue
                idf = math.log(1 + (len(rows) - document_frequency[token] + 0.5) / (document_frequency[token] + 0.5))
                denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * len(tokens) / average_length)
                score += idf * frequency * 2.5 / denominator
            if score > 0:
                ranked.append((score, chunk, document))
        return sorted(ranked, key=lambda item: item[0], reverse=True)[:limit]


class FitnessRagService:
    def __init__(self, session: Session, settings: Settings | None = None, *, embedding_provider: EmbeddingProvider | None = None, llm_service: LLMService | None = None, sparse_retriever: BM25SparseRetriever | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.embedding_provider = embedding_provider or DashScopeEmbeddingProvider(self.settings)
        self.llm_service = llm_service
        self.sparse_retriever = sparse_retriever or BM25SparseRetriever()
        self.chunking_config = ChunkingConfig()
        if (
            self.embedding_provider.provider_name == "dashscope"
            and self.embedding_provider.dimension != self.settings.embedding_dimension
        ):
            raise RagDocumentError("DashScope embedding dimension does not match EMBEDDING_DIMENSION.")

    async def _embed_chunks_with_cache(self, chunks: list[str]) -> tuple[list[list[float]], int]:
        hashes = [content_hash(chunk) for chunk in chunks]
        cached_rows = self.session.scalars(
            select(RagChunk).where(
                RagChunk.content_hash.in_(set(hashes)),
                RagChunk.embedding_provider == self.embedding_provider.provider_name,
                RagChunk.embedding_model == self.embedding_provider.model,
                RagChunk.embedding_version == self.embedding_provider.version,
                RagChunk.embedding_dimension == self.embedding_provider.dimension,
                RagChunk.embedding.is_not(None),
            )
        ).all()
        cache = {chunk.content_hash: chunk.embedding for chunk in cached_rows if chunk.embedding}
        missing_by_hash: dict[str, str] = {}
        for digest, chunk in zip(hashes, chunks, strict=True):
            if digest not in cache:
                missing_by_hash.setdefault(digest, chunk)
        if missing_by_hash:
            missing_hashes = list(missing_by_hash)
            embedded = await self.embedding_provider.embed_documents(
                [missing_by_hash[digest] for digest in missing_hashes]
            )
            cache.update(dict(zip(missing_hashes, embedded, strict=True)))
        return [cache[digest] for digest in hashes], len(hashes) - len(missing_by_hash)

    async def import_text_document_async(self, *, user_id: str, title: str, content: str, source_uri: str | None = None, source_type: str | None = None, metadata: dict[str, Any] | None = None) -> RagDocument:
        chunks = split_text_into_chunks(content, self.chunking_config)
        if not chunks:
            raise RagDocumentError("Document content is empty after parsing.")
        vectors, cache_hits = await self._embed_chunks_with_cache(chunks)
        if any(len(vector) != self.embedding_provider.dimension for vector in vectors):
            raise RagDocumentError("Embedding dimension does not match the active pgvector schema.")
        document = RagDocument(
            user_id=user_id, title=title, source_uri=source_uri,
            source_type=source_type or infer_source_type(source_uri) or "text",
            embedding_provider=self.embedding_provider.provider_name,
            embedding_model=self.embedding_provider.model,
            embedding_version=self.embedding_provider.version,
            embedding_dimension=self.embedding_provider.dimension,
            content_hash=content_hash(content), index_status="ready", chunk_count=len(chunks),
            metadata_json={"chunking": {"max_chars": self.chunking_config.max_chars, "overlap_chars": self.chunking_config.overlap_chars}, "embedding_cache_hits": cache_hits, **(metadata or {})},
        )
        self.session.add(document)
        self.session.flush()
        for index, (chunk_text, vector) in enumerate(zip(chunks, vectors, strict=True)):
            self.session.add(RagChunk(
                document_id=document.id, chunk_index=index, content=chunk_text, embedding=vector,
                embedding_provider=self.embedding_provider.provider_name,
                embedding_model=self.embedding_provider.model,
                embedding_version=self.embedding_provider.version,
                embedding_dimension=self.embedding_provider.dimension,
                content_hash=content_hash(chunk_text), metadata_json={"source_type": document.source_type},
            ))
        self.session.flush()
        return document

    def import_text_document(self, **kwargs: Any) -> RagDocument:
        return asyncio.run(self.import_text_document_async(**kwargs))

    async def import_file_document_async(self, *, user_id: str, file_path: str, title: str | None = None, metadata: dict[str, Any] | None = None) -> RagDocument:
        path = Path(file_path)
        if not path.is_file():
            raise RagDocumentError(f"Document file does not exist: {file_path}")
        return await self.import_text_document_async(user_id=user_id, title=title or path.stem, content=extract_text_from_file(path), source_uri=str(path), source_type=infer_source_type(str(path)), metadata=metadata)

    def import_file_document(self, **kwargs: Any) -> RagDocument:
        return asyncio.run(self.import_file_document_async(**kwargs))

    async def rebuild_index(self, *, user_id: str) -> int:
        documents = self.session.scalars(select(RagDocument).where(RagDocument.user_id == user_id)).all()
        rebuilt = 0
        for document in documents:
            chunks = self.session.scalars(select(RagChunk).where(RagChunk.document_id == document.id).order_by(RagChunk.chunk_index)).all()
            if not chunks:
                continue
            vectors, _ = await self._embed_chunks_with_cache([chunk.content for chunk in chunks])
            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk.embedding = vector
                chunk.embedding_provider = self.embedding_provider.provider_name
                chunk.embedding_model = self.embedding_provider.model
                chunk.embedding_version = self.embedding_provider.version
                chunk.embedding_dimension = self.embedding_provider.dimension
                chunk.content_hash = content_hash(chunk.content)
            document.embedding_provider = self.embedding_provider.provider_name
            document.embedding_model = self.embedding_provider.model
            document.embedding_version = self.embedding_provider.version
            document.embedding_dimension = self.embedding_provider.dimension
            document.content_hash = content_hash("\n\n".join(chunk.content for chunk in chunks))
            document.index_status = "ready"
            rebuilt += 1
        self.session.flush()
        return rebuilt

    async def search_async(self, *, user_id: str, query: str, history: list[dict[str, str]] | None = None, document_ids: list[str] | None = None, top_k: int = 3, min_relevance: float | None = None) -> RagSearchResult:
        if user_id != DEFAULT_USER_ID:
            raise RagSearchError("RAG is restricted to the fixed default_user.")
        initial: RagPipelineState = {"user_id": user_id, "query": query, "history": history or [], "document_ids": document_ids or [], "trace": {"pipeline": "advanced_rag_v1", "document_filters": document_ids or [], "embedding": {"provider": self.embedding_provider.provider_name, "model": self.embedding_provider.model, "version": self.embedding_provider.version, "dimension": self.embedding_provider.dimension}, "stages": {}}}
        result = await self._build_graph().ainvoke(initial)
        selected = result.get("selected", [])[: min(top_k, self.settings.rag_final_limit)]
        return RagSearchResult(sources=selected, no_match_reason=result.get("no_match_reason"), trace=result.get("trace"))

    def search(self, **kwargs: Any) -> RagSearchResult:
        return asyncio.run(self.search_async(**kwargs))

    def _build_graph(self):
        graph = StateGraph(RagPipelineState)
        graph.add_node("analyze_query", self._analyze_query)
        graph.add_node("rewrite_query", self._rewrite_query)
        graph.add_node("decompose_query", self._decompose_query)
        graph.add_node("generate_hyde", self._generate_hyde)
        graph.add_node("dense_retrieve", self._dense_retrieve)
        graph.add_node("sparse_retrieve", self._sparse_retrieve)
        graph.add_node("deduplicate_candidates", self._deduplicate)
        graph.add_node("rrf_fuse", self._rrf_fuse)
        graph.add_node("select_context", self._select_context)
        graph.add_node("generate_grounded_answer", self._prepare_grounded_answer)
        graph.add_edge(START, "analyze_query")
        graph.add_conditional_edges("analyze_query", lambda s: "retrieve" if s["plan"].retrieval_required else "skip", {"retrieve": "rewrite_query", "skip": "select_context"})
        graph.add_conditional_edges("rewrite_query", lambda s: "decompose" if s["plan"].subqueries else ("hyde" if s["plan"].hyde_passages else "dense"), {"decompose": "decompose_query", "hyde": "generate_hyde", "dense": "dense_retrieve"})
        graph.add_conditional_edges("decompose_query", lambda s: "hyde" if s["plan"].hyde_passages else "dense", {"hyde": "generate_hyde", "dense": "dense_retrieve"})
        graph.add_edge("generate_hyde", "dense_retrieve")
        graph.add_edge("dense_retrieve", "sparse_retrieve")
        graph.add_edge("sparse_retrieve", "deduplicate_candidates")
        graph.add_edge("deduplicate_candidates", "rrf_fuse")
        graph.add_edge("rrf_fuse", "select_context")
        graph.add_edge("select_context", "generate_grounded_answer")
        graph.add_edge("generate_grounded_answer", END)
        return graph.compile()

    async def _analyze_query(self, state: RagPipelineState) -> dict[str, Any]:
        started = time.perf_counter()
        if self.llm_service:
            history = state.get("history", [])[-6:]
            messages = [*history, {"role": "user", "content": state["query"]}]
            plan = await self.llm_service.complete_structured(messages, RagQueryPlan, system_prompt="你是健身健康知识检索规划器。结合会话历史生成独立查询；多部分问题给出子查询；仅在语义召回有价值时给出一段 HyDE 假设答案。对明显闲聊可设置 retrieval_required=false。只规划检索，不提供医疗诊断。")
        else:
            previous = next((m["content"] for m in reversed(state.get("history", [])) if m.get("role") == "user"), "")
            conversational = any(term in state["query"] for term in ("这个", "那", "继续", "它"))
            standalone = f"{previous}；{state['query']}" if conversational and previous else state["query"]
            parts = [p.strip() for p in re.split(r"[？?；;]|以及|并且", standalone) if p.strip()]
            plan = RagQueryPlan(retrieval_required=True, standalone_query=standalone, subqueries=parts[:4] if len(parts) > 1 else [], hyde_passages=[])
        trace = state["trace"]
        trace["stages"]["analyze_query"] = {"latency_ms": round((time.perf_counter() - started) * 1000, 2), "retrieval_required": plan.retrieval_required, "constraints": plan.constraints}
        return {"plan": plan, "trace": trace}

    async def _rewrite_query(self, state: RagPipelineState) -> dict[str, Any]:
        query = state["plan"].standalone_query.strip() or state["query"]
        state["trace"]["stages"]["rewrite_query"] = {"query": query}
        return {"rewritten_query": query, "trace": state["trace"]}

    async def _decompose_query(self, state: RagPipelineState) -> dict[str, Any]:
        state["trace"]["stages"]["decompose_query"] = {"subqueries": state["plan"].subqueries}
        return {"subqueries": state["plan"].subqueries, "trace": state["trace"]}

    async def _generate_hyde(self, state: RagPipelineState) -> dict[str, Any]:
        state["trace"]["stages"]["generate_hyde"] = {"passages": state["plan"].hyde_passages}
        return {"hyde_passages": state["plan"].hyde_passages, "trace": state["trace"]}

    def _active_rows(self, state: RagPipelineState) -> list[tuple[RagChunk, RagDocument]]:
        statement = select(RagChunk, RagDocument).join(RagDocument, RagDocument.id == RagChunk.document_id).where(
            RagDocument.user_id == state["user_id"], RagDocument.index_status == "ready",
            RagDocument.embedding_provider == self.embedding_provider.provider_name,
            RagDocument.embedding_model == self.embedding_provider.model,
            RagDocument.embedding_version == self.embedding_provider.version,
            RagDocument.embedding_dimension == self.embedding_provider.dimension,
        )
        if state.get("document_ids"):
            statement = statement.where(RagDocument.id.in_(state["document_ids"]))
        return list(self.session.execute(statement).all())

    async def _dense_retrieve(self, state: RagPipelineState) -> dict[str, Any]:
        started = time.perf_counter()
        queries = list(dict.fromkeys([state["query"], state.get("rewritten_query", state["query"]), *state.get("subqueries", []), *state.get("hyde_passages", [])]))
        vectors = await self.embedding_provider.embed_queries(queries)
        rankings: list[dict[str, Any]] = []
        candidates: dict[str, dict[str, Any]] = {}
        for route_index, (query, vector) in enumerate(zip(queries, vectors, strict=True)):
            ranked = self._dense_rank(state, vector)
            ids = []
            for rank, (score, chunk, document) in enumerate(ranked, 1):
                ids.append(chunk.id)
                candidates.setdefault(chunk.id, self._candidate(chunk, document))["routes"].append({"route": f"dense_{route_index}", "query": query, "rank": rank, "raw_score": score})
            rankings.append({"route": f"dense_{route_index}", "ids": ids})
        state["trace"]["stages"]["dense_retrieve"] = {"queries": queries, "ranking_count": len(rankings), "latency_ms": round((time.perf_counter() - started) * 1000, 2), "model": self.embedding_provider.model, "version": self.embedding_provider.version}
        return {"rankings": rankings, "candidates": candidates, "trace": state["trace"]}

    def _dense_rank(self, state: RagPipelineState, vector: list[float]) -> list[tuple[float, RagChunk, RagDocument]]:
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            literal = "[" + ",".join(map(str, vector)) + "]"
            document_filter = "AND d.id IN :document_ids" if state.get("document_ids") else ""
            statement = text(f"""SELECT c.id chunk_id, 1-(c.embedding <=> CAST(:embedding AS vector)) score FROM rag_chunks c JOIN rag_documents d ON d.id=c.document_id WHERE d.user_id=:user_id AND d.index_status='ready' AND d.embedding_provider=:provider AND d.embedding_model=:model AND d.embedding_version=:version AND d.embedding_dimension=:dimension {document_filter} ORDER BY c.embedding <=> CAST(:embedding AS vector) LIMIT :limit""")
            if state.get("document_ids"):
                statement = statement.bindparams(bindparam("document_ids", expanding=True))
            params = {"embedding": literal, "user_id": state["user_id"], "provider": self.embedding_provider.provider_name, "model": self.embedding_provider.model, "version": self.embedding_provider.version, "dimension": self.embedding_provider.dimension, "limit": self.settings.rag_dense_limit, "document_ids": state.get("document_ids", [])}
            scores = {row.chunk_id: float(row.score) for row in self.session.execute(statement, params)}
            rows = self._active_rows(state)
            return sorted([(scores[c.id], c, d) for c, d in rows if c.id in scores], reverse=True, key=lambda item: item[0])
        ranked = [(cosine_similarity(vector, chunk.embedding), chunk, document) for chunk, document in self._active_rows(state)]
        return sorted(ranked, reverse=True, key=lambda item: item[0])[: self.settings.rag_dense_limit]

    async def _sparse_retrieve(self, state: RagPipelineState) -> dict[str, Any]:
        started = time.perf_counter()
        ranked = self.sparse_retriever.rank(state.get("rewritten_query", state["query"]), self._active_rows(state), self.settings.rag_sparse_limit)
        candidates = state.get("candidates", {})
        ids = []
        for rank, (score, chunk, document) in enumerate(ranked, 1):
            ids.append(chunk.id)
            candidates.setdefault(chunk.id, self._candidate(chunk, document))["routes"].append({"route": "bm25", "rank": rank, "raw_score": score})
        rankings = [*state.get("rankings", []), {"route": "bm25", "ids": ids}]
        state["trace"]["stages"]["sparse_retrieve"] = {"engine": "okapi_bm25", "candidate_count": len(ids), "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
        return {"rankings": rankings, "candidates": candidates, "trace": state["trace"]}

    async def _deduplicate(self, state: RagPipelineState) -> dict[str, Any]:
        state["trace"]["stages"]["deduplicate_candidates"] = {"distinct_chunks": len(state.get("candidates", {}))}
        return {"trace": state["trace"]}

    async def _rrf_fuse(self, state: RagPipelineState) -> dict[str, Any]:
        scores = Counter()
        for ranking in state.get("rankings", []):
            for rank, chunk_id in enumerate(ranking["ids"], 1):
                scores[chunk_id] += 1 / (self.settings.rag_rrf_k + rank)
        fused = []
        for chunk_id, score in scores.most_common(self.settings.rag_fused_limit):
            item = state["candidates"][chunk_id]
            item["rrf_score"] = score
            fused.append(item)
        state["trace"]["stages"]["rrf_fuse"] = {"candidate_count": len(fused), "rrf_k": self.settings.rag_rrf_k, "scores": {item["chunk_id"]: item["rrf_score"] for item in fused}, "routes": {item["chunk_id"]: item["routes"] for item in fused}}
        return {"fused": fused, "trace": state["trace"]}

    async def _select_context(self, state: RagPipelineState) -> dict[str, Any]:
        started = time.perf_counter()
        selected = []
        for item in state.get("fused", []):
            dense_scores = [
                float(route["raw_score"])
                for route in item["routes"]
                if route["route"].startswith("dense_")
            ]
            max_dense_score = max(dense_scores, default=None)
            bm25_match = any(route["route"] == "bm25" for route in item["routes"])
            if not bm25_match and (
                max_dense_score is None
                or max_dense_score < self.settings.rag_min_dense_score
            ):
                continue
            relevance = (
                max(0.0, min(1.0, max_dense_score))
                if max_dense_score is not None
                else max(0.0, min(1.0, item["rrf_score"] * self.settings.rag_rrf_k))
            )
            selected.append(
                RagSource(
                    document_id=item["document_id"],
                    chunk_id=item["chunk_id"],
                    title=item["title"],
                    source_uri=item["source_uri"],
                    relevance_score=relevance,
                    excerpt=item["content"],
                    metadata={
                        "ranking_strategy": "rrf",
                        "retrieval_routes": item["routes"],
                        "rrf_score": item["rrf_score"],
                        "max_dense_score": max_dense_score,
                        "bm25_match": bm25_match,
                    },
                )
            )
            if len(selected) == self.settings.rag_final_limit:
                break
        reason = None if selected else "No sufficiently relevant fitness knowledge evidence was found."
        state["trace"]["stages"]["select_context"] = {
            "ranking_strategy": "rrf",
            "selected_count": len(selected),
            "chunk_ids": [source.chunk_id for source in selected],
            "min_dense_score": self.settings.rag_min_dense_score,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        return {"selected": selected, "no_match_reason": reason, "trace": state["trace"]}

    async def _prepare_grounded_answer(self, state: RagPipelineState) -> dict[str, Any]:
        state["trace"]["stages"]["generate_grounded_answer"] = {"evidence_count": len(state.get("selected", [])), "mode": "streamed_by_chat_api"}
        return {"trace": state["trace"]}

    @staticmethod
    def _candidate(chunk: RagChunk, document: RagDocument) -> dict[str, Any]:
        return {"chunk_id": chunk.id, "document_id": document.id, "title": document.title, "source_uri": document.source_uri, "content": chunk.content, "routes": []}


def grounded_fitness_prompt(sources: list[RagSource], no_match_reason: str | None) -> str:
    evidence = "\n\n".join(f"[{index}] {source.title}\n{source.excerpt}" for index, source in enumerate(sources, 1))
    return (
        "你是谨慎的健身健康助手。只能依据下列证据回答，不得补造事实；每个关键建议使用 [1]、[2]、[3] 引用。"
        "如果证据不足，明确说证据不足并询问必要信息，不要给出无依据训练处方。不得诊断疾病；出现疼痛、胸闷、头晕或急性症状时建议停止训练并咨询合格专业人士。\n\n"
        + (f"证据：\n{evidence}" if evidence else f"没有可用证据：{no_match_reason or 'unknown'}")
    )
