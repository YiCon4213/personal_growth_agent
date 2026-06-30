from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator, UserDefinedType

from app.models.schemas import (
    ApprovalStatus,
    CandidateStatus,
    MCPTransport,
    MessageRole,
    ProfileCategory,
    RiskLevel,
    SkillStatus,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class JsonDict(TypeDecorator[dict[str, Any]]):
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class Vector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimension: int = 1024) -> None:
        self.dimension = dimension

    def get_col_spec(self, **kw: Any) -> str:
        return f"vector({self.dimension})"

    def bind_processor(self, dialect):  # type: ignore[no-untyped-def]
        def process(value: list[float] | None) -> str | None:
            if value is None:
                return None
            return "[" + ",".join(str(float(item)) for item in value) + "]"

        return process

    def result_processor(self, dialect, coltype):  # type: ignore[no-untyped-def]
        def process(value: Any) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, list):
                return [float(item) for item in value]
            text = str(value).strip("[]")
            if not text:
                return []
            return [float(item) for item in text.split(",")]

        return process


@compiles(Vector, "sqlite")
def compile_vector_sqlite(type_: Vector, compiler, **kw: Any) -> str:  # type: ignore[no-untyped-def]
    return "JSON"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Thread(TimestampMixin, Base):
    __tablename__ = "threads"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(80), index=True)
    title: Mapped[str | None] = mapped_column(String(200))
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict)

    messages: Mapped[list[Message]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default=MessageRole.USER.value, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict)

    thread: Mapped[Thread] = relationship(back_populates="messages")


class UserProfileItem(TimestampMixin, Base):
    __tablename__ = "user_profile_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(40), default=ProfileCategory.PREFERENCE.value, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_thread_id: Mapped[str | None] = mapped_column(String(80), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict)


class ProfileCandidate(Base):
    __tablename__ = "profile_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(40), default=ProfileCategory.PREFERENCE.value, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[int | None] = mapped_column(Integer)
    source_summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_thread_id: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(20), default=CandidateStatus.PENDING.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict)


class UserSkill(TimestampMixin, Base):
    __tablename__ = "user_skills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    applicable_scenarios: Mapped[list[str]] = mapped_column(JsonDict, default=list)
    status: Mapped[str] = mapped_column(String(20), default=SkillStatus.ENABLED.value, nullable=False)
    source_thread_id: Mapped[str | None] = mapped_column(String(80), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict)


class SkillCandidate(Base):
    __tablename__ = "skill_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    applicable_scenarios: Mapped[list[str]] = mapped_column(JsonDict, default=list)
    source_thread_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=CandidateStatus.PENDING.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict)


class MCPServer(TimestampMixin, Base):
    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(Text, nullable=False)
    transport: Mapped[str] = mapped_column(String(40), default=MCPTransport.HTTP.value, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict)
    command: Mapped[str | None] = mapped_column(String(260))
    args: Mapped[list[str]] = mapped_column(JsonDict, default=list)
    env: Mapped[dict[str, str]] = mapped_column(JsonDict, default=dict)
    working_directory: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_mcp_servers_user_name"),)


class MCPTool(TimestampMixin, Base):
    __tablename__ = "mcp_tools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    server_id: Mapped[str] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict)
    risk_level: Mapped[str] = mapped_column(String(20), default=RiskLevel.LOW.value, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict)

    __table_args__ = (UniqueConstraint("server_id", "name", name="uq_mcp_tools_server_name"),)


class MCPToolCall(Base):
    __tablename__ = "mcp_tool_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(80), index=True)
    server_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    tool_id: Mapped[str | None] = mapped_column(String(36), index=True)
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict)
    risk_level: Mapped[str] = mapped_column(String(20), default=RiskLevel.LOW.value, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)



class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    thread_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    server_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    tool_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict)
    risk_level: Mapped[str] = mapped_column(String(20), default=RiskLevel.HIGH.value, nullable=False)
    expected_impact: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=ApprovalStatus.PENDING.value, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(80))
    rejected_by: Mapped[str | None] = mapped_column(String(80))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    tool_call_id: Mapped[str | None] = mapped_column(String(36), index=True)
    execution_result: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class RagDocument(TimestampMixin, Base):
    __tablename__ = "rag_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    source_uri: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(String(60))
    embedding_provider: Mapped[str] = mapped_column(String(80), nullable=False, default="unknown")
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(80), nullable=False, default="1")
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    index_status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict)

    chunks: Mapped[list[RagChunk]] = relationship(back_populates="document", cascade="all, delete-orphan")


class RagChunk(Base):
    __tablename__ = "rag_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(
        ForeignKey("rag_documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    embedding_provider: Mapped[str] = mapped_column(String(80), nullable=False, default="unknown")
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(80), nullable=False, default="1")
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False, default=1024)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict)

    document: Mapped[RagDocument] = relationship(back_populates="chunks")

    __table_args__ = (UniqueConstraint("document_id", "chunk_index", name="uq_rag_chunks_document_index"),)
