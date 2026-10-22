def test_get_and_put_availability(make_user, login_as):
    user_client = login_as(make_user())

    initial = user_client.get("/api/me/availability")
    updated = user_client.put(
        "/api/me/availability",
        json={"availability": [{"dayOfWeek": 2, "start": "10:00", "end": "12:00"}]},
    )

    assert initial.status_code == 200
    assert initial.json()["timezone"] == "UTC"
    assert len(initial.json()["availability"]) == 5
    assert updated.status_code == 200
    assert updated.json()["availability"] == [
        {"dayOfWeek": 2, "start": "10:00", "end": "12:00"}
    ]


def test_add_and_remove_unavailability(make_user, login_as):
    user_client = login_as(make_user())

    created = user_client.post(
        "/api/me/unavailability",
        json={
            "label": "Gym",
            "type": "recurring",
            "daysOfWeek": [1, 3],
            "startTime": "07:00",
            "endTime": "08:00",
            "recurUntil": None,
        },
    )
    item_id = created.json()["id"]
    deleted = user_client.delete(f"/api/me/unavailability/{item_id}")
    deleted_again = user_client.delete(f"/api/me/unavailability/{item_id}")

    assert created.status_code == 201
    assert created.json()["label"] == "Gym"
    assert deleted.status_code == 204
    assert user_client.get("/api/me/availability").json()["unavailability"] == []
    assert deleted_again.status_code == 404
