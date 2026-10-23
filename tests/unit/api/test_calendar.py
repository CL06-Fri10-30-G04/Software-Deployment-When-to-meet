import pytest

# meeting_for() makes meetings for Mon 2 - Tue 3 Nov 2026.
WEEK = {"start": "2026-11-02T00:00:00Z", "end": "2026-11-09T00:00:00Z"}


def calendar(client, **params):
    response = client.get("/api/calendar", params={**WEEK, **params})
    assert response.status_code == 200, response.text
    return response.json()["items"]


def ids(items):
    return {item["id"] for item in items}


def schedule(client, meeting):
    """Find slots and finalise the best one; returns the scheduled meeting."""
    slot = client.post(f"/api/meetings/{meeting['id']}/find-slots").json()["candidateSlots"][0]
    response = client.post(
        f"/api/meetings/{meeting['id']}/finalise",
        json={"slot": {"start": slot["start"], "end": slot["end"]}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_calendar_requires_login(client):
    response = client.get("/api/calendar", params=WEEK)

    assert response.status_code == 401


def test_shows_only_my_meetings_in_the_range(make_user, login_as, meeting_for):
    alex = make_user("Alex")
    mine = meeting_for(alex)
    meeting_for(make_user("Blair"))
    alex_client = login_as(alex)

    items = calendar(alex_client)
    december = calendar(alex_client, start="2026-12-01T00:00:00Z", end="2026-12-08T00:00:00Z")

    assert ids(items) == {mine["id"]}
    item = items[0]
    assert item["status"] == "scheduling"
    assert item["start"] is None
    assert (item["earliestDate"], item["latestDate"]) == ("2026-11-02", "2026-11-03")
    assert item["myResponse"] == "accepted"
    assert item["creatorName"] == "Alex"
    assert december == []


def test_scheduled_meetings_use_their_final_time(make_user, login_as, meeting_for):
    creator = make_user("Creator")
    creator_client = login_as(creator)
    scheduled = schedule(creator_client, meeting_for(creator))
    slot_start = scheduled["finalSlot"]["start"]

    items = calendar(creator_client)
    after_slot = calendar(creator_client, start=scheduled["finalSlot"]["end"], end="2026-11-04T00:00:00Z")

    assert items[0]["start"] == slot_start
    assert items[0]["status"] == "scheduled"
    assert after_slot == []


def test_response_filters_use_my_reply(make_user, login_as, meeting_for):
    creator = make_user("Creator")
    invitee = make_user("Invitee")
    meeting = meeting_for(creator, [invitee])
    own = meeting_for(invitee)
    invitee_client = login_as(invitee)

    assert ids(calendar(invitee_client, show="invited")) == {meeting["id"]}
    assert ids(calendar(invitee_client, show="attending")) == {own["id"]}
    assert ids(calendar(invitee_client, show="created")) == {own["id"]}

    invitee_client.post(f"/api/meetings/{meeting['id']}/respond", json={"response": "declined"})

    assert ids(calendar(invitee_client, show="declined")) == {meeting["id"]}
    assert ids(calendar(invitee_client, show="all")) == {meeting["id"], own["id"]}


def test_role_filter_matches_any_participant_role(make_user, login_as, meeting_for):
    creator = make_user("Creator", role="Staff")
    with_manager = meeting_for(creator, [make_user("Morgan", role="Manager")])
    staff_only = meeting_for(creator)
    creator_client = login_as(creator)

    assert ids(calendar(creator_client, role="Manager")) == {with_manager["id"]}
    assert ids(calendar(creator_client, role="Staff")) == {with_manager["id"], staff_only["id"]}
    assert calendar(creator_client, role="Junior Staff") == []


def test_everyone_scope_is_for_admins_and_managers(make_user, login_as, meeting_for):
    others = meeting_for(make_user("Blair"))
    staff_client = login_as(make_user("Sam", role="Staff"))
    manager_client = login_as(make_user("Morgan", role="Manager"))

    forbidden = staff_client.get("/api/calendar", params={**WEEK, "scope": "everyone"})
    items = calendar(manager_client, scope="everyone")

    assert forbidden.status_code == 403
    assert forbidden.json()["error"] == "forbidden"
    assert ids(items) == {others["id"]}
    assert items[0]["myResponse"] is None


def test_cancelled_meetings_are_hidden_unless_asked_for(make_user, login_as, meeting_for):
    creator = make_user("Creator")
    meeting = meeting_for(creator)
    creator_client = login_as(creator)
    creator_client.post(f"/api/meetings/{meeting['id']}/cancel")

    assert calendar(creator_client) == []
    assert calendar(creator_client, cancelled="true")[0]["status"] == "cancelled"


@pytest.mark.parametrize(
    "params",
    [
        {"start": "2026-11-09T00:00:00Z", "end": "2026-11-02T00:00:00Z"},
        {"start": "2026-01-01T00:00:00Z", "end": "2026-06-01T00:00:00Z"},
        {**WEEK, "show": "everything"},
        {**WEEK, "role": "Intern"},
        {"start": "not-a-date", "end": "2026-11-02T00:00:00Z"},
    ],
)
def test_invalid_queries_are_validation_errors(make_user, login_as, params):
    response = login_as(make_user()).get("/api/calendar", params=params)

    assert response.status_code == 400
    assert response.json()["error"] == "validation_error"
