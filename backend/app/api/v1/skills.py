from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import DatabaseConfigurationError, get_session
from app.models.schemas import (
    CandidateStatus,
    ErrorResponse,
    SkillCandidate,
    SkillCandidateDecisionRequest,
    SkillCandidateDecisionResponse,
    UserSkill,
)
from app.services.skill_service import (
    SkillService,
    SkillServiceError,
    skill_candidate_to_schema,
    skill_to_schema,
)

router = APIRouter(prefix="/skills", tags=["skills"])
SessionDependency = Annotated[Session, Depends(get_session)]


def raise_skill_http_error(exc: SkillServiceError) -> None:
    status_code = 400
    if exc.code == "not_found":
        status_code = 404
    detail = ErrorResponse(code=exc.code, message=exc.message, details=exc.details).model_dump(mode="json")
    raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("", response_model=list[UserSkill])
def list_skills(
    user_id: str,
    session: SessionDependency,
    enabled_only: bool = Query(default=True),
) -> list[UserSkill]:
    try:
        service = SkillService(session)
        return [skill_to_schema(item) for item in service.list_skills(user_id, enabled_only=enabled_only)]
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/candidates", response_model=list[SkillCandidate])
def list_skill_candidates(
    user_id: str,
    session: SessionDependency,
    status: CandidateStatus | None = Query(default=CandidateStatus.PENDING),
) -> list[SkillCandidate]:
    try:
        service = SkillService(session)
        return [skill_candidate_to_schema(item) for item in service.list_candidates(user_id, status=status)]
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/candidates/{candidate_id}/approve", response_model=SkillCandidateDecisionResponse)
def approve_skill_candidate(
    candidate_id: str,
    request: SkillCandidateDecisionRequest,
    session: SessionDependency,
) -> SkillCandidateDecisionResponse:
    try:
        service = SkillService(session)
        candidate, skill = service.approve_candidate(candidate_id, user_id=request.user_id)
        session.commit()
        return SkillCandidateDecisionResponse(
            candidate=skill_candidate_to_schema(candidate),
            skill=skill_to_schema(skill),
        )
    except SkillServiceError as exc:
        session.rollback()
        raise_skill_http_error(exc)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/candidates/{candidate_id}/reject", response_model=SkillCandidateDecisionResponse)
def reject_skill_candidate(
    candidate_id: str,
    request: SkillCandidateDecisionRequest,
    session: SessionDependency,
) -> SkillCandidateDecisionResponse:
    try:
        service = SkillService(session)
        candidate = service.reject_candidate(candidate_id, user_id=request.user_id)
        session.commit()
        return SkillCandidateDecisionResponse(
            candidate=skill_candidate_to_schema(candidate),
            skill=None,
        )
    except SkillServiceError as exc:
        session.rollback()
        raise_skill_http_error(exc)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/{skill_id}/disable", response_model=UserSkill)
def disable_skill(
    skill_id: str,
    user_id: str,
    session: SessionDependency,
) -> UserSkill:
    try:
        service = SkillService(session)
        skill = service.disable_skill(skill_id, user_id=user_id)
        session.commit()
        return skill_to_schema(skill)
    except SkillServiceError as exc:
        session.rollback()
        raise_skill_http_error(exc)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
