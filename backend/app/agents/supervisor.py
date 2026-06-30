"""Supervisor node and deterministic routing for the first LangGraph skeleton."""

from app.agents.state import AgentRoute, AgentStatusRecord, GraphState

LEARNING_KEYWORDS = (
    "学习",
    "学完",
    "课程",
    "考试",
    "复习",
    "作业",
    "计划太紧",
    "放慢",
    "学习计划",
    "路径",
    "python",
    "后端",
    "编程",
    "study",
    "learn",
    "course",
)
FITNESS_KEYWORDS = (
    "健身",
    "运动",
    "训练",
    "锻炼",
    "减脂",
    "增肌",
    "体重",
    "kg",
    "跑步",
    "力量",
    "肩膀",
    "肩部",
    "膝盖",
    "膝部",
    "腰痛",
    "背痛",
    "workout",
    "fitness",
)
LIFE_KEYWORDS = (
    "天气",
    "日程",
    "提醒",
    "待办",
    "安排今天",
    "查一下",
    "几点",
    "当前时间",
    "现在时间",
    "时区",
    "timezone",
    "current time",
    "convert time",
    "工具",
    "calendar",
    "weather",
    "todo",
)


def classify_route(message: str) -> AgentRoute:
    normalized = message.lower()
    if any(keyword in normalized for keyword in LIFE_KEYWORDS):
        return "life"
    if any(keyword in normalized for keyword in FITNESS_KEYWORDS):
        return "fitness"
    if any(keyword in normalized for keyword in LEARNING_KEYWORDS):
        return "learning"
    return "general"


def supervisor_node(state: GraphState) -> GraphState:
    route = classify_route(state["message"])
    records: list[AgentStatusRecord] = [
        {
            "agent": "supervisor",
            "status": "completed",
            "message": f"Supervisor routed the request to the {route} agent.",
        }
    ]
    return {"route": route, "status_records": records}


def select_next_agent(state: GraphState) -> AgentRoute:
    return state.get("route", "general")
