"""Minimal general conversation agent node."""

from app.agents.state import AgentStatusRecord, GraphState, render_profile_context_note, render_skill_context_note


def general_agent_node(state: GraphState) -> GraphState:
    records: list[AgentStatusRecord] = [
        {
            "agent": "supervisor",
            "status": "completed",
            "message": "Supervisor handled the request as a general conversation.",
        }
    ]
    return {
        "response": "我已收到你的消息。当前 LangGraph 骨架会先完成路由，普通对话先返回最小可用回复。" + render_profile_context_note(state) + render_skill_context_note(state),
        "status_records": records,
    }
