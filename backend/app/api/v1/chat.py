from collections.abc import AsyncIterator

from datetime import UTC, datetime

from typing import Any

from uuid import uuid4



from fastapi import APIRouter

from fastapi.responses import StreamingResponse



from app.agents.graph import run_supervisor_graph

from app.core.database import DatabaseConfigurationError, create_session_factory

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

    ProfileCandidate,

    ProfileCandidatePayload,

    SkillCandidate,

    SkillCandidatePayload,

    RagSourcesPayload,

    StreamEvent,

    StreamEventType,

    TokenPayload,

    ToolCallPayload,

)

from app.services.mcp_service import MCPService

from app.services.profile_service import ProfileService, profile_candidate_to_schema

from app.services.skill_service import SkillService, skill_candidate_to_schema



router = APIRouter(prefix="/chat", tags=["chat"])



AGENT_NAME_BY_VALUE = {agent.value: agent for agent in AgentName}

AGENT_STATUS_BY_VALUE = {status.value: status for status in AgentStatus}





def build_stream_event(

    *,

    event_type: StreamEventType,

    thread_id: str,

    run_id: str,

    payload: dict[str, Any],

) -> StreamEvent:

    return StreamEvent(

        event=event_type,

        thread_id=thread_id,

        run_id=run_id,

        timestamp=datetime.now(UTC),

        payload=payload,

    )





def format_sse(event: StreamEvent) -> str:

    event_name = event.event.value

    event_json = event.model_dump_json()

    return f"event: {event_name}\ndata: {event_json}\n\n"





def agent_status_payload(

    *,

    agent: str,

    status: str,

    message: str,

    details: dict[str, Any] | None = None,

) -> dict[str, Any]:

    return AgentStatusPayload(

        agent=AGENT_NAME_BY_VALUE.get(agent, AgentName.SUPERVISOR),

        status=AGENT_STATUS_BY_VALUE.get(status, AgentStatus.RUNNING),

        message=message,

        details=details or {},

    ).model_dump(mode="json")





def split_tokens(message: str) -> list[str]:

    return [token for token in message.split() if token]





async def stream_graph_chat(request: ChatStreamRequest, run_id: str) -> AsyncIterator[str]:

    try:

        if request.message.strip() == "__trigger_error__":

            raise RuntimeError("Forced graph error for SSE validation.")



        yield format_sse(

            build_stream_event(

                event_type=StreamEventType.AGENT_STATUS,

                thread_id=request.thread_id,

                run_id=run_id,

                payload=agent_status_payload(

                    agent="supervisor",

                    status="running",

                    message="Supervisor is routing the request.",

                ),

            )

        )



        service_session = None

        mcp_service = None

        profile_service = None

        skill_service = None

        profile_context: list[dict[str, Any]] = []

        skill_context: list[dict[str, Any]] = []

        profile_candidates: list[dict[str, Any]] = []

        skill_candidates: list[dict[str, Any]] = []

        user_id = request.user_id or "default_user"



        try:

            if request.enabled_mcp_server_ids or request.user_id:

                service_session = create_session_factory()()

                if request.enabled_mcp_server_ids:

                    mcp_service = MCPService(service_session)

                profile_service = ProfileService(service_session)

                skill_service = SkillService(service_session)

                profile_context = profile_service.relevant_profile_context(user_id, request.message)

                skill_context = skill_service.relevant_skill_context(user_id, request.message)

        except DatabaseConfigurationError:

            if request.enabled_mcp_server_ids:

                raise

            service_session = None

            profile_service = None



        try:

            if skill_service is not None:

                skill_service.record_user_message(user_id=user_id, thread_id=request.thread_id, message=request.message)

            graph_user_id = user_id if request.enabled_mcp_server_ids else request.user_id
            result = run_supervisor_graph(

                message=request.message,

                thread_id=request.thread_id,

                run_id=run_id,

                user_id=graph_user_id,

                rag_collection_ids=request.rag_collection_ids,

                enabled_mcp_server_ids=request.enabled_mcp_server_ids,

                mcp_service=mcp_service,

                profile_context=profile_context,

                skill_context=skill_context,

            )

            if skill_service is not None:

                skill_service.record_assistant_message(

                    user_id=graph_user_id,

                    thread_id=request.thread_id,

                    message=result.get("response") or "",

                )

                created_skill_candidate = skill_service.maybe_generate_candidate(

                    user_id=graph_user_id,

                    thread_id=request.thread_id,

                )

                if created_skill_candidate is not None:

                    skill_candidates = [

                        skill_candidate_to_schema(created_skill_candidate).model_dump(mode="json")

                    ]

            if profile_service is not None:

                created_candidates = profile_service.extract_candidates_from_message(

                    user_id=graph_user_id,

                    thread_id=request.thread_id,

                    message=request.message,

                )

                profile_candidates = [

                    profile_candidate_to_schema(candidate).model_dump(mode="json")

                    for candidate in created_candidates

                ]

            if service_session is not None:

                service_session.commit()

        except Exception:

            if service_session is not None:

                service_session.rollback()

            raise

        finally:

            if service_session is not None:

                service_session.close()



        route = result.get("route", "general")

        for record in result.get("status_records", []):

            yield format_sse(

                build_stream_event(

                    event_type=StreamEventType.AGENT_STATUS,

                    thread_id=request.thread_id,

                    run_id=run_id,

                    payload=agent_status_payload(

                        agent=record["agent"],

                        status=record["status"],

                        message=record["message"],

                        details={"route": route},

                    ),

                )

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

            payload["output"] = call.get("output") or {}

            if call.get("call_id"):

                payload["call_id"] = call["call_id"]

            if call.get("error"):

                payload["error"] = call["error"]

            yield format_sse(

                build_stream_event(

                    event_type=StreamEventType.TOOL_CALL,

                    thread_id=request.thread_id,

                    run_id=run_id,

                    payload=payload,

                )

            )



        for approval in result.get("approval_requests", []):

            yield format_sse(

                build_stream_event(

                    event_type=StreamEventType.APPROVAL_REQUIRED,

                    thread_id=request.thread_id,

                    run_id=run_id,

                    payload=ApprovalRequiredPayload(

                        approval=ApprovalRequest.model_validate(approval)

                    ).model_dump(mode="json"),

                )

            )



        for candidate in profile_candidates:

            yield format_sse(

                build_stream_event(

                    event_type=StreamEventType.PROFILE_CANDIDATE,

                    thread_id=request.thread_id,

                    run_id=run_id,

                    payload=ProfileCandidatePayload(

                        candidate=ProfileCandidate.model_validate(candidate)

                    ).model_dump(mode="json"),

                )

            )





        for candidate in skill_candidates:

            yield format_sse(

                build_stream_event(

                    event_type=StreamEventType.SKILL_CANDIDATE,

                    thread_id=request.thread_id,

                    run_id=run_id,

                    payload=SkillCandidatePayload(

                        candidate=SkillCandidate.model_validate(candidate)

                    ).model_dump(mode="json"),

                )

            )



        rag_sources = result.get("rag_sources", [])

        rag_no_match_reason = result.get("rag_no_match_reason")

        if rag_sources or rag_no_match_reason:

            yield format_sse(

                build_stream_event(

                    event_type=StreamEventType.RAG_SOURCES,

                    thread_id=request.thread_id,

                    run_id=run_id,

                    payload=RagSourcesPayload(

                        sources=rag_sources,

                        no_match_reason=rag_no_match_reason,

                    ).model_dump(mode="json"),

                )

            )



        reply = result.get("response") or "我已收到你的消息，但当前图没有生成回复。"

        for token in split_tokens(reply):

            token_payload = TokenPayload(text=f"{token} ").model_dump(mode="json")

            yield format_sse(

                build_stream_event(

                    event_type=StreamEventType.TOKEN,

                    thread_id=request.thread_id,

                    run_id=run_id,

                    payload=token_payload,

                )

            )



        metadata: dict[str, Any] = {

            "mock": True,

            "graph": "supervisor_skeleton",

            "route": route,

        }

        if "learning_plan" in result:

            metadata["learning_plan"] = result["learning_plan"]

        if rag_no_match_reason:

            metadata["rag_no_match_reason"] = rag_no_match_reason

        if "mcp_tool_calls" in result:

            metadata["mcp_tool_calls"] = result["mcp_tool_calls"]

        if "approval_requests" in result:

            metadata["approval_requests"] = result["approval_requests"]

        if profile_context:

            metadata["profile_context"] = profile_context

        if skill_context:

            metadata["skill_context"] = skill_context

        if profile_candidates:

            metadata["profile_candidates"] = profile_candidates

        if skill_candidates:

            metadata["skill_candidates"] = skill_candidates



        final_payload = FinalPayload(

            message=reply,

            sources=rag_sources,

            metadata=metadata,

        ).model_dump(mode="json")

        yield format_sse(

            build_stream_event(

                event_type=StreamEventType.FINAL,

                thread_id=request.thread_id,

                run_id=run_id,

                payload=final_payload,

            )

        )

    except Exception as exc:

        error_payload = ErrorResponse(

            code=ErrorCode.INTERNAL_ERROR,

            message="Chat stream failed.",

            details={"reason": str(exc)},

        ).model_dump(mode="json")

        yield format_sse(

            build_stream_event(

                event_type=StreamEventType.ERROR,

                thread_id=request.thread_id,

                run_id=run_id,

                payload=error_payload,

            )

        )





@router.post("/stream")

async def chat_stream(request: ChatStreamRequest) -> StreamingResponse:

    run_id = f"run_{uuid4().hex}"

    return StreamingResponse(

        stream_graph_chat(request, run_id),

        media_type="text/event-stream",

        headers={

            "Cache-Control": "no-cache",

            "X-Accel-Buffering": "no",

        },

    )
