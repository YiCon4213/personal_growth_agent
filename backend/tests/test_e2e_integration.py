import json
from collections.abc import Generator
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.agents.fitness as fitness_module
import app.api.v1.chat as chat_module
import app.services.mcp_service as mcp_service_module
from app.core.database import get_session
from app.db.models import Base, MCPServer
from app.main import create_app


class FakeMCPTransport:
    def __init__(self) -> None:
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
        self.calls.append((tool_name, arguments))
        if tool_name == "weather.lookup":
            return {"content": [{"type": "text", "text": "晴，适合安排户外散步。"}]}
        return {"content": [{"type": "text", "text": "邮件已发送。"}]}


def parse_sse_events(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        event_line = next(line for line in lines if line.startswith("event: "))
        data_line = next(line for line in lines if line.startswith("data: "))
        events.append(
            {
                "event_name": event_line.removeprefix("event: "),
                "data": json.loads(data_line.removeprefix("data: ")),
            }
        )
    return events


def stream_chat(client: TestClient, payload: dict[str, Any]) -> list[dict[str, Any]]:
    with client.stream("POST", "/api/v1/chat/stream", json=payload) as response:
        body = response.read().decode()
    assert response.status_code == 200
    return parse_sse_events(body)


def build_e2e_client(monkeypatch) -> tuple[TestClient, FakeMCPTransport]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def override_get_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    fake_transport = FakeMCPTransport()
    monkeypatch.setattr(chat_module, "create_session_factory", lambda: session_factory)
    monkeypatch.setattr(fitness_module, "create_session_factory", lambda: session_factory)
    monkeypatch.setattr(
        mcp_service_module,
        "JSONRPCMCPTransportClient",
        lambda: fake_transport,
    )

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), fake_transport


def test_end_to_end_core_flows_share_one_app_and_database(monkeypatch) -> None:
    client, fake_transport = build_e2e_client(monkeypatch)
    user_id = "e2e_user"

    learning_events = stream_chat(
        client,
        {
            "user_id": user_id,
            "thread_id": "e2e_learning",
            "message": "我想 3 个月学完 Python 后端，每天 2 小时",
        },
    )
    learning_final = learning_events[-1]["data"]["payload"]
    assert learning_final["metadata"]["route"] == "learning"
    assert learning_final["metadata"]["learning_plan"]["weekly_plan"]

    document_response = client.post(
        "/api/v1/rag/documents",
        json={
            "user_id": user_id,
            "title": "减脂训练指南",
            "content": "减脂训练建议结合力量训练和有氧训练。动作标准优先。",
            "source_uri": "fitness.md",
            "source_type": "markdown",
        },
    )
    assert document_response.status_code == 200

    fitness_events = stream_chat(
        client,
        {"user_id": user_id, "thread_id": "e2e_fitness", "message": "我想做减脂力量训练"},
    )
    assert any(event["event_name"] == "rag_sources" for event in fitness_events)
    fitness_final = fitness_events[-1]["data"]["payload"]
    assert fitness_final["metadata"]["route"] == "fitness"
    assert fitness_final["sources"][0]["title"] == "减脂训练指南"

    server_response = client.post(
        "/api/v1/mcp/servers",
        json={
            "user_id": user_id,
            "name": "life-tools",
            "endpoint_url": "https://mcp.example.test/rpc",
            "transport": "http",
        },
    )
    assert server_response.status_code == 200
    server_id = server_response.json()["id"]
    refresh_response = client.post(f"/api/v1/mcp/servers/{server_id}/refresh-tools", params={"user_id": user_id})
    assert refresh_response.status_code == 200

    low_risk_events = stream_chat(
        client,
        {
            "user_id": user_id,
            "thread_id": "e2e_mcp_low",
            "message": "帮我查天气并安排今天",
            "enabled_mcp_server_ids": [server_id],
        },
    )
    tool_event = next(event for event in low_risk_events if event["event_name"] == "tool_call")
    assert tool_event["data"]["payload"]["tool_name"] == "weather.lookup"
    assert fake_transport.calls[-1][0] == "weather.lookup"

    high_risk_events = stream_chat(
        client,
        {
            "user_id": user_id,
            "thread_id": "e2e_mcp_high",
            "message": "帮我用 email.send 发送提醒",
            "enabled_mcp_server_ids": [server_id],
        },
    )
    approval_event = next(event for event in high_risk_events if event["event_name"] == "approval_required")
    approval = approval_event["data"]["payload"]["approval"]
    assert approval["status"] == "pending"
    assert approval["tool_name"] == "email.send"
    assert fake_transport.calls[-1][0] == "weather.lookup"

    approve_response = client.post(
        f"/api/v1/approvals/{approval['id']}/approve",
        json={"user_id": user_id, "approver_id": user_id},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["approval"]["status"] == "executed"
    assert fake_transport.calls[-1][0] == "email.send"

    profile_events = stream_chat(
        client,
        {
            "user_id": user_id,
            "thread_id": "e2e_profile",
            "message": "我每天晚上 9 点后学习效率高，请记住。",
        },
    )
    profile_candidate = next(
        event for event in profile_events if event["event_name"] == "profile_candidate"
    )["data"]["payload"]["candidate"]
    approve_profile = client.post(
        f"/api/v1/profile/candidates/{profile_candidate['id']}/approve",
        json={"user_id": user_id},
    )
    assert approve_profile.status_code == 200

    profile_context_events = stream_chat(
        client,
        {"user_id": user_id, "thread_id": "e2e_profile_next", "message": "帮我规划 Python 学习"},
    )
    assert profile_context_events[-1]["data"]["payload"]["metadata"]["profile_context"]

    skill_candidate = None
    for index in range(1, 11):
        skill_events = stream_chat(
            client,
            {
                "user_id": user_id,
                "thread_id": "e2e_skill",
                "message": f"第 {index} 轮：我想学习 Python 后端，请一步步安排。",
            },
        )
        candidates = [event for event in skill_events if event["event_name"] == "skill_candidate"]
        if candidates:
            skill_candidate = candidates[0]["data"]["payload"]["candidate"]
    assert skill_candidate is not None

    approve_skill = client.post(
        f"/api/v1/skills/candidates/{skill_candidate['id']}/approve",
        json={"user_id": user_id},
    )
    assert approve_skill.status_code == 200

    skill_context_events = stream_chat(
        client,
        {"user_id": user_id, "thread_id": "e2e_skill_next", "message": "继续帮我规划 Python 学习"},
    )
    assert skill_context_events[-1]["data"]["payload"]["metadata"]["skill_context"]
