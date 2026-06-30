"""Fitness guidance agent node with optional RAG support."""

from sqlalchemy.exc import SQLAlchemyError

from app.agents.state import (
    AgentStatusRecord,
    GraphState,
    render_profile_context_note,
    render_skill_context_note,
)
from app.core.database import DatabaseConfigurationError, create_session_factory
from app.models.schemas import RagSource
from app.services.rag_service import FitnessRagService, RagSearchResult

RISK_KEYWORDS = [
    "伤",
    "痛",
    "病",
    "膝盖",
    "腰",
    "心脏",
    "疾病",
    "极端",
    "补剂",
    "药",
    "骨折",
]


def fitness_agent_node(state: GraphState) -> GraphState:
    message = state.get("message", "")
    user_id = state.get("user_id") or "default_user"
    if state.get("user_id") is None and state.get("rag_service") is None and not state.get("rag_collection_ids"):
        rag_result = RagSearchResult(
            sources=[],
            no_match_reason="RAG search skipped because user_id was not provided.",
        )
    else:
        rag_result = search_fitness_knowledge(state, user_id=user_id, query=message)
    sources = rag_result.sources
    no_match_reason = rag_result.no_match_reason

    records: list[AgentStatusRecord] = [
        {
            "agent": "fitness",
            "status": "completed",
            "message": fitness_status_message(sources, no_match_reason),
        }
    ]
    return {
        "response": build_fitness_response(message, sources, no_match_reason)
        + render_profile_context_note(state)
        + render_skill_context_note(state),
        "rag_sources": sources,
        "rag_no_match_reason": no_match_reason,
        "status_records": records,
    }


def search_fitness_knowledge(state: GraphState, *, user_id: str, query: str) -> RagSearchResult:
    injected_service = state.get("rag_service")
    if injected_service is not None:
        return injected_service.search(
            user_id=user_id,
            query=query,
            document_ids=state.get("rag_collection_ids") or None,
            top_k=3,
            min_relevance=0.05,
        )

    try:
        session_factory = create_session_factory()
    except DatabaseConfigurationError as exc:
        return RagSearchResult(sources=[], no_match_reason=str(exc))

    try:
        with session_factory() as session:
            service = FitnessRagService(session)
            return service.search(
                user_id=user_id,
                query=query,
                document_ids=state.get("rag_collection_ids") or None,
                top_k=3,
                min_relevance=0.05,
            )
    except SQLAlchemyError as exc:
        return RagSearchResult(
            sources=[],
            no_match_reason=f"RAG database search failed: {exc.__class__.__name__}",
        )


def fitness_status_message(sources: list[RagSource], no_match_reason: str | None) -> str:
    if sources:
        return f"Fitness agent retrieved {len(sources)} RAG source(s)."
    if no_match_reason:
        return "Fitness agent found no matching RAG source and returned a cautious response."
    return "Fitness agent produced a cautious response."


def build_fitness_response(
    message: str,
    sources: list[RagSource],
    no_match_reason: str | None,
) -> str:
    safety_note = build_safety_note(message)
    if sources:
        source_lines = [
            f"[{index}] {source.title}: {compact_excerpt(source.excerpt)}"
            for index, source in enumerate(sources, start=1)
        ]
        return (
            "健身指导 Agent 已结合知识库给出建议。\n\n"
            "知识库依据：\n"
            + "\n".join(source_lines)
            + "\n\n模型推理建议：先把训练目标拆成可恢复、可持续的小周期，"
            "优先保证动作标准和逐步加量，再根据疲劳程度调整训练量。"
            f"{safety_note}"
        )
    reason = no_match_reason or "No matching fitness knowledge chunks were found."
    return (
        "健身指导 Agent 已接手，但当前没有可引用的知识库依据。\n\n"
        f"知识库依据：未找到匹配片段（{reason}）。\n\n"
        "模型推理建议：可以先采用保守的全身训练安排，例如每周 3 次力量训练，"
        "每次覆盖深蹲/髋 hinge/推/拉/核心，强度控制在还剩 2-3 次余力的范围。"
        f"{safety_note}"
    )


def compact_excerpt(excerpt: str, limit: int = 140) -> str:
    normalized = " ".join(excerpt.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def build_safety_note(message: str) -> str:
    if any(keyword in message for keyword in RISK_KEYWORDS):
        return (
            "\n\n安全边界：你提到了可能涉及伤病、疼痛、疾病、补剂或高风险训练的信息；"
            "这里的建议不能替代医生或康复专业人士判断，出现疼痛或异常反应应停止并寻求专业意见。"
        )
    return "\n\n安全边界：如训练中出现疼痛、头晕、胸闷或异常不适，应停止训练并咨询专业人士。"
