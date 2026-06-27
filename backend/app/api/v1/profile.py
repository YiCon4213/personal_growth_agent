from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import DatabaseConfigurationError, get_session
from app.models.schemas import (
    CandidateStatus,
    ErrorResponse,
    ProfileCandidate,
    ProfileCandidateDecisionRequest,
    ProfileCandidateDecisionResponse,
    UserProfileItem,
)
from app.services.profile_service import (
    ProfileService,
    ProfileServiceError,
    profile_candidate_to_schema,
    profile_item_to_schema,
)

router = APIRouter(prefix="/profile", tags=["profile"])
SessionDependency = Annotated[Session, Depends(get_session)]


def raise_profile_http_error(exc: ProfileServiceError) -> None:
    status_code = 400
    if exc.code == "not_found":
        status_code = 404
    detail = ErrorResponse(code=exc.code, message=exc.message, details=exc.details).model_dump(mode="json")
    raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("", response_model=list[UserProfileItem])
def list_profile_items(
    user_id: str,
    session: SessionDependency,
    enabled_only: bool = Query(default=True),
) -> list[UserProfileItem]:
    try:
        service = ProfileService(session)
        return [profile_item_to_schema(item) for item in service.list_profile_items(user_id, enabled_only=enabled_only)]
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/candidates", response_model=list[ProfileCandidate])
def list_profile_candidates(
    user_id: str,
    session: SessionDependency,
    status: CandidateStatus | None = Query(default=CandidateStatus.PENDING),
) -> list[ProfileCandidate]:
    try:
        service = ProfileService(session)
        return [profile_candidate_to_schema(item) for item in service.list_candidates(user_id, status=status)]
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/candidates/{candidate_id}/approve", response_model=ProfileCandidateDecisionResponse)
def approve_profile_candidate(
    candidate_id: str,
    request: ProfileCandidateDecisionRequest,
    session: SessionDependency,
) -> ProfileCandidateDecisionResponse:
    try:
        service = ProfileService(session)
        candidate, profile_item = service.approve_candidate(candidate_id, user_id=request.user_id)
        session.commit()
        return ProfileCandidateDecisionResponse(
            candidate=profile_candidate_to_schema(candidate),
            profile_item=profile_item_to_schema(profile_item),
        )
    except ProfileServiceError as exc:
        session.rollback()
        raise_profile_http_error(exc)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/candidates/{candidate_id}/reject", response_model=ProfileCandidateDecisionResponse)
def reject_profile_candidate(
    candidate_id: str,
    request: ProfileCandidateDecisionRequest,
    session: SessionDependency,
) -> ProfileCandidateDecisionResponse:
    try:
        service = ProfileService(session)
        candidate = service.reject_candidate(candidate_id, user_id=request.user_id)
        session.commit()
        return ProfileCandidateDecisionResponse(
            candidate=profile_candidate_to_schema(candidate),
            profile_item=None,
        )
    except ProfileServiceError as exc:
        session.rollback()
        raise_profile_http_error(exc)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/{item_id}/disable", response_model=UserProfileItem)
def disable_profile_item(
    item_id: str,
    user_id: str,
    session: SessionDependency,
) -> UserProfileItem:
    try:
        service = ProfileService(session)
        item = service.disable_profile_item(item_id, user_id=user_id)
        session.commit()
        return profile_item_to_schema(item)
    except ProfileServiceError as exc:
        session.rollback()
        raise_profile_http_error(exc)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.delete("/{item_id}")
def delete_profile_item(
    item_id: str,
    user_id: str,
    session: SessionDependency,
) -> dict[str, str]:
    try:
        service = ProfileService(session)
        service.delete_profile_item(item_id, user_id=user_id)
        session.commit()
        return {"status": "deleted", "id": item_id}
    except ProfileServiceError as exc:
        session.rollback()
        raise_profile_http_error(exc)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
