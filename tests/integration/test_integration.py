import pytest

from backend.app import app, get_db_connection

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client

def test_list_meetings_returns_data(client):
    response = client.get("/api/meetings")

    assert response.status_code == 200
    assert isinstance(response.get_json(), list)

def test_create_meeting_adds_to_database(client):
    title = "Automated test meeting"
    description = "Created by pytest"

    response = client.post("/api/meetings", json={"title": title, "description": description})

    assert response.status_code == 201
    created = response.get_json()
    assert created["title"] == title
    assert created["description"] == description

    connection = get_db_connection()
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT title, description FROM meetings WHERE id = %s",
            (created["id"],),
        )
        saved = cursor.fetchone()
        cursor.close()
    finally:
        connection.close()

    assert saved == {"title": title, "description": description}