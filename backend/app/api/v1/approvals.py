from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import DatabaseConfigurationError, get_session
from app.models.schemas import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    ApprovalRequest,
    ApprovalStatus,
    ErrorResponse,
)
from app.services.approval_service import ApprovalService, ApprovalServiceError, approval_to_schema
from app.services.mcp_service import MCPServiceError

router = APIRouter(prefix="/approvals", tags=["approvals"])
SessionDependency = Annotated[Session, Depends(get_session)]


def raise_approval_http_error(exc: ApprovalServiceError | MCPServiceError) -> None:
    status_code = 400
    if exc.code == "not_found":
        status_code = 404
    elif exc.code == "external_service_error":
        status_code = 502
    detail = ErrorResponse(code=exc.code, message=exc.message, details=exc.details).model_dump(mode="json")
    raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("", response_model=list[ApprovalRequest])
def list_approvals(
    user_id: str,
    session: SessionDependency,
    status: ApprovalStatus | None = Query(default=ApprovalStatus.PENDING),
) -> list[ApprovalRequest]:
    try:
        service = ApprovalService(session)
        approvals = service.store.list_approval_requests(user_id, status=status)
        return [approval_to_schema(approval) for approval in approvals]
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/{approval_id}/approve", response_model=ApprovalDecisionResponse)
def approve_request(
    approval_id: str,
    request: ApprovalDecisionRequest,
    session: SessionDependency,
) -> ApprovalDecisionResponse:
    try:
        service = ApprovalService(session)
        approval, tool_call = service.approve(
            approval_id,
            user_id=request.user_id,
            approver_id=request.approver_id,
            reason=request.reason,
            timeout_seconds=request.timeout_seconds,
        )
        session.commit()
        return ApprovalDecisionResponse(approval=approval_to_schema(approval), tool_call=tool_call)
    except (ApprovalServiceError, MCPServiceError) as exc:
        session.rollback()
        raise_approval_http_error(exc)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/{approval_id}/reject", response_model=ApprovalDecisionResponse)
def reject_request(
    approval_id: str,
    request: ApprovalDecisionRequest,
    session: SessionDependency,
) -> ApprovalDecisionResponse:
    try:
        service = ApprovalService(session)
        approval = service.reject(
            approval_id,
            user_id=request.user_id,
            approver_id=request.approver_id,
            reason=request.reason,
        )
        session.commit()
        return ApprovalDecisionResponse(approval=approval_to_schema(approval), tool_call=None)
    except ApprovalServiceError as exc:
        session.rollback()
        raise_approval_http_error(exc)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
