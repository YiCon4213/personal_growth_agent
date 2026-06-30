from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.db.models import Base
from app.main import create_app
from app.services.skill_service import SkillService


def make_client_with_session() -> tuple[TestClient, Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = session_factory()
    app = create_app()

    def override_get_session() -> Generator[Session, None, None]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), session


def add_ten_rounds(service: SkillService) -> str:
    for index in range(1, 11):
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
    candidate = service.maybe_generate_candidate(user_id="user_1", thread_id="thread_1")
    assert candidate is not None
    return candidate.id


def test_skill_candidate_approve_and_disable_flow_api() -> None:
    client, session = make_client_with_session()
    service = SkillService(session)
    candidate_id = add_ten_rounds(service)
    session.commit()

    pending_response = client.get("/api/v1/skills/candidates", params={"user_id": "user_1"})
    assert pending_response.status_code == 200
    assert pending_response.json()[0]["id"] == candidate_id

    approve_response = client.post(
        f"/api/v1/skills/candidates/{candidate_id}/approve",
        json={"user_id": "user_1"},
    )
    assert approve_response.status_code == 200
    body = approve_response.json()
    assert body["candidate"]["status"] == "approved"
    assert body["skill"]["status"] == "enabled"

    skills_response = client.get("/api/v1/skills", params={"user_id": "user_1"})
    assert skills_response.status_code == 200
    skill = skills_response.json()[0]
    assert skill["id"] == body["skill"]["id"]

    disable_response = client.post(f"/api/v1/skills/{skill['id']}/disable", params={"user_id": "user_1"})
    assert disable_response.status_code == 200
    assert disable_response.json()["status"] == "disabled"
    assert client.get("/api/v1/skills", params={"user_id": "user_1"}).json() == []


def test_skill_candidate_reject_flow_api() -> None:
    client, session = make_client_with_session()
    service = SkillService(session)
    candidate_id = add_ten_rounds(service)
    session.commit()

    reject_response = client.post(
        f"/api/v1/skills/candidates/{candidate_id}/reject",
        json={"user_id": "user_1"},
    )

    assert reject_response.status_code == 200
    assert reject_response.json()["candidate"]["status"] == "rejected"
    assert client.get("/api/v1/skills", params={"user_id": "user_1"}).json() == []
