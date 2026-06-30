from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol, TypeVar
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, SchemaError, ValidationError
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import MCPServer, MCPTool
from app.models.schemas import ErrorCode, ErrorResponse, MCPTool as MCPToolSchema, RiskLevel
from app.services.data_store import DataStore
from app.services.llm_service import LLMMessage, LLMService, LLMServiceError


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


ResultT = TypeVar("ResultT")


class OfficialMCPTransportClient:
    """Official MCP SDK client for stdio, Streamable HTTP, and legacy SSE."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def list_tools(self, server: MCPServer, *, timeout_seconds: float = 10) -> list[dict[str, Any]]:
        async def operation(session: ClientSession) -> list[dict[str, Any]]:
            items: list[dict[str, Any]] = []
            cursor: str | None = None
            while True:
                result = await session.list_tools(cursor=cursor)
                items.extend(
                    tool.model_dump(mode="json", by_alias=True, exclude_none=True)
                    for tool in result.tools
                )
                cursor = result.nextCursor
                if not cursor:
                    return items

        return self._run(server, operation, timeout_seconds)

    def call_tool(
        self,
        server: MCPServer,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float = 10,
    ) -> dict[str, Any]:
        async def operation(session: ClientSession) -> dict[str, Any]:
            result = await session.call_tool(
                tool_name,
                arguments=arguments,
                read_timeout_seconds=timedelta(seconds=timeout_seconds),
            )
            return result.model_dump(mode="json", by_alias=True, exclude_none=True)

        output = self._run(server, operation, timeout_seconds)
        if output.get("isError"):
            raise MCPServiceError(
                ErrorCode.EXTERNAL_SERVICE_ERROR,
                "MCP tool returned an error result.",
                {"server_id": server.id, "tool_name": tool_name},
            )
        return output

    def _run(
        self,
        server: MCPServer,
        operation: Callable[[ClientSession], Awaitable[ResultT]],
        timeout_seconds: float,
    ) -> ResultT:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mcp-client")
        future = executor.submit(
            asyncio.run,
            self._run_session(server, operation, timeout_seconds),
        )
        try:
            return future.result(timeout=timeout_seconds + 2)
        except FutureTimeoutError as exc:
            future.cancel()
            raise MCPServiceError(
                ErrorCode.EXTERNAL_SERVICE_ERROR,
                "MCP server request timed out.",
                {"server_id": server.id, "timeout_seconds": timeout_seconds},
            ) from exc
        except MCPServiceError:
            raise
        except Exception as exc:
            raise MCPServiceError(
                ErrorCode.EXTERNAL_SERVICE_ERROR,
                "MCP server connection or protocol lifecycle failed.",
                {"server_id": server.id, "error_type": type(exc).__name__},
            ) from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    async def _run_session(
        self,
        server: MCPServer,
        operation: Callable[[ClientSession], Awaitable[ResultT]],
        timeout_seconds: float,
    ) -> ResultT:
        async with self._transport(server, timeout_seconds) as (read_stream, write_stream):
            async with ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timedelta(seconds=timeout_seconds),
            ) as session:
                await session.initialize()
                return await operation(session)

    @asynccontextmanager
    async def _transport(self, server: MCPServer, timeout_seconds: float):
        if server.transport in {"stdio", "stdio_bridge"}:
            command = (server.command or "").strip()
            command_name = Path(command).name
            normalized = command_name.lower()
            if normalized.endswith(".exe"):
                normalized = normalized[:-4]
            command_has_path = command_name != command
            if (
                not command
                or normalized not in self.settings.mcp_stdio_command_allowlist
                or (command_has_path and not self.settings.mcp_stdio_allow_absolute_commands)
            ):
                raise MCPServiceError(
                    ErrorCode.VALIDATION_ERROR,
                    "MCP stdio command is not allowed.",
                    {"server_id": server.id, "command": normalized or None},
                )

            args = list(server.args or [])
            target = Path(args[0]).name.lower() if args else ""
            if not target or target not in self.settings.mcp_stdio_target_allowlist:
                raise MCPServiceError(
                    ErrorCode.VALIDATION_ERROR,
                    "MCP stdio target is not allowed.",
                    {"server_id": server.id, "command": normalized, "target": target or None},
                )
            if normalized == "uvx" and args[0].lower() != target:
                raise MCPServiceError(
                    ErrorCode.VALIDATION_ERROR,
                    "uvx MCP targets must be bare allowlisted package names.",
                    {"server_id": server.id, "target": target},
                )
            unexpected_env = set(server.env or {}) - self.settings.mcp_stdio_env_key_allowlist
            if unexpected_env:
                raise MCPServiceError(
                    ErrorCode.VALIDATION_ERROR,
                    "MCP stdio environment contains non-allowlisted keys.",
                    {"server_id": server.id, "env_keys": sorted(unexpected_env)},
                )
            if server.working_directory and not self.settings.mcp_stdio_allow_working_directory:
                raise MCPServiceError(
                    ErrorCode.VALIDATION_ERROR,
                    "MCP stdio working directories are disabled.",
                    {"server_id": server.id},
                )
            parameters = StdioServerParameters(
                command=command,
                args=args,
                env=dict(server.env) if server.env else None,
                cwd=server.working_directory,
            )
            async with stdio_client(parameters) as streams:
                yield streams
            return

        parsed = urlparse(server.endpoint_url)
        hostname = (parsed.hostname or "").rstrip(".").lower()
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
            raise MCPServiceError(
                ErrorCode.VALIDATION_ERROR,
                "MCP HTTP endpoint must be an absolute http(s) URL without embedded credentials.",
                {"server_id": server.id},
            )
        allowed_remote_hosts = self.settings.mcp_remote_host_allowlist
        if self.settings.environment.lower() == "production" and parsed.scheme != "https":
            raise MCPServiceError(
                ErrorCode.VALIDATION_ERROR,
                "Production MCP HTTP endpoints must use HTTPS.",
                {"server_id": server.id, "host": hostname},
            )
        if (self.settings.environment.lower() == "production" or allowed_remote_hosts) and (
            hostname not in allowed_remote_hosts
        ):
            raise MCPServiceError(
                ErrorCode.VALIDATION_ERROR,
                "MCP remote host is not allowlisted.",
                {"server_id": server.id, "host": hostname},
            )
        if server.transport == "sse":
            async with sse_client(
                server.endpoint_url,
                timeout=timeout_seconds,
                sse_read_timeout=timeout_seconds,
            ) as streams:
                yield streams
            return
        if server.transport not in {"http", "streamable_http"}:
            raise MCPServiceError(
                ErrorCode.VALIDATION_ERROR,
                "Unsupported MCP transport.",
                {"server_id": server.id, "transport": server.transport},
            )
        async with streamable_http_client(server.endpoint_url) as streams:
            yield streams[0], streams[1]


HIGH_RISK_WORDS = ("delete", "remove", "write", "send", "email", "pay", "order", "calendar", "file")
MEDIUM_RISK_WORDS = ("update", "create", "submit", "post", "message", "todo", "task")


def infer_risk_level(tool_name: str, description: str | None, metadata: dict[str, Any]) -> RiskLevel:
    explicit = metadata.get("risk_level") or metadata.get("risk")
    if explicit in {item.value for item in RiskLevel}:
        return RiskLevel(str(explicit))
    text = f"{tool_name} {description or ""}".lower()
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


def validate_tool_arguments(tool: MCPTool, arguments: dict[str, Any]) -> None:
    schema = tool.input_schema or {"type": "object"}
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(arguments)
    except SchemaError as exc:
        raise MCPServiceError(
            ErrorCode.EXTERNAL_SERVICE_ERROR,
            "MCP server published an invalid tool input schema.",
            {"tool_id": tool.id, "schema_path": list(exc.path)},
        ) from exc
    except ValidationError as exc:
        raise MCPServiceError(
            ErrorCode.VALIDATION_ERROR,
            "MCP tool arguments do not match the advertised input schema.",
            {
                "tool_id": tool.id,
                "argument_path": list(exc.absolute_path),
                "schema_path": list(exc.absolute_schema_path),
            },
        ) from exc


class MCPService:
    def __init__(
        self,
        session: Session,
        *,
        transport_client: MCPTransportClient | None = None,
        llm_service: LLMService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.store = DataStore(session)
        self.settings = settings or get_settings()
        self.transport_client = transport_client or OfficialMCPTransportClient(self.settings)
        self.llm_service = llm_service

    def refresh_tools(self, user_id: str, server_id: str) -> list[MCPTool]:
        server = self._get_server_for_user(user_id, server_id)
        raw_tools = self.transport_client.list_tools(
            server, timeout_seconds=self.settings.mcp_timeout_seconds
        )
        tools: list[MCPTool] = []
        for raw_tool in raw_tools:
            name = raw_tool.get("name")
            if not isinstance(name, str) or not name.strip():
                raise MCPServiceError(
                    ErrorCode.EXTERNAL_SERVICE_ERROR,
                    "MCP tool schema is missing a valid name.",
                    {"server_id": server.id},
                )
            input_schema = raw_tool.get("inputSchema") or raw_tool.get("input_schema") or {}
            if not isinstance(input_schema, dict):
                raise MCPServiceError(
                    ErrorCode.EXTERNAL_SERVICE_ERROR,
                    "MCP tool input schema must be an object.",
                    {"server_id": server.id, "tool_name": name},
                )
            try:
                Draft202012Validator.check_schema(input_schema)
            except SchemaError as exc:
                raise MCPServiceError(
                    ErrorCode.EXTERNAL_SERVICE_ERROR,
                    "MCP server published an invalid tool input schema.",
                    {"server_id": server.id, "tool_name": name},
                ) from exc
            metadata = raw_tool.get("_meta") if isinstance(raw_tool.get("_meta"), dict) else {}
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

    def select_tool(
        self,
        user_id: str,
        message: str,
        *,
        history: list[LLMMessage] | None = None,
        server_ids: list[str] | None = None,
    ) -> tuple[MCPTool, MCPServer, dict[str, Any]] | None:
        candidates = list(self.list_tools(user_id, server_ids=server_ids))
        if not candidates:
            return None
        if self.llm_service is None:
            raise MCPServiceError(
                ErrorCode.EXTERNAL_SERVICE_ERROR,
                "LLM tool selection is not configured.",
            )

        aliases: dict[str, tuple[MCPTool, MCPServer]] = {}
        tool_definitions: list[dict[str, Any]] = []
        for tool, server in candidates:
            alias = f"tool_{tool.id.replace("-", "_")}"
            aliases[alias] = (tool, server)
            tool_definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": alias,
                        "description": (
                            f"MCP tool name: {tool.name}. Server: {server.name}. "
                            f"{tool.description or ""}"
                        ).strip(),
                        "parameters": tool.input_schema or {"type": "object"},
                    },
                }
            )
        messages = [*(history or []), {"role": "user", "content": message}]
        try:
            selection = self.llm_service.select_tool(
                messages,
                tool_definitions,
                system_prompt=(
                    "你是生活助手的 MCP 工具规划器。只有当工具确实适合用户请求时才调用；"
                    "参数必须严格符合工具 JSON Schema。不得虚构工具，不得绕过审批。"
                ),
            )
        except LLMServiceError as exc:
            raise MCPServiceError(
                ErrorCode.EXTERNAL_SERVICE_ERROR,
                "LLM MCP tool selection failed.",
                {"kind": exc.kind},
            ) from exc
        if selection is None:
            return None
        pair = aliases.get(selection.tool_name)
        if pair is None:
            raise MCPServiceError(
                ErrorCode.VALIDATION_ERROR,
                "LLM selected an unavailable MCP tool.",
                {"selected_tool": selection.tool_name},
            )
        tool, server = pair
        validate_tool_arguments(tool, selection.arguments)
        return tool, server, selection.arguments

    def call_tool(
        self,
        user_id: str,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        thread_id: str | None = None,
        timeout_seconds: float | None = None,
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
        validate_tool_arguments(tool, arguments)
        if require_approval and tool.risk_level != RiskLevel.LOW.value:
            raise MCPServiceError(
                ErrorCode.APPROVAL_REQUIRED,
                "MCP tool requires approval before execution.",
                {"tool_id": tool.id, "risk_level": tool.risk_level},
            )
        effective_timeout = timeout_seconds or self.settings.mcp_timeout_seconds
        try:
            output = self.transport_client.call_tool(
                server, tool.name, arguments, timeout_seconds=effective_timeout
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

    def _get_server_for_user(self, user_id: str, server_id: str) -> MCPServer:
        server = self.store.get_mcp_server(server_id)
        if server is None or server.user_id != user_id:
            raise MCPServiceError(ErrorCode.NOT_FOUND, "MCP server was not found.", {"server_id": server_id})
        return server
