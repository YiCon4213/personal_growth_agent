import json

from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.db.models import Base
from app.main import create_app
from app.services.llm_service import FakeLLMService
from app.services.embedding_service import FakeEmbeddingProvider


def build_test_client(session_factory=None, llm_service=None) -> TestClient:
    if session_factory is None:
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

    app = create_app(llm_service=llm_service or FakeLLMService(), embedding_provider=FakeEmbeddingProvider())
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)

def parse_sse_events(body: str) -> list[dict]:
    events = []
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


def test_chat_stream_returns_structured_sse_events() -> None:
    client = build_test_client()

    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={"message": "帮我规划 Python 学习", "thread_id": "thread_test"},
    ) as response:
        body = response.read().decode()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = parse_sse_events(body)
    event_names = [event["event_name"] for event in events]

    assert event_names[0] == "agent_status"
    assert "token" in event_names
    assert event_names[-1] == "final"

    run_ids = {event["data"]["run_id"] for event in events}
    assert len(run_ids) == 1
    for event in events:
        data = event["data"]
        assert data["event"] == event["event_name"]
        assert data["thread_id"] == "thread_test"
        assert data["run_id"].startswith("run_")
        assert "timestamp" in data
        assert isinstance(data["payload"], dict)

    status_agents = [
        event["data"]["payload"]["agent"]
        for event in events
        if event["event_name"] == "agent_status"
    ]
    final_metadata = events[-1]["data"]["payload"]["metadata"]
    assert "supervisor" in status_agents
    assert "learning" in status_agents
    assert final_metadata["route"] == "learning"
    assert "mock" not in final_metadata
    assert final_metadata["learning_plan"]["goal"] == "Python 编程"
    assert final_metadata["learning_plan"]["weekly_plan"]


def test_chat_stream_returns_error_event_for_stream_failure() -> None:
    client = build_test_client()

    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={"message": "__trigger_error__", "thread_id": "thread_error"},
    ) as response:
        body = response.read().decode()

    assert response.status_code == 200

    events = parse_sse_events(body)
    assert events[-1]["event_name"] == "error"
    error_data = events[-1]["data"]
    assert error_data["event"] == "error"
    assert error_data["thread_id"] == "thread_error"
    assert error_data["payload"]["code"] == "internal_error"
    assert error_data["payload"]["message"] == "Chat stream failed."


def test_chat_stream_validation_error_is_sse_error_event() -> None:
    client = build_test_client()

    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={"message": "", "thread_id": "thread_validation"},
    ) as response:
        body = response.read().decode()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = parse_sse_events(body)
    assert len(events) == 1
    assert events[0]["event_name"] == "error"
    error_data = events[0]["data"]
    assert error_data["event"] == "error"
    assert error_data["thread_id"] == "thread_validation"
    assert error_data["payload"]["code"] == "validation_error"
    assert error_data["payload"]["message"] == "Chat stream request validation failed."


def test_chat_stream_exposes_fitness_route_status() -> None:
    client = build_test_client()

    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={"message": "我想做减脂训练", "thread_id": "thread_fitness"},
    ) as response:
        body = response.read().decode()

    events = parse_sse_events(body)
    status_agents = [
        event["data"]["payload"]["agent"]
        for event in events
        if event["event_name"] == "agent_status"
    ]
    assert "fitness" in status_agents
    assert events[-1]["data"]["payload"]["metadata"]["route"] == "fitness"
    assert events[-1]["data"]["payload"]["sources"] == []
    assert "证据不足" in events[-1]["data"]["payload"]["message"]
    assert "[1]" not in events[-1]["data"]["payload"]["message"]


def test_chat_stream_returns_adjusted_learning_plan() -> None:
    client = build_test_client()

    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={"message": "计划太紧，帮我放慢", "thread_id": "thread_adjust"},
    ) as response:
        body = response.read().decode()

    events = parse_sse_events(body)
    final_payload = events[-1]["data"]["payload"]
    learning_plan = final_payload["metadata"]["learning_plan"]

    assert final_payload["metadata"]["route"] == "learning"
    assert learning_plan["pace"] == "relaxed"
    assert learning_plan["total_weeks"] >= 16
    assert "宽松节奏" in learning_plan["adjustment_advice"]



def test_chat_stream_emits_approval_required_event(monkeypatch) -> None:
    import app.api.v1.chat as chat_module

    def fake_run_supervisor_graph(**kwargs):
        return {
            "route": "life",
            "response": "生活助手 Agent 已暂停。高风险 MCP 工具 email.send 需要用户审批后才会执行。",
            "status_records": [
                {
                    "agent": "life",
                    "status": "waiting_approval",
                    "message": "MCP tool email.send is waiting for approval.",
                }
            ],
            "approval_requests": [
                {
                    "id": "approval_1",
                    "user_id": "default_user",
                    "thread_id": "thread_approval",
                    "tool_id": "tool_1",
                    "server_id": "server_1",
                    "tool_name": "email.send",
                    "arguments": {"text": "hello"},
                    "risk_level": "high",
                    "expected_impact": "Send an external email message.",
                    "status": "pending",
                    "created_at": "2026-06-26T00:00:00Z",
                    "decided_at": None,
                    "executed_at": None,
                    "tool_call_id": None,
                    "execution_result": {},
                    "error_message": None,
                }
            ],
        }

    monkeypatch.setattr(chat_module, "run_supervisor_graph", fake_run_supervisor_graph)
    client = build_test_client()

    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={"message": "请发邮件", "thread_id": "thread_approval"},
    ) as response:
        body = response.read().decode()

    events = parse_sse_events(body)
    event_names = [event["event_name"] for event in events]
    assert "approval_required" in event_names
    approval_event = next(event for event in events if event["event_name"] == "approval_required")
    approval = approval_event["data"]["payload"]["approval"]
    assert approval["id"] == "approval_1"
    assert approval["tool_name"] == "email.send"
    assert approval["status"] == "pending"
    assert events[-1]["data"]["payload"]["metadata"]["approval_requests"][0]["id"] == "approval_1"

def test_chat_stream_emits_profile_candidate_and_uses_approved_profile(monkeypatch) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.api.v1.chat as chat_module
    from app.db.models import Base
    from app.services.profile_service import ProfileService

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    client = build_test_client(session_factory)
    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={
            "message": "我每天晚上 9 点后学习效率高，请记住。",
            "thread_id": "thread_profile",
            "user_id": "default_user",
        },
    ) as response:
        body = response.read().decode()

    events = parse_sse_events(body)
    candidate_event = next(event for event in events if event["event_name"] == "profile_candidate")
    candidate = candidate_event["data"]["payload"]["candidate"]
    assert candidate["status"] == "pending"
    assert "晚上9点后学习效率高" in candidate["content"]
    assert events[-1]["data"]["payload"]["metadata"]["profile_candidates"][0]["id"] == candidate["id"]

    with session_factory() as session:
        service = ProfileService(session)
        service.approve_candidate(candidate["id"], user_id="default_user")
        session.commit()

    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={
            "message": "帮我规划 Python 学习",
            "thread_id": "thread_profile_2",
            "user_id": "default_user",
        },
    ) as response:
        second_body = response.read().decode()

    second_events = parse_sse_events(second_body)
    final_payload = second_events[-1]["data"]["payload"]
    assert final_payload["metadata"]["profile_context"][0]["content"] == candidate["content"]



def test_chat_stream_emits_skill_candidate_after_ten_turns_and_uses_approved_skill(monkeypatch) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.api.v1.chat as chat_module
    from app.db.models import Base
    from app.services.skill_service import SkillService

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    client = build_test_client(session_factory)
    candidate = None
    for index in range(1, 11):
        with client.stream(
            "POST",
            "/api/v1/chat/stream",
            json={
                "message": f"第 {index} 轮：我想学习 Python 后端，请一步步安排。",
                "thread_id": "thread_skill",
                "user_id": "default_user",
            },
        ) as response:
            body = response.read().decode()
        events = parse_sse_events(body)
        skill_events = [event for event in events if event["event_name"] == "skill_candidate"]
        if index < 10:
            assert skill_events == []
        else:
            assert len(skill_events) == 1
            candidate = skill_events[0]["data"]["payload"]["candidate"]
            assert candidate["status"] == "pending"
            assert "常用计划模板" in candidate["content"]
            assert events[-1]["data"]["payload"]["metadata"]["skill_candidates"][0]["id"] == candidate["id"]

    assert candidate is not None
    with session_factory() as session:
        service = SkillService(session)
        service.approve_candidate(candidate["id"], user_id="default_user")
        session.commit()

    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={
            "message": "帮我规划 Python 学习",
            "thread_id": "thread_skill_next",
            "user_id": "default_user",
        },
    ) as response:
        second_body = response.read().decode()

    second_events = parse_sse_events(second_body)
    final_payload = second_events[-1]["data"]["payload"]
    assert final_payload["metadata"]["skill_context"][0]["id"]
