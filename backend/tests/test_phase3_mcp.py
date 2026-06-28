import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.graph import run_supervisor_graph
from app.core.config import Settings
from app.db.models import Base, MCPServer
from app.models.schemas import ErrorCode, MCPServerCreateRequest, MCPTransport
from app.services.data_store import DataStore
from app.services.llm_service import FakeLLMService
from app.services.mcp_service import (
    MCPService,
    MCPServiceError,
    OfficialMCPTransportClient,
)


@pytest.fixture()
def store() -> DataStore:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return DataStore(factory())


def time_server(store: DataStore) -> tuple[MCPServer, Settings]:
    settings = Settings(
        mcp_stdio_allowed_commands="python",
        mcp_timeout_seconds=15,
    )
    script = Path(__file__).parent / "fixtures" / "fake_mcp_time_server.py"
    server = store.create_mcp_server(
        "default_user",
        "time",
        "",
        transport=MCPTransport.STDIO,
        command=sys.executable,
        args=[str(script)],
    )
    return server, settings


def test_official_stdio_lifecycle_and_time_tool_selection(store: DataStore) -> None:
    server, settings = time_server(store)
    service = MCPService(
        store.session,
        transport_client=OfficialMCPTransportClient(settings),
        llm_service=FakeLLMService(),
        settings=settings,
    )

    tools = service.refresh_tools("default_user", server.id)
    assert {tool.name for tool in tools} == {"get_current_time", "convert_time"}

    result = run_supervisor_graph(
        message="请告诉我现在 Asia/Shanghai 是几点",
        thread_id="thread_time",
        run_id="run_time",
        user_id="default_user",
        enabled_mcp_server_ids=[server.id],
        mcp_service=service,
    )
    call = result["mcp_tool_calls"][0]
    assert call["tool"]["name"] == "get_current_time"
    assert call["arguments"] == {"timezone": "Asia/Shanghai"}
    assert call["call_id"]
    assert call["output"]["isError"] is False
    assert "+08:00" in call["output"]["content"][0]["text"]
    assert "工具返回" in result["response"]

def test_schema_validation_blocks_invalid_time_arguments_before_transport(store: DataStore) -> None:
    class RecordingTransport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def list_tools(self, server: MCPServer, *, timeout_seconds: float = 10):
            return [
                {
                    "name": "get_current_time",
                    "description": "Get time",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"timezone": {"type": "string"}},
                        "required": ["timezone"],
                        "additionalProperties": False,
                    },
                }
            ]

        def call_tool(self, server, tool_name, arguments, *, timeout_seconds=10):
            self.calls.append((tool_name, arguments))
            return {"content": []}

    server = store.create_mcp_server("default_user", "time", "https://example.test/mcp")
    transport = RecordingTransport()
    service = MCPService(
        store.session,
        transport_client=transport,
        llm_service=FakeLLMService(),
    )
    tool = service.refresh_tools("default_user", server.id)[0]

    with pytest.raises(MCPServiceError) as error:
        service.call_tool("default_user", tool.id, {})

    assert error.value.code == ErrorCode.VALIDATION_ERROR
    assert transport.calls == []


def test_stdio_request_requires_command() -> None:
    with pytest.raises(ValueError):
        MCPServerCreateRequest(
            user_id="default_user",
            name="time",
            transport=MCPTransport.STDIO,
        )



def test_deepseek_tool_call_contract_uses_provider_tools(monkeypatch) -> None:
    from app.services import llm_service as llm_module
    from app.services.llm_service import DeepSeekLLMService

    captured: dict[str, Any] = {}

    class Response:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "tool_time",
                                        "arguments": '{"timezone":"Asia/Shanghai"}',
                                    }
                                }
                            ]
                        }
                    }
                ]
            }

    class Client:
        def __init__(self, **kwargs) -> None:
            captured["timeout"] = kwargs["timeout"]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, *, headers, json):
            captured["url"] = url
            captured["payload"] = json
            return Response()

    monkeypatch.setattr(llm_module.httpx, "Client", Client)
    service = DeepSeekLLMService(
        Settings(
            deepseek_api_key="fake-key",
            llm_base_url="https://provider.example",
            llm_model="fake-model",
        )
    )
    selection = service.select_tool(
        [{"role": "user", "content": "上海现在几点"}],
        [
            {
                "type": "function",
                "function": {
                    "name": "tool_time",
                    "description": "Get current time",
                    "parameters": {
                        "type": "object",
                        "properties": {"timezone": {"type": "string"}},
                        "required": ["timezone"],
                    },
                },
            }
        ],
        system_prompt="Select a tool.",
    )

    assert selection is not None
    assert selection.tool_name == "tool_time"
    assert selection.arguments == {"timezone": "Asia/Shanghai"}
    assert captured["payload"]["tool_choice"] == "auto"
    assert captured["payload"]["tools"][0]["type"] == "function"
