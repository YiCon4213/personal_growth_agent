from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import DatabaseConfigurationError, get_session
from app.db.models import MCPServer
from app.models.schemas import (
    MCPRefreshToolsResponse,
    MCPServerCreateRequest,
    MCPServerResponse,
    MCPTool,
    MCPToolCallRequest,
    MCPToolCallResponse,
)
from app.services.data_store import DataStore
from app.services.mcp_service import MCPService, MCPServiceError, mcp_tool_to_schema

router = APIRouter(prefix="/mcp", tags=["mcp"])
SessionDependency = Annotated[Session, Depends(get_session)]


def to_server_response(server: MCPServer) -> MCPServerResponse:
    return MCPServerResponse(
        id=server.id,
        user_id=server.user_id,
        name=server.name,
        endpoint_url=server.endpoint_url,
        transport=server.transport,
        enabled=server.enabled,
        created_at=server.created_at,
        updated_at=server.updated_at,
        metadata=server.metadata_json,
    )


def raise_mcp_http_error(exc: MCPServiceError) -> None:
    status_code = 400
    if exc.code == "not_found":
        status_code = 404
    elif exc.code == "external_service_error":
        status_code = 502
    elif exc.code == "approval_required":
        status_code = 409
    raise HTTPException(status_code=status_code, detail=exc.to_error_response().model_dump(mode="json")) from exc


@router.post("/servers", response_model=MCPServerResponse)
def create_mcp_server(request: MCPServerCreateRequest, session: SessionDependency) -> MCPServerResponse:
    try:
        store = DataStore(session)
        server = store.create_mcp_server(
            request.user_id,
            request.name,
            request.endpoint_url,
            transport=request.transport,
            enabled=request.enabled,
            metadata=request.metadata,
        )
        session.commit()
        return to_server_response(server)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/servers", response_model=list[MCPServerResponse])
def list_mcp_servers(
    user_id: str,
    session: SessionDependency,
    enabled_only: bool = Query(default=False),
) -> list[MCPServerResponse]:
    try:
        store = DataStore(session)
        return [to_server_response(server) for server in store.list_mcp_servers(user_id, enabled_only=enabled_only)]
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/servers/{server_id}/refresh-tools", response_model=MCPRefreshToolsResponse)
def refresh_mcp_tools(
    server_id: str,
    user_id: str,
    session: SessionDependency,
) -> MCPRefreshToolsResponse:
    try:
        service = MCPService(session)
        tools = service.refresh_tools(user_id, server_id)
        server = service.store.get_mcp_server(server_id)
        if server is None:
            raise HTTPException(status_code=404, detail="MCP server was not found.")
        session.commit()
        return MCPRefreshToolsResponse(
            server=to_server_response(server),
            tools=[mcp_tool_to_schema(tool, server) for tool in tools],
        )
    except MCPServiceError as exc:
        session.rollback()
        raise_mcp_http_error(exc)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/tools", response_model=list[MCPTool])
def list_mcp_tools(
    user_id: str,
    session: SessionDependency,
    enabled_only: bool = Query(default=True),
) -> list[MCPTool]:
    try:
        service = MCPService(session)
        return [
            mcp_tool_to_schema(tool, server)
            for tool, server in service.list_tools(user_id, enabled_only=enabled_only)
        ]
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/tools/{tool_id}/test", response_model=MCPToolCallResponse)
def test_mcp_tool(
    tool_id: str,
    request: MCPToolCallRequest,
    session: SessionDependency,
) -> MCPToolCallResponse:
    try:
        service = MCPService(session)
        tool, server, output, call_id = service.call_tool(
            request.user_id,
            tool_id,
            request.arguments,
            thread_id=request.thread_id,
            timeout_seconds=request.timeout_seconds,
        )
        session.commit()
        return MCPToolCallResponse(
            call_id=call_id,
            tool=mcp_tool_to_schema(tool, server),
            arguments=request.arguments,
            output=output,
            status="succeeded",
        )
    except MCPServiceError as exc:
        session.rollback()
        raise_mcp_http_error(exc)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
