from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.db.models import Base
from app.main import create_app
from app.services.profile_service import ProfileService


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


def test_profile_candidate_approve_flow_api() -> None:
    client, session = make_client_with_session()
    service = ProfileService(session)
    candidate = service.extract_candidates_from_message(
        user_id="user_1",
        thread_id="thread_1",
        message="我每天晚上 9 点后学习效率高。",
    )[0]
    session.commit()

    pending_response = client.get("/api/v1/profile/candidates", params={"user_id": "user_1"})
    assert pending_response.status_code == 200
    assert pending_response.json()[0]["id"] == candidate.id

    approve_response = client.post(
        f"/api/v1/profile/candidates/{candidate.id}/approve",
        json={"user_id": "user_1"},
    )
    assert approve_response.status_code == 200
    body = approve_response.json()
    assert body["candidate"]["status"] == "approved"
    assert body["profile_item"]["content"] == candidate.content

    profile_response = client.get("/api/v1/profile", params={"user_id": "user_1"})
    assert profile_response.status_code == 200
    assert profile_response.json()[0]["content"] == candidate.content


def test_profile_candidate_reject_flow_api() -> None:
    client, session = make_client_with_session()
    service = ProfileService(session)
    candidate = service.extract_candidates_from_message(
        user_id="user_1",
        thread_id="thread_1",
        message="我喜欢详细、一步步解释。",
    )[0]
    session.commit()

    reject_response = client.post(
        f"/api/v1/profile/candidates/{candidate.id}/reject",
        json={"user_id": "user_1"},
    )

    assert reject_response.status_code == 200
    assert reject_response.json()["candidate"]["status"] == "rejected"
    assert client.get("/api/v1/profile", params={"user_id": "user_1"}).json() == []


def test_profile_disable_and_delete_api() -> None:
    client, session = make_client_with_session()
    service = ProfileService(session)
    candidate = service.extract_candidates_from_message(
        user_id="user_1",
        thread_id="thread_1",
        message="我每天晚上 9 点后学习效率高。",
    )[0]
    _, item = service.approve_candidate(candidate.id, user_id="user_1")
    session.commit()

    disable_response = client.post(f"/api/v1/profile/{item.id}/disable", params={"user_id": "user_1"})
    assert disable_response.status_code == 200
    assert disable_response.json()["enabled"] is False

    delete_response = client.delete(f"/api/v1/profile/{item.id}", params={"user_id": "user_1"})
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "deleted"
