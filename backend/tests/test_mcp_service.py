from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.graph import run_supervisor_graph
from app.db.models import Base, MCPServer
from app.models.schemas import ErrorCode, MCPTransport, RiskLevel
from app.services.approval_service import ApprovalService
from app.services.data_store import DataStore
from app.services.mcp_service import MCPService, MCPServiceError


class FakeMCPTransport:
    def __init__(self, *, fail_call: bool = False) -> None:
        self.fail_call = fail_call
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_tools(self, server: MCPServer, *, timeout_seconds: float = 10) -> list[dict[str, Any]]:
        return [
            {
                "name": "weather.lookup",
                "description": "Look up current weather for a location.",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
            {
                "name": "email.send",
                "description": "Send an email message.",
                "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
            },
        ]

    def call_tool(
        self,
        server: MCPServer,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float = 10,
    ) -> dict[str, Any]:
        if self.fail_call:
            raise MCPServiceError(
                ErrorCode.EXTERNAL_SERVICE_ERROR,
                "MCP server request timed out.",
                {"server_id": server.id},
            )
        self.calls.append((tool_name, arguments))
        return {"content": [{"type": "text", "text": "晴，适合安排户外散步。"}]}


@pytest.fixture()
def store() -> DataStore:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return DataStore(session_factory())


def test_mcp_service_refreshes_tools_and_records_risk(store: DataStore) -> None:
    server = store.create_mcp_server(
        "user_1",
        "life-tools",
        "https://mcp.example.test/rpc",
        transport=MCPTransport.HTTP,
    )
    service = MCPService(store.session, transport_client=FakeMCPTransport())

    tools = service.refresh_tools("user_1", server.id)

    assert [tool.name for tool in tools] == ["weather.lookup", "email.send"]
    assert tools[0].risk_level == RiskLevel.LOW.value
    assert tools[1].risk_level == RiskLevel.HIGH.value
    assert store.list_mcp_tools("user_1")[0].input_schema["properties"]["query"]["type"] == "string"


def test_mcp_service_calls_low_risk_tool_and_records_output(store: DataStore) -> None:
    server = store.create_mcp_server("user_1", "life-tools", "https://mcp.example.test/rpc")
    fake_transport = FakeMCPTransport()
    service = MCPService(store.session, transport_client=fake_transport)
    tool = service.refresh_tools("user_1", server.id)[0]

    called_tool, _, output, call_id = service.call_tool(
        "user_1",
        tool.id,
        {"query": "查天气"},
        thread_id="thread_1",
    )

    assert called_tool.name == "weather.lookup"
    assert output["content"][0]["text"] == "晴，适合安排户外散步。"
    assert call_id
    assert fake_transport.calls == [("weather.lookup", {"query": "查天气"})]


def test_mcp_service_blocks_non_low_risk_tool_until_approval_task(store: DataStore) -> None:
    server = store.create_mcp_server("user_1", "life-tools", "https://mcp.example.test/rpc")
    service = MCPService(store.session, transport_client=FakeMCPTransport())
    high_risk_tool = service.refresh_tools("user_1", server.id)[1]

    with pytest.raises(MCPServiceError) as exc_info:
        service.call_tool("user_1", high_risk_tool.id, {"text": "hello"})

    assert exc_info.value.code == ErrorCode.APPROVAL_REQUIRED


def test_life_agent_can_call_enabled_low_risk_mcp_tool(store: DataStore) -> None:
    server = store.create_mcp_server("default_user", "life-tools", "https://mcp.example.test/rpc")
    service = MCPService(store.session, transport_client=FakeMCPTransport())
    service.refresh_tools("default_user", server.id)

    result = run_supervisor_graph(
        message="帮我查天气并安排今天",
        thread_id="thread_life_mcp",
        run_id="run_test",
        user_id="default_user",
        enabled_mcp_server_ids=[server.id],
        mcp_service=service,
    )

    assert result["route"] == "life"
    assert result["mcp_tool_calls"][0]["status"] == "succeeded"
    assert result["mcp_tool_calls"][0]["tool"]["name"] == "weather.lookup"
    assert "工具返回" in result["response"]


def test_high_risk_tool_creates_approval_without_execution(store: DataStore) -> None:
    server = store.create_mcp_server("default_user", "life-tools", "https://mcp.example.test/rpc")
    fake_transport = FakeMCPTransport()
    service = MCPService(store.session, transport_client=fake_transport)
    service.refresh_tools("default_user", server.id)

    result = run_supervisor_graph(
        message="帮我用 email.send 发送生活提醒消息",
        thread_id="thread_approval",
        run_id="run_test",
        user_id="default_user",
        enabled_mcp_server_ids=[server.id],
        mcp_service=service,
    )

    assert result["route"] == "life"
    assert result["approval_requests"][0]["status"] == "pending"
    assert result["approval_requests"][0]["tool_name"] == "email.send"
    assert result["mcp_tool_calls"][0]["status"] == "waiting_approval"
    assert fake_transport.calls == []


def test_approval_reject_does_not_execute_tool(store: DataStore) -> None:
    server = store.create_mcp_server("user_1", "life-tools", "https://mcp.example.test/rpc")
    fake_transport = FakeMCPTransport()
    mcp_service = MCPService(store.session, transport_client=fake_transport)
    high_risk_tool = mcp_service.refresh_tools("user_1", server.id)[1]
    approval_service = ApprovalService(store.session, mcp_service=mcp_service)
    approval = approval_service.create_for_tool_call(
        user_id="user_1",
        thread_id="thread_1",
        tool_id=high_risk_tool.id,
        arguments={"text": "hello"},
    )

    rejected = approval_service.reject(approval.id, user_id="user_1", reason="Not now")

    assert rejected.status == "rejected"
    assert fake_transport.calls == []


def test_approval_approve_executes_original_tool(store: DataStore) -> None:
    server = store.create_mcp_server("user_1", "life-tools", "https://mcp.example.test/rpc")
    fake_transport = FakeMCPTransport()
    mcp_service = MCPService(store.session, transport_client=fake_transport)
    high_risk_tool = mcp_service.refresh_tools("user_1", server.id)[1]
    approval_service = ApprovalService(store.session, mcp_service=mcp_service)
    approval = approval_service.create_for_tool_call(
        user_id="user_1",
        thread_id="thread_1",
        tool_id=high_risk_tool.id,
        arguments={"text": "hello"},
    )

    executed, tool_call = approval_service.approve(approval.id, user_id="user_1")

    assert executed.status == "executed"
    assert executed.tool_call_id == tool_call.call_id
    assert tool_call.tool.name == "email.send"
    assert fake_transport.calls == [("email.send", {"text": "hello"})]
