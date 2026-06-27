from __future__ import annotations

import json
import socket
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.models import MCPServer, MCPTool
from app.models.schemas import ErrorCode, ErrorResponse, MCPTool as MCPToolSchema, RiskLevel
from app.services.data_store import DataStore


class MCPServiceError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_error_response(self) -> ErrorResponse:
        return ErrorResponse(code=self.code, message=self.message, details=self.details)


class MCPTransportClient(Protocol):
    def list_tools(self, server: MCPServer, *, timeout_seconds: float = 10) -> list[dict[str, Any]]:
        ...

    def call_tool(
        self,
        server: MCPServer,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float = 10,
    ) -> dict[str, Any]:
        ...


class JSONRPCMCPTransportClient:
    def _post_json_rpc(
        self,
        server: MCPServer,
        method: str,
        params: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        if server.transport == "stdio_bridge":
            raise MCPServiceError(
                ErrorCode.EXTERNAL_SERVICE_ERROR,
                "Local stdio MCP bridge is reserved but not implemented yet.",
                {"server_id": server.id, "transport": server.transport},
            )

        body = json.dumps(
            {"jsonrpc": "2.0", "id": str(uuid4()), "method": method, "params": params}
        ).encode("utf-8")
        request = Request(
            server.endpoint_url,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - user-configured MCP endpoint.
                payload = json.loads(response.read().decode("utf-8"))
        except socket.timeout as exc:
            raise MCPServiceError(
                ErrorCode.EXTERNAL_SERVICE_ERROR,
                "MCP server request timed out.",
                {"server_id": server.id, "method": method, "timeout_seconds": timeout_seconds},
            ) from exc
        except HTTPError as exc:
            raise MCPServiceError(
                ErrorCode.EXTERNAL_SERVICE_ERROR,
                "MCP server returned an HTTP error.",
                {"server_id": server.id, "method": method, "status_code": exc.code},
            ) from exc
        except URLError as exc:
            raise MCPServiceError(
                ErrorCode.EXTERNAL_SERVICE_ERROR,
                "MCP server connection failed.",
                {"server_id": server.id, "method": method, "reason": str(exc.reason)},
            ) from exc
        except json.JSONDecodeError as exc:
            raise MCPServiceError(
                ErrorCode.EXTERNAL_SERVICE_ERROR,
                "MCP server returned invalid JSON.",
                {"server_id": server.id, "method": method},
            ) from exc

        if not isinstance(payload, dict):
            raise MCPServiceError(
                ErrorCode.EXTERNAL_SERVICE_ERROR,
                "MCP server response must be a JSON object.",
                {"server_id": server.id, "method": method},
            )
        if payload.get("error"):
            raise MCPServiceError(
                ErrorCode.EXTERNAL_SERVICE_ERROR,
                "MCP server returned a JSON-RPC error.",
                {"server_id": server.id, "method": method, "error": payload["error"]},
            )
        result = payload.get("result", payload)
        if not isinstance(result, dict):
            raise MCPServiceError(
                ErrorCode.EXTERNAL_SERVICE_ERROR,
                "MCP server result must be a JSON object.",
                {"server_id": server.id, "method": method},
            )
        return result

    def list_tools(self, server: MCPServer, *, timeout_seconds: float = 10) -> list[dict[str, Any]]:
        result = self._post_json_rpc(server, "tools/list", {}, timeout_seconds=timeout_seconds)
        tools = result.get("tools", result.get("data", []))
        if not isinstance(tools, list):
            raise MCPServiceError(
                ErrorCode.EXTERNAL_SERVICE_ERROR,
                "MCP tools/list response did not contain a tools array.",
                {"server_id": server.id},
            )
        return [tool for tool in tools if isinstance(tool, dict)]

    def call_tool(
        self,
        server: MCPServer,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float = 10,
    ) -> dict[str, Any]:
        return self._post_json_rpc(
            server,
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            timeout_seconds=timeout_seconds,
        )


HIGH_RISK_WORDS = ("delete", "remove", "write", "send", "email", "pay", "order", "calendar", "file")
MEDIUM_RISK_WORDS = ("update", "create", "submit", "post", "message", "todo", "task")


def infer_risk_level(tool_name: str, description: str | None, metadata: dict[str, Any]) -> RiskLevel:
    explicit = metadata.get("risk_level") or metadata.get("risk")
    if explicit in {item.value for item in RiskLevel}:
        return RiskLevel(str(explicit))
    text = f"{tool_name} {description or ''}".lower()
    if any(word in text for word in HIGH_RISK_WORDS):
        return RiskLevel.HIGH
    if any(word in text for word in MEDIUM_RISK_WORDS):
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def mcp_tool_to_schema(tool: MCPTool, server: MCPServer) -> MCPToolSchema:
    return MCPToolSchema(
        id=tool.id,
        server_id=tool.server_id,
        name=tool.name,
        description=tool.description,
        transport=server.transport,
        input_schema=tool.input_schema,
        risk_level=tool.risk_level,
        enabled=tool.enabled,
        metadata=tool.metadata_json,
    )


class MCPService:
    def __init__(
        self,
        session: Session,
        *,
        transport_client: MCPTransportClient | None = None,
    ) -> None:
        self.session = session
        self.store = DataStore(session)
        self.transport_client = transport_client or JSONRPCMCPTransportClient()

    def refresh_tools(self, user_id: str, server_id: str) -> list[MCPTool]:
        server = self._get_server_for_user(user_id, server_id)
        raw_tools = self.transport_client.list_tools(server)
        tools: list[MCPTool] = []
        for raw_tool in raw_tools:
            name = raw_tool.get("name")
            if not isinstance(name, str) or not name.strip():
                raise MCPServiceError(
                    ErrorCode.EXTERNAL_SERVICE_ERROR,
                    "MCP tool schema is missing a valid name.",
                    {"server_id": server.id, "tool": raw_tool},
                )
            input_schema = raw_tool.get("inputSchema") or raw_tool.get("input_schema") or {}
            if not isinstance(input_schema, dict):
                raise MCPServiceError(
                    ErrorCode.EXTERNAL_SERVICE_ERROR,
                    "MCP tool input schema must be an object.",
                    {"server_id": server.id, "tool_name": name},
                )
            metadata = raw_tool.get("metadata") if isinstance(raw_tool.get("metadata"), dict) else {}
            description = raw_tool.get("description") if isinstance(raw_tool.get("description"), str) else None
            tools.append(
                self.store.upsert_mcp_tool(
                    server.id,
                    name.strip(),
                    description=description,
                    input_schema=input_schema,
                    risk_level=infer_risk_level(name, description, metadata),
                    enabled=True,
                    metadata=metadata,
                )
            )
        return tools

    def list_tools(
        self,
        user_id: str,
        *,
        server_ids: list[str] | None = None,
        enabled_only: bool = True,
    ) -> list[tuple[MCPTool, MCPServer]]:
        pairs: list[tuple[MCPTool, MCPServer]] = []
        for tool in self.store.list_mcp_tools(user_id, server_ids=server_ids, enabled_only=enabled_only):
            server = self.store.get_mcp_server(tool.server_id)
            if server is not None:
                pairs.append((tool, server))
        return pairs

    def call_tool(
        self,
        user_id: str,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        thread_id: str | None = None,
        timeout_seconds: float = 10,
        require_approval: bool = True,
    ) -> tuple[MCPTool, MCPServer, dict[str, Any], str]:
        tool = self.store.get_mcp_tool_for_user(user_id, tool_id)
        if tool is None:
            raise MCPServiceError(ErrorCode.NOT_FOUND, "MCP tool was not found.", {"tool_id": tool_id})
        server = self._get_server_for_user(user_id, tool.server_id)
        if not tool.enabled or not server.enabled:
            raise MCPServiceError(
                ErrorCode.VALIDATION_ERROR,
                "MCP tool or server is disabled.",
                {"tool_id": tool.id, "server_id": server.id},
            )
        if require_approval and tool.risk_level != RiskLevel.LOW.value:
            raise MCPServiceError(
                ErrorCode.APPROVAL_REQUIRED,
                "MCP tool requires approval before execution.",
                {"tool_id": tool.id, "risk_level": tool.risk_level},
            )
        try:
            output = self.transport_client.call_tool(
                server, tool.name, arguments, timeout_seconds=timeout_seconds
            )
            call = self.store.create_mcp_tool_call(
                user_id,
                server.id,
                tool.name,
                thread_id=thread_id,
                tool_id=tool.id,
                arguments=arguments,
                output=output,
                risk_level=tool.risk_level,
                status="succeeded",
            )
            return tool, server, output, call.id
        except MCPServiceError as exc:
            self.store.create_mcp_tool_call(
                user_id,
                server.id,
                tool.name,
                thread_id=thread_id,
                tool_id=tool.id,
                arguments=arguments,
                output={},
                risk_level=tool.risk_level,
                status="failed",
                error_message=exc.message,
            )
            raise

    def choose_tool(
        self, user_id: str, message: str, *, server_ids: list[str] | None = None
    ) -> tuple[MCPTool, MCPServer] | None:
        lower_message = message.lower()
        candidates = list(self.list_tools(user_id, server_ids=server_ids))
        if not candidates:
            return None
        for tool, server in candidates:
            if tool.name.lower() in lower_message:
                return tool, server
        low_risk = [pair for pair in candidates if pair[0].risk_level == RiskLevel.LOW.value]
        if low_risk:
            return low_risk[0]
        return candidates[0]
    def choose_low_risk_tool(
        self, user_id: str, message: str, *, server_ids: list[str] | None = None
    ) -> tuple[MCPTool, MCPServer] | None:
        lower_message = message.lower()
        candidates = [
            (tool, server)
            for tool, server in self.list_tools(user_id, server_ids=server_ids)
            if tool.risk_level == RiskLevel.LOW.value
        ]
        if not candidates:
            return None
        for tool, server in candidates:
            if tool.name.lower() in lower_message:
                return tool, server
        return candidates[0]

    def build_arguments_for_tool(self, tool: MCPTool, message: str) -> dict[str, Any]:
        properties = tool.input_schema.get("properties")
        if not isinstance(properties, dict):
            return {"query": message}
        arguments: dict[str, Any] = {}
        for key, schema in properties.items():
            if not isinstance(key, str) or not isinstance(schema, dict):
                continue
            if key in {"query", "q", "message", "text", "prompt"}:
                arguments[key] = message
            elif key in {"location", "city"}:
                arguments[key] = "当前用户位置"
        return arguments or {"query": message}

    def _get_server_for_user(self, user_id: str, server_id: str) -> MCPServer:
        server = self.store.get_mcp_server(server_id)
        if server is None or server.user_id != user_id:
            raise MCPServiceError(ErrorCode.NOT_FOUND, "MCP server was not found.", {"server_id": server_id})
        return server
