import pytest

from backend.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_health(client, monkeypatch):
    class FakeConnection:
        def close(self):
            pass

    monkeypatch.setattr("backend.app.get_db_connection", lambda: FakeConnection())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "database": "connected"}

def test_index(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.content_type.startswith("text/html")


def test_missing_frontend_file(client):
    response = client.get("/nonexistent-file.js")

    assert response.status_code == 404
