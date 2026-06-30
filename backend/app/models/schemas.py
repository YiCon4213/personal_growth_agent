from __future__ import annotations



from datetime import datetime

from enum import StrEnum

from typing import Any



from pydantic import BaseModel, Field, HttpUrl, model_validator





class MessageRole(StrEnum):

    USER = "user"

    ASSISTANT = "assistant"

    SYSTEM = "system"

    TOOL = "tool"





class StreamEventType(StrEnum):

    TOKEN = "token"

    AGENT_STATUS = "agent_status"

    TOOL_CALL = "tool_call"

    APPROVAL_REQUIRED = "approval_required"

    RAG_SOURCES = "rag_sources"

    PROFILE_CANDIDATE = "profile_candidate"

    SKILL_CANDIDATE = "skill_candidate"

    FINAL = "final"

    ERROR = "error"





class AgentName(StrEnum):

    SUPERVISOR = "supervisor"

    LEARNING = "learning"

    FITNESS = "fitness"

    LIFE = "life"

    RAG = "rag"

    PROFILE = "profile"

    SKILL = "skill"





class AgentStatus(StrEnum):

    QUEUED = "queued"

    RUNNING = "running"

    WAITING_APPROVAL = "waiting_approval"

    COMPLETED = "completed"

    FAILED = "failed"





class RiskLevel(StrEnum):

    LOW = "low"

    MEDIUM = "medium"

    HIGH = "high"





class CandidateStatus(StrEnum):

    PENDING = "pending"

    APPROVED = "approved"

    EXECUTING = "executing"

    REJECTED = "rejected"





class ApprovalStatus(StrEnum):

    PENDING = "pending"

    APPROVED = "approved"

    EXECUTING = "executing"

    REJECTED = "rejected"

    EXECUTED = "executed"

    FAILED = "failed"





class ProfileCategory(StrEnum):

    LEARNING = "learning"

    FITNESS = "fitness"

    LIFE = "life"

    PREFERENCE = "preference"

    LIMITATION = "limitation"

    COMMUNICATION = "communication"





class SkillStatus(StrEnum):

    CANDIDATE = "candidate"

    ENABLED = "enabled"

    DISABLED = "disabled"





class MCPTransport(StrEnum):

    HTTP = "http"

    SSE = "sse"

    STREAMABLE_HTTP = "streamable_http"

    STDIO = "stdio"

    STDIO_BRIDGE = "stdio_bridge"





class ErrorCode(StrEnum):

    VALIDATION_ERROR = "validation_error"

    NOT_FOUND = "not_found"

    EXTERNAL_SERVICE_ERROR = "external_service_error"

    APPROVAL_REQUIRED = "approval_required"

    INTERNAL_ERROR = "internal_error"





class Attachment(BaseModel):

    id: str | None = None

    filename: str

    content_type: str

    url: HttpUrl | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)





class ChatMessage(BaseModel):

    id: str | None = None

    role: MessageRole

    content: str

    created_at: datetime | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)





class ConversationCreateRequest(BaseModel):

    title: str | None = Field(default=None, max_length=200)


class ConversationRenameRequest(BaseModel):

    title: str = Field(min_length=1, max_length=200)


class ConversationSummary(BaseModel):

    id: str

    title: str

    created_at: datetime

    updated_at: datetime

    message_count: int = 0


class ConversationDetail(ConversationSummary):

    messages: list[ChatMessage] = Field(default_factory=list)

class ChatStreamRequest(BaseModel):

    message: str = Field(min_length=1, max_length=32000, description="User message for the unified assistant.")

    thread_id: str = Field(min_length=1, max_length=80, description="Stable conversation thread id.")

    image_url: HttpUrl | None = Field(

        default=None,

        description="Backward-compatible optional image URL from the old chat shape.",

    )

    attachments: list[Attachment] = Field(default_factory=list)

    enabled_mcp_server_ids: list[str] = Field(default_factory=list, max_length=50)

    rag_collection_ids: list[str] = Field(default_factory=list, max_length=100)

    user_id: str | None = Field(default=None, description="Deprecated; fixed default_user is always used.")

    metadata: dict[str, Any] = Field(default_factory=dict)





class AgentStatusPayload(BaseModel):

    agent: AgentName

    status: AgentStatus

    message: str | None = None

    details: dict[str, Any] = Field(default_factory=dict)





class TokenPayload(BaseModel):

    text: str





class ToolCallPayload(BaseModel):

    tool_id: str

    tool_name: str

    server_id: str | None = None

    arguments: dict[str, Any] = Field(default_factory=dict)

    risk_level: RiskLevel = RiskLevel.LOW

    status: str = "planned"





class RagSource(BaseModel):

    document_id: str

    chunk_id: str

    title: str

    source_uri: str | None = None

    relevance_score: float | None = Field(default=None, ge=0, le=1)

    excerpt: str

    metadata: dict[str, Any] = Field(default_factory=dict)





class RagSourcesPayload(BaseModel):

    sources: list[RagSource] = Field(default_factory=list)

    no_match_reason: str | None = None





class ProfileCandidate(BaseModel):
    id: str
    user_id: str | None = None
    category: ProfileCategory
    content: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_summary: str
    source_thread_id: str | None = None
    status: CandidateStatus = CandidateStatus.PENDING
    created_at: datetime | None = None





class ProfileCandidatePayload(BaseModel):

    candidate: ProfileCandidate





class SkillCandidate(BaseModel):

    id: str

    user_id: str | None = None

    title: str

    content: str

    applicable_scenarios: list[str] = Field(default_factory=list)

    source_thread_id: str

    status: CandidateStatus = CandidateStatus.PENDING

    created_at: datetime | None = None





class SkillCandidatePayload(BaseModel):

    candidate: SkillCandidate





class FinalPayload(BaseModel):

    message: str

    sources: list[RagSource] = Field(default_factory=list)

    metadata: dict[str, Any] = Field(default_factory=dict)





class ErrorResponse(BaseModel):

    code: ErrorCode

    message: str

    details: dict[str, Any] = Field(default_factory=dict)





class ErrorPayload(BaseModel):

    error: ErrorResponse





class ApprovalRequest(BaseModel):

    id: str

    user_id: str | None = None

    thread_id: str

    tool_id: str | None = None

    server_id: str | None = None

    tool_name: str

    arguments: dict[str, Any] = Field(default_factory=dict)

    risk_level: RiskLevel

    expected_impact: str

    status: ApprovalStatus = ApprovalStatus.PENDING

    created_at: datetime | None = None

    decided_at: datetime | None = None

    executed_at: datetime | None = None

    tool_call_id: str | None = None

    execution_result: dict[str, Any] = Field(default_factory=dict)

    error_message: str | None = None





class ApprovalRequiredPayload(BaseModel):

    approval: ApprovalRequest





class ApprovalDecisionRequest(BaseModel):

    user_id: str | None = None

    approver_id: str | None = None

    reason: str | None = None

    timeout_seconds: float = Field(default=10, ge=1, le=60)





class ApprovalDecisionResponse(BaseModel):

    approval: ApprovalRequest

    tool_call: MCPToolCallResponse | None = None





class MCPTool(BaseModel):

    id: str

    server_id: str

    name: str

    description: str | None = None

    transport: MCPTransport

    input_schema: dict[str, Any] = Field(default_factory=dict)

    risk_level: RiskLevel = RiskLevel.LOW

    enabled: bool = True

    metadata: dict[str, Any] = Field(default_factory=dict)





class MCPServerCreateRequest(BaseModel):

    user_id: str = Field(min_length=1)

    name: str = Field(min_length=1, max_length=160)

    endpoint_url: str = ""

    transport: MCPTransport = MCPTransport.HTTP

    enabled: bool = True

    metadata: dict[str, Any] = Field(default_factory=dict)
    command: str | None = Field(default=None, min_length=1, max_length=260)

    args: list[str] = Field(default_factory=list, max_length=50)

    env: dict[str, str] = Field(default_factory=dict)

    working_directory: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_transport_configuration(self) -> "MCPServerCreateRequest":
        if self.transport in {MCPTransport.STDIO, MCPTransport.STDIO_BRIDGE}:
            if not self.command:
                raise ValueError("command is required for stdio MCP servers")
        elif not self.endpoint_url.strip():
            raise ValueError("endpoint_url is required for HTTP MCP servers")
        return self




class MCPServerResponse(BaseModel):

    id: str

    user_id: str

    name: str

    endpoint_url: str

    transport: MCPTransport

    enabled: bool

    created_at: datetime | None = None

    updated_at: datetime | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)
    command: str | None = None

    args: list[str] = Field(default_factory=list)

    env_keys: list[str] = Field(default_factory=list)

    working_directory: str | None = None




class MCPRefreshToolsResponse(BaseModel):

    server: MCPServerResponse

    tools: list[MCPTool] = Field(default_factory=list)





class MCPToolCallRequest(BaseModel):

    user_id: str = Field(min_length=1)

    thread_id: str | None = None

    arguments: dict[str, Any] = Field(default_factory=dict)

    timeout_seconds: float = Field(default=10, ge=1, le=60)





class MCPToolCallResponse(BaseModel):

    call_id: str

    tool: MCPTool

    arguments: dict[str, Any] = Field(default_factory=dict)

    output: dict[str, Any] = Field(default_factory=dict)

    status: str

    error: ErrorResponse | None = None





class UserProfileItem(BaseModel):
    id: str
    user_id: str | None = None
    category: ProfileCategory
    content: str
    source_summary: str
    source_thread_id: str | None = None
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None






class ProfileCandidateDecisionRequest(BaseModel):
    user_id: str | None = None
    reviewer_id: str | None = None
    reason: str | None = None


class ProfileCandidateDecisionResponse(BaseModel):
    candidate: ProfileCandidate
    profile_item: UserProfileItem | None = None

class UserSkill(BaseModel):

    id: str

    user_id: str | None = None

    title: str

    content: str

    applicable_scenarios: list[str] = Field(default_factory=list)

    status: SkillStatus = SkillStatus.ENABLED

    source_thread_id: str | None = None

    created_at: datetime | None = None

    updated_at: datetime | None = None






class SkillCandidateDecisionRequest(BaseModel):
    user_id: str | None = None
    reviewer_id: str | None = None
    reason: str | None = None


class SkillCandidateDecisionResponse(BaseModel):
    candidate: SkillCandidate
    skill: UserSkill | None = None

class StreamEvent(BaseModel):

    event: StreamEventType

    thread_id: str

    run_id: str

    timestamp: datetime

    payload: dict[str, Any] = Field(default_factory=dict)







class RagDocumentImportRequest(BaseModel):

    user_id: str = Field(min_length=1)

    title: str = Field(min_length=1, max_length=240)

    content: str = Field(min_length=1, description="Markdown or TXT content to import.")

    source_uri: str | None = None

    source_type: str | None = Field(default=None, description="markdown, txt, or pdf metadata label.")

    metadata: dict[str, Any] = Field(default_factory=dict)





class RagFileImportRequest(BaseModel):

    user_id: str = Field(min_length=1)

    file_path: str = Field(min_length=1, description="Local Markdown, TXT, or PDF path readable by backend.")

    title: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)





class RagDocumentResponse(BaseModel):

    id: str

    user_id: str

    title: str

    source_uri: str | None = None

    source_type: str | None = None

    embedding_provider: str

    embedding_model: str

    embedding_version: str

    embedding_dimension: int

    content_hash: str

    index_status: str

    chunk_count: int

    created_at: datetime | None = None

    updated_at: datetime | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)





class RagSearchRequest(BaseModel):

    user_id: str = Field(min_length=1)

    query: str = Field(min_length=1)

    document_ids: list[str] = Field(default_factory=list)

    top_k: int = Field(default=4, ge=1, le=20)

    min_relevance: float = Field(default=0.05, ge=0, le=1)





class RagSearchResponse(BaseModel):

    sources: list[RagSource] = Field(default_factory=list)

    no_match_reason: str | None = None

    trace: dict[str, Any] = Field(default_factory=dict)





class SchemaCatalog(BaseModel):

    chat_request: ChatStreamRequest

    stream_event: StreamEvent

    agent_status: AgentStatusPayload

    rag_source: RagSource

    mcp_tool: MCPTool

    approval_request: ApprovalRequest

    profile_candidate: ProfileCandidate

    skill_candidate: SkillCandidate

    error: ErrorResponse

    rag_document_import: RagDocumentImportRequest | None = None

    rag_document: RagDocumentResponse | None = None

    rag_search: RagSearchRequest | None = None

    mcp_server_create: MCPServerCreateRequest | None = None

    mcp_server: MCPServerResponse | None = None

    mcp_tool_call: MCPToolCallRequest | None = None
