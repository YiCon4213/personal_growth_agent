"""Life assistant agent node with MCP approval support."""

from app.agents.state import AgentStatusRecord, GraphState, render_profile_context_note, render_skill_context_note
from app.models.schemas import ErrorCode, RiskLevel
from app.services.approval_service import ApprovalService, approval_to_schema
from app.services.mcp_service import MCPServiceError, mcp_tool_to_schema


def life_agent_node(state: GraphState) -> GraphState:
    mcp_service = state.get("mcp_service")
    user_id = state.get("user_id") or "default_user"
    enabled_server_ids = state.get("enabled_mcp_server_ids") or []
    message = state.get("message", "")
    profile_note = render_profile_context_note(state) + render_skill_context_note(state)

    if mcp_service is None or not enabled_server_ids:
        records: list[AgentStatusRecord] = [
            {
                "agent": "life",
                "status": "completed",
                "message": "Life assistant agent produced a minimal tool-planning response.",
            }
        ]
        return {
            "response": (
                "生活助手 Agent 已接手。当前没有启用的 MCP server，"
                "我会先按普通生活规划方式回应；如需调用工具，请在请求中传入 enabled_mcp_server_ids。"
            ) + profile_note,
            "status_records": records,
        }

    try:
        selected = mcp_service.select_tool(
            user_id,
            message,
            history=state.get("history") or [],
            server_ids=list(enabled_server_ids),
        )
        if selected is None:
            return {
                "response": "生活助手 Agent 已接手，但LLM 判断当前请求不需要调用已启用的 MCP 工具。" + profile_note,
                "status_records": [
                    {
                        "agent": "life",
                        "status": "completed",
                        "message": "LLM selected no MCP tool.",
                    }
                ],
            }
        tool, server, arguments = selected
        tool_payload = mcp_tool_to_schema(tool, server).model_dump(mode="json")

        if tool.risk_level != RiskLevel.LOW.value:
            approval = ApprovalService(mcp_service.session, mcp_service=mcp_service).create_for_tool_call(
                user_id=user_id,
                thread_id=state.get("thread_id") or "unknown",
                tool_id=tool.id,
                arguments=arguments,
            )
            return {
                "response": (
                    f"生活助手 Agent 已暂停。高风险 MCP 工具 {tool.name} 需要用户审批后才会执行。"
                ) + profile_note,
                "approval_requests": [approval_to_schema(approval).model_dump(mode="json")],
                "mcp_tool_calls": [
                    {
                        "tool": tool_payload,
                        "arguments": arguments,
                        "output": {},
                        "status": "waiting_approval",
                    }
                ],
                "status_records": [
                    {
                        "agent": "life",
                        "status": "waiting_approval",
                        "message": f"MCP tool {tool.name} is waiting for approval.",
                    }
                ],
            }

        tool, server, output, call_id = mcp_service.call_tool(
            user_id,
            tool.id,
            arguments,
            thread_id=state.get("thread_id"),
        )
        return {
            "response": (
                f"生活助手 Agent 已调用低风险 MCP 工具 {tool.name}。"
                f"工具返回：{output}"
            ) + profile_note,
            "mcp_tool_calls": [
                {
                    "call_id": call_id,
                    "tool": tool_payload,
                    "arguments": arguments,
                    "output": output,
                    "status": "succeeded",
                }
            ],
            "status_records": [
                {
                    "agent": "life",
                    "status": "completed",
                    "message": f"Called low-risk MCP tool {tool.name}.",
                }
            ],
        }
    except MCPServiceError as exc:
        status = "waiting_approval" if exc.code == ErrorCode.APPROVAL_REQUIRED else "failed"
        return {
            "response": f"生活助手 Agent 调用 MCP 工具失败：{exc.message}" + profile_note,
            "mcp_tool_calls": [
                {
                    "status": "failed",
                    "error": exc.to_error_response().model_dump(mode="json"),
                }
            ],
            "status_records": [
                {
                    "agent": "life",
                    "status": status,
                    "message": exc.message,
                }
            ],
        }
