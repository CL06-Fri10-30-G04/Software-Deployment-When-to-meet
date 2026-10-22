def test_register_returns_user_without_password_hash_and_logs_in(client, password):
    response = client.post(
        "/api/auth/register",
        json={
            "name": "Sam",
            "email": "Sam@Example.com",
            "password": password,
            "role": "Manager",
            "timezone": "UTC",
        },
    )

    assert response.status_code == 201
    user = response.json()
    assert user["email"] == "sam@example.com"
    assert "passwordHash" not in user
    assert client.get("/api/auth/me").json()["id"] == user["id"]


def test_login_sets_session_and_me_returns_the_user(client, make_user, password):
    user = make_user()

    response = client.post(
        "/api/auth/login", json={"email": user["email"], "password": password}
    )

    assert response.status_code == 200
    assert response.json()["id"] == user["id"]
    assert "passwordHash" not in response.json()
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == user["id"]
    assert "passwordHash" not in me.json()


def test_login_rejects_wrong_password_and_unknown_email(client, make_user, password):
    user = make_user()

    wrong_password = client.post(
        "/api/auth/login", json={"email": user["email"], "password": "nope"}
    )
    unknown_email = client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": password}
    )

    for response in (wrong_password, unknown_email):
        assert response.status_code == 401
        assert response.json()["error"] == "invalid_credentials"
    assert client.get("/api/auth/me").status_code == 401


def test_logout_clears_the_session(make_user, login_as):
    user_client = login_as(make_user())

    response = user_client.post("/api/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert user_client.get("/api/auth/me").status_code == 401


def test_me_without_session_is_unauthenticated(client):
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json() == {
        "error": "unauthenticated",
        "message": "Authentication required.",
    }


def test_protected_route_without_session_is_unauthenticated(client):
    response = client.get("/api/meetings")

    assert response.status_code == 401
    assert response.json()["error"] == "unauthenticated"


def test_tampered_session_cookie_is_rejected(client, make_user, login_as):
    user_client = login_as(make_user())
    cookie = user_client.cookies.get("session")

    client.cookies.set("session", cookie[:-4] + "AAAA")

    assert client.get("/api/auth/me").status_code == 401


def test_list_users_never_returns_password_hashes(make_user, login_as):
    user = make_user("Alex")
    make_user("Blair")

    response = login_as(user).get("/api/users")

    assert response.status_code == 200
    assert {item["name"] for item in response.json()} == {"Alex", "Blair"}
    assert all("passwordHash" not in item for item in response.json())
