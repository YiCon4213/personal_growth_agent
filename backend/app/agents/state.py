"""LangGraph state definitions for the supervisor skeleton."""



from operator import add

from typing import Annotated, Any, Literal, TypedDict



from app.models.schemas import RagSource



AgentRoute = Literal["learning", "fitness", "life", "general"]





class AgentStatusRecord(TypedDict):

    agent: str

    status: str

    message: str





class GraphState(TypedDict, total=False):

    message: str

    thread_id: str

    user_id: str | None

    run_id: str

    route: AgentRoute

    response: str

    learning_plan: dict[str, Any]

    rag_collection_ids: list[str]

    rag_sources: list[RagSource]

    rag_no_match_reason: str | None

    rag_service: Any

    enabled_mcp_server_ids: list[str]

    mcp_service: Any

    mcp_tool_calls: list[dict[str, Any]]

    approval_requests: list[dict[str, Any]]

    profile_context: list[dict[str, Any]]
    skill_context: list[dict[str, Any]]
    status_records: Annotated[list[AgentStatusRecord], add]



def render_profile_context_note(state: GraphState) -> str:
    context = state.get("profile_context") or []
    if not context:
        return ""
    snippets = []
    for item in context[:3]:
        category = item.get("category", "profile")
        content = item.get("content", "")
        if content:
            snippets.append(f"{category}: {content}")
    if not snippets:
        return ""
    return "\n\n已参考已确认画像：" + "；".join(snippets)

def render_skill_context_note(state: GraphState) -> str:
    context = state.get("skill_context") or []
    if not context:
        return ""
    snippets = []
    for item in context[:2]:
        title = item.get("title", "Skill")
        content = item.get("content", "")
        if content:
            first_line = str(content).splitlines()[0]
            snippets.append(f"{title}: {first_line}")
    if not snippets:
        return ""
    return "\n\n已参考已启用 Skill：" + "；".join(snippets)
