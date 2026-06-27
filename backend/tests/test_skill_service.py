from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.models.schemas import CandidateStatus, SkillStatus
from app.services.skill_service import SkillService


def make_service() -> SkillService:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return SkillService(session_factory())


def add_round(service: SkillService, index: int) -> None:
    service.record_user_message(
        user_id="user_1",
        thread_id="thread_1",
        message=f"第 {index} 轮：我想学习 Python 后端，请一步步安排。",
    )
    service.record_assistant_message(
        user_id="user_1",
        thread_id="thread_1",
        message="已生成学习建议。",
    )


def test_generates_skill_candidate_after_ten_effective_user_turns() -> None:
    service = make_service()
    for index in range(1, 10):
        add_round(service, index)
        assert service.maybe_generate_candidate(user_id="user_1", thread_id="thread_1") is None

    add_round(service, 10)
    candidate = service.maybe_generate_candidate(user_id="user_1", thread_id="thread_1")

    assert candidate is not None
    assert candidate.status == CandidateStatus.PENDING.value
    assert candidate.metadata_json["turn_count"] == 10
    assert "偏好：" in candidate.content
    assert "常用计划模板：" in candidate.content
    assert "决策规则：" in candidate.content
    assert "长期目标：" in candidate.content
    assert "提醒规则：" in candidate.content
    assert "第 1 轮" not in candidate.content


def test_does_not_duplicate_candidate_for_same_turn_count() -> None:
    service = make_service()
    for index in range(1, 11):
        add_round(service, index)

    first = service.maybe_generate_candidate(user_id="user_1", thread_id="thread_1")
    second = service.maybe_generate_candidate(user_id="user_1", thread_id="thread_1")

    assert first is not None
    assert second is None
    assert len(service.list_candidates("user_1")) == 1


def test_approve_candidate_enables_skill_and_disable_hides_context() -> None:
    service = make_service()
    for index in range(1, 11):
        add_round(service, index)
    candidate = service.maybe_generate_candidate(user_id="user_1", thread_id="thread_1")
    assert candidate is not None

    approved, skill = service.approve_candidate(candidate.id, user_id="user_1")

    assert approved.status == CandidateStatus.APPROVED.value
    assert skill.status == SkillStatus.ENABLED.value
    assert service.relevant_skill_context("user_1", "帮我规划 Python 学习")[0]["id"] == skill.id

    disabled = service.disable_skill(skill.id, user_id="user_1")
    assert disabled.status == SkillStatus.DISABLED.value
    assert service.relevant_skill_context("user_1", "帮我规划 Python 学习") == []


def test_reject_candidate_does_not_enable_skill() -> None:
    service = make_service()
    for index in range(1, 11):
        add_round(service, index)
    candidate = service.maybe_generate_candidate(user_id="user_1", thread_id="thread_1")
    assert candidate is not None

    rejected = service.reject_candidate(candidate.id, user_id="user_1")

    assert rejected.status == CandidateStatus.REJECTED.value
    assert service.list_skills("user_1") == []
