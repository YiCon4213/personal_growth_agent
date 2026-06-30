import json
from collections.abc import AsyncIterator, Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.db.models import Base
from app.main import create_app
from app.services.llm_service import FakeLLMService, LLMServiceError


def parse_events(body: str) -> list[dict[str, Any]]:
    return [
        json.loads(next(line for line in block.splitlines() if line.startswith("data: "))[6:])
        for block in body.strip().split("\n\n")
    ]


def build_client(llm_service=None) -> tuple[TestClient, FakeLLMService]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def override_get_session() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    fake = llm_service or FakeLLMService()
    app = create_app(llm_service=fake)
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), fake


def stream(client: TestClient, thread_id: str, message: str) -> list[dict[str, Any]]:
    with client.stream(
        "POST", "/api/v1/chat/stream", json={"thread_id": thread_id, "message": message}
    ) as response:
        assert response.status_code == 200
        return parse_events(response.read().decode())


def test_conversation_crud_history_and_context_isolation() -> None:
    client, fake = build_client()
    first = client.post("/api/v1/conversations", json={"title": "第一段对话"})
    second = client.post("/api/v1/conversations", json={})
    assert first.status_code == 201
    assert second.status_code == 201
    first_id = first.json()["id"]
    second_id = second.json()["id"]

    stream(client, first_id, "我的代号是松鼠")
    second_turn = stream(client, first_id, "我的代号是什么？")
    assert "我的代号是松鼠" in second_turn[-1]["payload"]["message"]

    isolated = stream(client, second_id, "我的代号是什么？")
    assert "我的代号是松鼠" not in isolated[-1]["payload"]["message"]
    assert len(fake.calls[-1]) == 1

    detail = client.get(f"/api/v1/conversations/{first_id}")
    assert detail.status_code == 200
    assert [item["role"] for item in detail.json()["messages"]] == [
        "user", "assistant", "user", "assistant"
    ]

    renamed = client.patch(
        f"/api/v1/conversations/{first_id}", json={"title": "松鼠计划"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "松鼠计划"
    listed = client.get("/api/v1/conversations").json()
    assert {item["id"] for item in listed} == {first_id, second_id}

    deleted = client.delete(f"/api/v1/conversations/{first_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/conversations/{first_id}").status_code == 404


class FailingLLM:
    def __init__(self, kind: str) -> None:
        self.kind = kind

    async def complete_structured(self, messages, response_model, *, system_prompt):
        raise LLMServiceError("结构化请求失败", kind=self.kind)

    async def stream_text(self, messages, *, system_prompt) -> AsyncIterator[str]:
        raise LLMServiceError(f"可理解的 {self.kind} 错误", kind=self.kind)
        yield ""


@pytest.mark.parametrize("kind", ["timeout", "rate_limit", "authentication", "network"])
def test_llm_failures_are_understandable_sse_errors(kind: str) -> None:
    client, _ = build_client(FailingLLM(kind))
    conversation = client.post("/api/v1/conversations", json={}).json()
    events = stream(client, conversation["id"], "你好")
    assert events[-1]["event"] == "error"
    assert events[-1]["payload"]["code"] == "external_service_error"
    assert events[-1]["payload"]["details"]["kind"] == kind
    assert kind in events[-1]["payload"]["message"]