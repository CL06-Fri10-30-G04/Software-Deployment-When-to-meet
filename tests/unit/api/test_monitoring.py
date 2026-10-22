def test_live_metrics_require_login(client):
    response = client.get("/api/monitoring/live")

    assert response.status_code == 401
    assert response.json()["error"] == "unauthenticated"


def test_live_and_azure_metrics_are_admin_only(make_user, login_as):
    manager_client = login_as(make_user("Mo", role="Manager"))

    for path in ("/api/monitoring/live", "/api/monitoring/azure"):
        response = manager_client.get(path)
        assert response.status_code == 403
        assert response.json()["error"] == "forbidden"


def test_admin_gets_live_system_and_request_metrics(make_user, login_as):
    admin_client = login_as(make_user("Ada", role="Admin"))
    admin_client.get("/api/auth/me")

    response = admin_client.get("/api/monitoring/live")

    assert response.status_code == 200
    body = response.json()
    latest = body["system"]["latest"]
    for key in (
        "cpuPercent",
        "memoryBytes",
        "memoryPercent",
        "diskReadBytesPerSec",
        "networkInBytesPerSec",
    ):
        assert key in latest
    routes = {(row["method"], row["route"]) for row in body["requests"]["routes"]}
    assert ("GET", "/api/auth/me") in routes
    assert not any(route.startswith("/api/monitoring") for _, route in routes)


def test_azure_metrics_report_missing_settings_when_not_configured(
    make_user, login_as, monkeypatch
):
    admin_client = login_as(make_user("Ada", role="Admin"))

    response = admin_client.get("/api/monitoring/azure?range=6h")

    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert "AZURE_MONITOR_APP_INSIGHTS_ID" in response.json()["missing"]


def test_azure_metrics_reject_unknown_range(make_user, login_as):
    admin_client = login_as(make_user("Ada", role="Admin"))

    response = admin_client.get("/api/monitoring/azure?range=7d")

    assert response.status_code == 400
    assert response.json()["error"] == "validation_error"


def test_monitoring_page_redirects_logged_out_visitors(client):
    response = client.get("/monitoring.html", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "login.html"


def test_monitoring_page_is_forbidden_for_non_admins(make_user, login_as):
    staff_client = login_as(make_user("Sam", role="Staff"))

    response = staff_client.get("/monitoring.html")

    assert response.status_code == 403
    assert "Only Admin users can view monitoring." in response.text
    assert "monitoring.js" not in response.text


def test_monitoring_page_is_served_to_admins(make_user, login_as):
    admin_client = login_as(make_user("Ada", role="Admin"))

    response = admin_client.get("/monitoring.html")

    assert response.status_code == 200
    assert "./js/monitoring.js" in response.text


def test_static_files_never_serve_the_monitoring_page_directly(client):
    assert client.get("/MONITORING.HTML").status_code == 404
