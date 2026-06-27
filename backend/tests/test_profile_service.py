from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.models.schemas import CandidateStatus, ProfileCategory
from app.services.profile_service import ProfileService, extract_profile_candidates


def make_service() -> ProfileService:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return ProfileService(session_factory())


def test_extracts_learning_profile_candidate_without_writing_profile_item() -> None:
    service = make_service()

    candidates = service.extract_candidates_from_message(
        user_id="user_1",
        thread_id="thread_1",
        message="我每天晚上 9 点后学习效率高，请帮我安排学习计划。",
    )

    assert len(candidates) == 1
    assert candidates[0].status == CandidateStatus.PENDING.value
    assert candidates[0].category == ProfileCategory.LEARNING.value
    assert "晚上9点后学习效率高" in candidates[0].content
    assert service.list_profile_items("user_1") == []


def test_approve_candidate_writes_confirmed_profile_item() -> None:
    service = make_service()
    candidate = service.extract_candidates_from_message(
        user_id="user_1",
        thread_id="thread_1",
        message="我每天晚上 9 点后学习效率高。",
    )[0]

    approved, item = service.approve_candidate(candidate.id, user_id="user_1")

    assert approved.status == CandidateStatus.APPROVED.value
    assert item.content == candidate.content
    assert item.source_thread_id == "thread_1"
    assert service.relevant_profile_context("user_1", "帮我规划 Python 学习")[0]["content"] == item.content


def test_reject_candidate_does_not_write_profile_item() -> None:
    service = make_service()
    candidate = service.extract_candidates_from_message(
        user_id="user_1",
        thread_id="thread_1",
        message="我喜欢详细、一步步解释。",
    )[0]

    rejected = service.reject_candidate(candidate.id, user_id="user_1")

    assert rejected.status == CandidateStatus.REJECTED.value
    assert service.list_profile_items("user_1") == []


def test_sensitive_message_is_not_extracted() -> None:
    extracted = extract_profile_candidates("我的身份证是 123456，帮我记住。", thread_id="thread_1")

    assert extracted == []


def test_disable_and_delete_profile_item() -> None:
    service = make_service()
    candidate = service.extract_candidates_from_message(
        user_id="user_1",
        thread_id="thread_1",
        message="我喜欢详细、一步步解释。",
    )[0]
    _, item = service.approve_candidate(candidate.id, user_id="user_1")

    disabled = service.disable_profile_item(item.id, user_id="user_1")
    assert disabled.enabled is False
    assert service.list_profile_items("user_1", enabled_only=True) == []

    service.delete_profile_item(item.id, user_id="user_1")
    assert service.list_profile_items("user_1", enabled_only=False) == []
