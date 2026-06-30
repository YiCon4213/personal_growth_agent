from datetime import UTC, datetime

from fastapi import APIRouter

from app.models.schemas import (
    AgentName,
    AgentStatus,
    AgentStatusPayload,
    ApprovalRequest,
    ChatStreamRequest,
    ErrorCode,
    ErrorResponse,
    MCPTool,
    MCPTransport,
    ProfileCandidate,
    ProfileCategory,
    RagSource,
    RiskLevel,
    SchemaCatalog,
    SkillCandidate,
    StreamEvent,
    StreamEventType,
)

router = APIRouter(prefix="/contracts", tags=["contracts"])


@router.get("/schema-catalog", response_model=SchemaCatalog)
def schema_catalog() -> SchemaCatalog:
    now = datetime.now(UTC)
    return SchemaCatalog(
        chat_request=ChatStreamRequest(
            message="Plan my Python backend learning path.",
            thread_id="thread_demo",
        ),
        stream_event=StreamEvent(
            event=StreamEventType.AGENT_STATUS,
            thread_id="thread_demo",
            run_id="run_demo",
            timestamp=now,
            payload={"agent": "supervisor", "status": "running"},
        ),
        agent_status=AgentStatusPayload(
            agent=AgentName.SUPERVISOR,
            status=AgentStatus.RUNNING,
            message="Routing the request.",
        ),
        rag_source=RagSource(
            document_id="doc_demo",
            chunk_id="chunk_demo",
            title="Demo source",
            relevance_score=0.9,
            excerpt="A short cited excerpt from the knowledge base.",
        ),
        mcp_tool=MCPTool(
            id="tool_demo",
            server_id="server_demo",
            name="weather.lookup",
            transport=MCPTransport.HTTP,
            input_schema={"type": "object", "properties": {"city": {"type": "string"}}},
            risk_level=RiskLevel.LOW,
        ),
        approval_request=ApprovalRequest(
            id="approval_demo",
            thread_id="thread_demo",
            tool_name="calendar.create_event",
            arguments={"title": "Study block"},
            risk_level=RiskLevel.HIGH,
            expected_impact="Create a calendar event after user approval.",
        ),
        profile_candidate=ProfileCandidate(
            id="profile_candidate_demo",
            category=ProfileCategory.LEARNING,
            content="The user prefers evening study sessions.",
            source_summary="User said they learn better after 9 PM.",
        ),
        skill_candidate=SkillCandidate(
            id="skill_candidate_demo",
            title="Evening planning preference",
            content="Prefer schedules that place deep learning tasks after 9 PM.",
            applicable_scenarios=["learning planning"],
            source_thread_id="thread_demo",
        ),
        error=ErrorResponse(
            code=ErrorCode.VALIDATION_ERROR,
            message="Request validation failed.",
        ),
    )
