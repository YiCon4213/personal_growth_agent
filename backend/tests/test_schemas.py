from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.models.schemas import (
    ChatStreamRequest,
    ErrorCode,
    ErrorResponse,
    StreamEvent,
    StreamEventType,
)


def test_chat_stream_request_keeps_compatible_fields() -> None:
    request = ChatStreamRequest(
        message="Help me plan a 3-month backend learning path.",
        thread_id="thread_123",
        image_url="https://example.com/image.png",
    )

    assert request.message.startswith("Help me")
    assert request.thread_id == "thread_123"
    assert str(request.image_url) == "https://example.com/image.png"
    assert request.attachments == []
    assert request.enabled_mcp_server_ids == []
    assert request.rag_collection_ids == []


def test_chat_stream_request_rejects_empty_message() -> None:
    with pytest.raises(ValidationError):
        ChatStreamRequest(message="", thread_id="thread_123")


def test_stream_event_has_required_contract_fields() -> None:
    event = StreamEvent(
        event=StreamEventType.ERROR,
        thread_id="thread_123",
        run_id="run_456",
        timestamp=datetime.now(UTC),
        payload=ErrorResponse(
            code=ErrorCode.INTERNAL_ERROR,
            message="Unexpected error.",
        ).model_dump(mode="json"),
    )

    dumped = event.model_dump(mode="json")
    assert dumped["event"] == "error"
    assert dumped["thread_id"] == "thread_123"
    assert dumped["run_id"] == "run_456"
    assert "timestamp" in dumped
    assert dumped["payload"]["code"] == "internal_error"


def test_schema_models_are_visible_in_openapi() -> None:
    client = TestClient(create_app())

    response = client.get("/openapi.json")

    assert response.status_code == 200
    schemas = response.json()["components"]["schemas"]
    for schema_name in [
        "ChatStreamRequest",
        "StreamEvent",
        "AgentStatusPayload",
        "RagSource",
        "MCPTool",
        "ApprovalRequest",
        "ProfileCandidate",
        "SkillCandidate",
        "ErrorResponse",
    ]:
        assert schema_name in schemas
