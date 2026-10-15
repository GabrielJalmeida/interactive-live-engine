"""Smoke tests for the initial application slice."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.main import create_app


def test_health_endpoint_reports_application_liveness() -> None:
    settings = Settings(_env_file=None, app_env="test")
    client = TestClient(create_app(settings))

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "interactive-live-engine",
        "environment": "test",
    }


def test_settings_reject_port_outside_valid_range() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_port=70000)
