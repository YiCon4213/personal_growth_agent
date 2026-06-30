import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app


def production_settings(**overrides) -> Settings:
    values = {
        "environment": "production",
        "allowed_hosts": "testserver",
        "cors_allowed_origins": "https://app.example.test",
        "database_url": "sqlite+pysqlite:///:memory:",
        "max_request_body_bytes": 1024,
        "rate_limit_requests_per_minute": 20,
    }
    values.update(overrides)
    return Settings(**values)


def test_production_rejects_wildcard_host_and_cors() -> None:
    with pytest.raises(ValidationError, match="ALLOWED_HOSTS"):
        Settings(environment="production", allowed_hosts="*")
    with pytest.raises(ValidationError, match="CORS_ALLOWED_ORIGINS"):
        Settings(environment="production", cors_allowed_origins="*")


def test_invalid_trusted_proxy_cidr_fails_at_startup() -> None:
    with pytest.raises(ValidationError):
        Settings(trusted_proxy_cidrs="not-a-network")

def test_security_headers_request_id_and_docs_disabled() -> None:
    client = TestClient(create_app(settings=production_settings()))

    response = client.get("/api/v1/health", headers={"X-Request-ID": "request-12345678"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "request-12345678"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    assert client.get("/docs").status_code == 404


def test_trusted_host_and_explicit_cors_origin() -> None:
    client = TestClient(create_app(settings=production_settings()))

    rejected = client.get("/api/v1/health", headers={"Host": "evil.example"})
    preflight = client.options(
        "/api/v1/contracts/schema-catalog",
        headers={
            "Origin": "https://app.example.test",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert rejected.status_code == 400
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "https://app.example.test"


def test_request_body_limit_rejects_declared_and_streamed_oversize_payloads() -> None:
    client = TestClient(create_app(settings=production_settings()))
    payload = json.dumps({"message": "x" * 2000, "thread_id": "thread"})

    response = client.post(
        "/api/v1/chat/stream",
        content=payload,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Request body exceeds the configured limit."


def test_rate_limit_returns_retry_after() -> None:
    client = TestClient(
        create_app(settings=production_settings(rate_limit_requests_per_minute=2))
    )

    assert client.get("/api/v1/contracts/schema-catalog").status_code == 200
    assert client.get("/api/v1/contracts/schema-catalog").status_code == 200
    limited = client.get("/api/v1/contracts/schema-catalog")

    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1


def test_readiness_checks_database_connection() -> None:
    client = TestClient(create_app(settings=production_settings()))

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
