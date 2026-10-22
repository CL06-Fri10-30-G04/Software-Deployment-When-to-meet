from uuid import uuid4

from backend.app.db.repositories.users import set_availability


def assert_error(response, status_code, error):
    assert response.status_code == status_code, response.text
    body = response.json()
    assert set(body) == {"error", "message"}
    assert body["error"] == error
    assert body["message"]


def test_invalid_request_body_is_validation_error(make_user, login_as):
    user_client = login_as(make_user())

    response = user_client.post(
        "/api/meetings",
        json={"durationMinutes": 30, "earliestDate": "2026-11-02", "latestDate": "2026-11-03"},
    )

    assert_error(response, 400, "validation_error")
    assert "name" in response.json()["message"]


def test_repository_validation_error_is_validation_error(make_user, login_as, meeting_for):
    creator = make_user()
    meeting = meeting_for(creator)

    response = login_as(creator).delete(
        f"/api/meetings/{meeting['id']}/participants/{creator['id']}"
    )

    assert_error(response, 400, "validation_error")


def test_duplicate_email_is_conflict(client, make_user, password):
    make_user(email="taken@example.com")

    response = client.post(
        "/api/auth/register",
        json={"name": "Copy", "email": "taken@example.com", "password": password},
    )

    assert_error(response, 409, "duplicate_email")


def test_permission_denied_is_forbidden(make_user, login_as, meeting_for):
    creator = make_user("Creator")
    staff = make_user("Staff Member", role="Staff")
    meeting = meeting_for(creator, [staff])

    response = login_as(staff).post(f"/api/meetings/{meeting['id']}/cancel")

    assert_error(response, 403, "forbidden")


def test_missing_meeting_is_not_found(make_user, login_as):
    response = login_as(make_user()).get(f"/api/meetings/{uuid4()}")

    assert_error(response, 404, "not_found")


def test_unknown_api_route_is_not_found(make_user, login_as):
    response = login_as(make_user()).get("/api/does-not-exist")

    assert_error(response, 404, "not_found")


def test_unavailable_participants_is_conflict(db, make_user, login_as, meeting_for):
    creator = make_user("Creator")
    busy = make_user("Busy")
    set_availability(db, busy["id"], [])
    meeting = meeting_for(creator, [busy])
    creator_client = login_as(creator)
    slot = creator_client.post(f"/api/meetings/{meeting['id']}/find-slots").json()[
        "candidateSlots"
    ][0]

    response = creator_client.post(
        f"/api/meetings/{meeting['id']}/finalise",
        json={"slot": {"start": slot["start"], "end": slot["end"]}, "force": False},
    )

    assert_error(response, 409, "participants_unavailable")


def test_concurrency_error_is_conflict(db, make_user, login_as, meeting_for):
    creator = make_user()
    meeting = meeting_for(creator)
    creator_client = login_as(creator)
    db.containers["meetings"].always_conflict = True

    response = creator_client.post(f"/api/meetings/{meeting['id']}/cancel")

    assert_error(response, 409, "concurrency_conflict")
