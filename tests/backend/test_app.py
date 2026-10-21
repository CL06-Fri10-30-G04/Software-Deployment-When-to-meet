import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


@pytest.fixture
def client():
    app = create_app(session_secret="test-session-secret")
    with TestClient(app) as client:
        yield client


def test_health(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_missing_frontend_file(client):
    response = client.get("/nonexistent-file.js")

    assert response.status_code == 404
