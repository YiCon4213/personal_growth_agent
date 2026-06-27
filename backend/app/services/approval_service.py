from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ApprovalRequest as ApprovalRequestModel
from app.models.schemas import (
    ApprovalRequest,
    ApprovalStatus,
    ErrorCode,
    MCPToolCallResponse,
    RiskLevel,
)
from app.services.data_store import DataStore
from app.services.mcp_service import MCPService, MCPServiceError, mcp_tool_to_schema


class ApprovalServiceError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def approval_to_schema(approval: ApprovalRequestModel) -> ApprovalRequest:
    return ApprovalRequest(
        id=approval.id,
        user_id=approval.user_id,
        thread_id=approval.thread_id,
        tool_id=approval.tool_id,
        server_id=approval.server_id,
        tool_name=approval.tool_name,
        arguments=approval.arguments,
        risk_level=RiskLevel(approval.risk_level),
        expected_impact=approval.expected_impact,
        status=ApprovalStatus(approval.status),
        created_at=approval.created_at,
        decided_at=approval.decided_at,
        executed_at=approval.executed_at,
        tool_call_id=approval.tool_call_id,
        execution_result=approval.execution_result,
        error_message=approval.error_message,
    )


def build_expected_impact(tool_name: str, risk_level: str, arguments: dict[str, Any]) -> str:
    return (
        f"工具 {tool_name} 的风险等级为 {risk_level}，执行前需要用户确认。"
        f"它将使用参数 {arguments} 调用外部 MCP 工具，可能产生写入、发送或修改外部状态的影响。"
    )


class ApprovalService:
    def __init__(self, session: Session, *, mcp_service: MCPService | None = None) -> None:
        self.session = session
        self.store = DataStore(session)
        self.mcp_service = mcp_service or MCPService(session)

    def create_for_tool_call(
        self,
        *,
        user_id: str,
        thread_id: str,
        tool_id: str,
        arguments: dict[str, Any],
    ) -> ApprovalRequestModel:
        tool = self.store.get_mcp_tool_for_user(user_id, tool_id)
        if tool is None:
            raise ApprovalServiceError(ErrorCode.NOT_FOUND, "MCP tool was not found.", {"tool_id": tool_id})
        server = self.store.get_mcp_server(tool.server_id)
        if server is None or server.user_id != user_id:
            raise ApprovalServiceError(ErrorCode.NOT_FOUND, "MCP server was not found.", {"server_id": tool.server_id})
        if tool.risk_level == RiskLevel.LOW.value:
            raise ApprovalServiceError(
                ErrorCode.VALIDATION_ERROR,
                "Low-risk MCP tools do not require approval.",
                {"tool_id": tool.id},
            )
        return self.store.create_approval_request(
            user_id,
            thread_id,
            server.id,
            tool.id,
            tool.name,
            arguments,
            risk_level=tool.risk_level,
            expected_impact=build_expected_impact(tool.name, tool.risk_level, arguments),
        )

    def list_pending(self, user_id: str) -> list[ApprovalRequestModel]:
        return list(self.store.list_approval_requests(user_id, status=ApprovalStatus.PENDING))

    def approve(
        self,
        approval_id: str,
        *,
        user_id: str | None = None,
        approver_id: str | None = None,
        reason: str | None = None,
        timeout_seconds: float = 10,
    ) -> tuple[ApprovalRequestModel, MCPToolCallResponse]:
        approval = self._get_mutable_pending(approval_id, user_id=user_id)
        now = datetime.now(UTC)
        approval.status = ApprovalStatus.APPROVED.value
        approval.approved_by = approver_id or user_id
        approval.decision_reason = reason
        approval.decided_at = now
        try:
            tool, server, output, call_id = self.mcp_service.call_tool(
                approval.user_id,
                approval.tool_id,
                approval.arguments,
                thread_id=approval.thread_id,
                timeout_seconds=timeout_seconds,
                require_approval=False,
            )
            approval.status = ApprovalStatus.EXECUTED.value
            approval.tool_call_id = call_id
            approval.execution_result = output
            approval.executed_at = datetime.now(UTC)
            response = MCPToolCallResponse(
                call_id=call_id,
                tool=mcp_tool_to_schema(tool, server),
                arguments=approval.arguments,
                output=output,
                status="succeeded",
            )
            return approval, response
        except MCPServiceError as exc:
            approval.status = ApprovalStatus.FAILED.value
            approval.error_message = exc.message
            approval.executed_at = datetime.now(UTC)
            raise

    def reject(
        self,
        approval_id: str,
        *,
        user_id: str | None = None,
        approver_id: str | None = None,
        reason: str | None = None,
    ) -> ApprovalRequestModel:
        approval = self._get_mutable_pending(approval_id, user_id=user_id)
        approval.status = ApprovalStatus.REJECTED.value
        approval.rejected_by = approver_id or user_id
        approval.decision_reason = reason
        approval.decided_at = datetime.now(UTC)
        return approval

    def _get_mutable_pending(self, approval_id: str, *, user_id: str | None) -> ApprovalRequestModel:
        approval = self.store.get_approval_request(approval_id)
        if approval is None:
            raise ApprovalServiceError(ErrorCode.NOT_FOUND, "Approval request was not found.", {"approval_id": approval_id})
        if user_id is not None and approval.user_id != user_id:
            raise ApprovalServiceError(ErrorCode.NOT_FOUND, "Approval request was not found.", {"approval_id": approval_id})
        if approval.status != ApprovalStatus.PENDING.value:
            raise ApprovalServiceError(
                ErrorCode.VALIDATION_ERROR,
                "Approval request is no longer pending.",
                {"approval_id": approval_id, "status": approval.status},
            )
        return approval
