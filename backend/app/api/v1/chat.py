from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agents.graph import run_supervisor_graph
from app.agents.supervisor import classify_route
from app.agents.learning import (
    LEARNING_PLAN_SYSTEM_PROMPT,
    LearningPlan,
    learning_messages,
    learning_response_prompt,
)
from app.core.config import get_settings
from app.core.database import get_session
from app.models.schemas import (
    AgentName,
    AgentStatus,
    AgentStatusPayload,
    ApprovalRequest,
    ApprovalRequiredPayload,
    ChatStreamRequest,
    ErrorCode,
    ErrorResponse,
    FinalPayload,
    MessageRole,
    ProfileCandidate,
    ProfileCandidatePayload,
    RagSourcesPayload,
    SkillCandidate,
    SkillCandidatePayload,
    StreamEvent,
    StreamEventType,
    TokenPayload,
    ToolCallPayload,
)
from app.services.data_store import DataStore
from app.services.embedding_service import EmbeddingServiceError
from app.services.llm_service import DeepSeekLLMService, LLMService, LLMServiceError
from app.services.mcp_service import MCPService
from app.services.profile_service import ProfileService, profile_candidate_to_schema
from app.services.rag_service import FitnessRagService, RagSearchResult, grounded_fitness_prompt
from app.services.skill_service import SkillService, skill_candidate_to_schema

router = APIRouter(prefix="/chat", tags=["chat"])
DEFAULT_USER_ID = "default_user"
AGENT_NAME_BY_VALUE = {agent.value: agent for agent in AgentName}
AGENT_STATUS_BY_VALUE = {status.value: status for status in AgentStatus}


def build_stream_event(
    *, event_type: StreamEventType, thread_id: str, run_id: str, payload: dict[str, Any]
) -> StreamEvent:
    return StreamEvent(
        event=event_type,
        thread_id=thread_id,
        run_id=run_id,
        timestamp=datetime.now(UTC),
        payload=payload,
    )


def format_sse(event: StreamEvent) -> str:
    return f"event: {event.event.value}\ndata: {event.model_dump_json()}\n\n"


def agent_status_payload(
    *, agent: str, status: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    return AgentStatusPayload(
        agent=AGENT_NAME_BY_VALUE.get(agent, AgentName.SUPERVISOR),
        status=AGENT_STATUS_BY_VALUE.get(status, AgentStatus.RUNNING),
        message=message,
        details=details or {},
    ).model_dump(mode="json")


def _event(
    event_type: StreamEventType,
    request: ChatStreamRequest,
    run_id: str,
    payload: dict[str, Any],
) -> str:
    return format_sse(
        build_stream_event(
            event_type=event_type,
            thread_id=request.thread_id,
            run_id=run_id,
            payload=payload,
        )
    )


def _history_messages(store: DataStore, thread_id: str, limit: int) -> list[dict[str, str]]:
    return [
        {"role": item.role, "content": item.content}
        for item in store.list_messages(thread_id, limit=limit)
        if item.role in {MessageRole.USER.value, MessageRole.ASSISTANT.value, MessageRole.SYSTEM.value}
    ]


def _context_prompt(profile_context: list[dict[str, Any]], skill_context: list[dict[str, Any]]) -> str:
    notes: list[str] = []
    if profile_context:
        notes.append("已确认用户画像：" + "；".join(str(item.get("content", "")) for item in profile_context[:3]))
    if skill_context:
        notes.append("已启用 Skill：" + "；".join(str(item.get("content", "")) for item in skill_context[:2]))
    return "\n".join(notes)


async def stream_graph_chat(
    request: ChatStreamRequest,
    run_id: str,
    session: Session,
    injected_llm_service: LLMService | None,
    injected_embedding_provider: Any | None = None,
) -> AsyncIterator[str]:
    settings = get_settings()
    store = DataStore(session)
    try:
        if request.message.strip() == "__trigger_error__":
            raise RuntimeError("Forced graph error for SSE validation.")

        yield _event(
            StreamEventType.AGENT_STATUS,
            request,
            run_id,
            agent_status_payload(
                agent="supervisor", status="running", message="Supervisor is routing the request."
            ),
        )

        thread = store.get_thread(request.thread_id)
        if thread is not None and thread.user_id not in {None, DEFAULT_USER_ID}:
            raise RuntimeError("Conversation does not belong to the fixed default_user.")
        history = _history_messages(store, request.thread_id, settings.conversation_history_limit)
        title = request.message.strip().replace("\n", " ")[:60] or "新会话"
        thread = store.upsert_thread(
            request.thread_id,
            user_id=DEFAULT_USER_ID,
            title=title if thread is None or not thread.title or thread.title == "新会话" else None,
        )

        profile_service = ProfileService(session)
        skill_service = SkillService(session)
        mcp_service = (
            MCPService(
                session,
                llm_service=injected_llm_service or DeepSeekLLMService(settings),
            )
            if request.enabled_mcp_server_ids
            else None
        )
        profile_context = profile_service.relevant_profile_context(DEFAULT_USER_ID, request.message)
        skill_context = skill_service.relevant_skill_context(DEFAULT_USER_ID, request.message)
        skill_service.record_user_message(
            user_id=DEFAULT_USER_ID, thread_id=request.thread_id, message=request.message
        )
        thread.updated_at = datetime.now(UTC)
        session.commit()

        rag_trace: dict[str, Any] = {}
        rag_service: Any | None = None
        if classify_route(request.message) == "fitness":
            advanced_rag = FitnessRagService(
                session,
                embedding_provider=injected_embedding_provider,
                llm_service=injected_llm_service,
            )
            rag_result = await advanced_rag.search_async(
                user_id=DEFAULT_USER_ID,
                query=request.message,
                history=history,
                document_ids=request.rag_collection_ids or None,
                top_k=3,
            )
            rag_trace = rag_result.trace or {}

            class PrecomputedRagService:
                def search(self, **kwargs: Any) -> RagSearchResult:
                    return rag_result

            rag_service = PrecomputedRagService()

        result = run_supervisor_graph(
            message=request.message,
            thread_id=request.thread_id,
            run_id=run_id,
            user_id=DEFAULT_USER_ID,
            history=history,
            rag_collection_ids=request.rag_collection_ids,
            rag_service=rag_service,
            enabled_mcp_server_ids=request.enabled_mcp_server_ids,
            mcp_service=mcp_service,
            profile_context=profile_context,
            skill_context=skill_context,
        )
        route = result.get("route", "general")

        for record in result.get("status_records", []):
            yield _event(
                StreamEventType.AGENT_STATUS,
                request,
                run_id,
                agent_status_payload(
                    agent=record["agent"],
                    status=record["status"],
                    message=record["message"],
                    details={"route": route},
                ),
            )

        for call in result.get("mcp_tool_calls", []):
            tool = call.get("tool") or {}
            payload = ToolCallPayload(
                tool_id=tool.get("id", "unknown"),
                tool_name=tool.get("name", "unknown"),
                server_id=tool.get("server_id"),
                arguments=call.get("arguments") or {},
                risk_level=tool.get("risk_level", "low"),
                status=call.get("status", "unknown"),
            ).model_dump(mode="json")
            payload.update({"output": call.get("output") or {}})
            if call.get("call_id"):
                payload["call_id"] = call["call_id"]
            if call.get("error"):
                payload["error"] = call["error"]
            yield _event(StreamEventType.TOOL_CALL, request, run_id, payload)

        for approval in result.get("approval_requests", []):
            yield _event(
                StreamEventType.APPROVAL_REQUIRED,
                request,
                run_id,
                ApprovalRequiredPayload(
                    approval=ApprovalRequest.model_validate(approval)
                ).model_dump(mode="json"),
            )

        rag_sources = result.get("rag_sources", [])
        rag_no_match_reason = result.get("rag_no_match_reason")
        if rag_sources or rag_no_match_reason:
            yield _event(
                StreamEventType.RAG_SOURCES,
                request,
                run_id,
                RagSourcesPayload(
                    sources=rag_sources, no_match_reason=rag_no_match_reason
                ).model_dump(mode="json"),
            )

        reply = ""
        if route in {"general", "learning", "fitness"}:
            llm_service = injected_llm_service or DeepSeekLLMService(settings)
            messages = learning_messages(history, request.message)
            context_note = _context_prompt(profile_context, skill_context)
            if route == "fitness":
                system_prompt = grounded_fitness_prompt(rag_sources, rag_no_match_reason)
            elif route == "learning":
                plan = await llm_service.complete_structured(
                    messages,
                    LearningPlan,
                    system_prompt=LEARNING_PLAN_SYSTEM_PROMPT + (f"\n{context_note}" if context_note else ""),
                )
                result["learning_plan"] = plan.model_dump(mode="json")
                system_prompt = learning_response_prompt(plan)
            else:
                system_prompt = (
                    "你是个人成长助手的通用对话 Agent。直接、诚实、自然地回答当前问题；"
                    "结合提供的有限同会话历史，但不要声称记得其他会话。"
                    + (f"\n{context_note}" if context_note else "")
                )
            async for text in llm_service.stream_text(messages, system_prompt=system_prompt):
                reply += text
                yield _event(
                    StreamEventType.TOKEN,
                    request,
                    run_id,
                    TokenPayload(text=text).model_dump(mode="json"),
                )
            if not reply.strip():
                raise LLMServiceError("DeepSeek 未返回文本内容，请重试。", kind="empty_response")
        else:
            reply = result.get("response") or "我已收到你的消息，但当前图没有生成回复。"
            yield _event(
                StreamEventType.TOKEN,
                request,
                run_id,
                TokenPayload(text=reply).model_dump(mode="json"),
            )

        profile_candidates = [
            profile_candidate_to_schema(candidate).model_dump(mode="json")
            for candidate in profile_service.extract_candidates_from_message(
                user_id=DEFAULT_USER_ID,
                thread_id=request.thread_id,
                message=request.message,
            )
        ]
        skill_service.record_assistant_message(
            user_id=DEFAULT_USER_ID, thread_id=request.thread_id, message=reply
        )
        created_skill_candidate = skill_service.maybe_generate_candidate(
            user_id=DEFAULT_USER_ID, thread_id=request.thread_id
        )
        skill_candidates = (
            [skill_candidate_to_schema(created_skill_candidate).model_dump(mode="json")]
            if created_skill_candidate is not None
            else []
        )
        thread.updated_at = datetime.now(UTC)
        session.commit()

        for candidate in profile_candidates:
            yield _event(
                StreamEventType.PROFILE_CANDIDATE,
                request,
                run_id,
                ProfileCandidatePayload(
                    candidate=ProfileCandidate.model_validate(candidate)
                ).model_dump(mode="json"),
            )
        for candidate in skill_candidates:
            yield _event(
                StreamEventType.SKILL_CANDIDATE,
                request,
                run_id,
                SkillCandidatePayload(
                    candidate=SkillCandidate.model_validate(candidate)
                ).model_dump(mode="json"),
            )

        metadata: dict[str, Any] = {"graph": "supervisor", "route": route}
        for key, value in (
            ("learning_plan", result.get("learning_plan")),
            ("rag_no_match_reason", rag_no_match_reason),
            ("rag_trace", rag_trace),
            ("mcp_tool_calls", result.get("mcp_tool_calls")),
            ("approval_requests", result.get("approval_requests")),
            ("profile_context", profile_context),
            ("skill_context", skill_context),
            ("profile_candidates", profile_candidates),
            ("skill_candidates", skill_candidates),
        ):
            if value:
                metadata[key] = value

        yield _event(
            StreamEventType.FINAL,
            request,
            run_id,
            FinalPayload(message=reply, sources=rag_sources, metadata=metadata).model_dump(mode="json"),
        )
    except EmbeddingServiceError as exc:
        session.rollback()
        yield _event(
            StreamEventType.ERROR,
            request,
            run_id,
            ErrorResponse(
                code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                message=str(exc),
                details={"service": "embedding"},
            ).model_dump(mode="json"),
        )
    except LLMServiceError as exc:
        session.rollback()
        yield _event(
            StreamEventType.ERROR,
            request,
            run_id,
            ErrorResponse(
                code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                message=exc.message,
                details={"service": "deepseek", "kind": exc.kind, "status_code": exc.status_code},
            ).model_dump(mode="json"),
        )
    except Exception as exc:
        session.rollback()
        yield _event(
            StreamEventType.ERROR,
            request,
            run_id,
            ErrorResponse(
                code=ErrorCode.INTERNAL_ERROR,
                message="Chat stream failed.",
                details={"error_type": exc.__class__.__name__},
            ).model_dump(mode="json"),
        )


@router.post("/stream")
async def chat_stream(
    request: ChatStreamRequest,
    http_request: Request,
    session: Session = Depends(get_session),
) -> StreamingResponse:
    run_id = f"run_{uuid4().hex}"
    return StreamingResponse(
        stream_graph_chat(request, run_id, session, getattr(http_request.app.state, "llm_service", None), getattr(http_request.app.state, "embedding_provider", None)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
