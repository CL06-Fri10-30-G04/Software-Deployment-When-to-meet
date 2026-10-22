from backend.app.db.repositories.users import set_availability


def test_list_meetings_returns_only_the_users_meetings(make_user, login_as, meeting_for):
    alex = make_user("Alex")
    blair = make_user("Blair")
    mine = meeting_for(alex)
    meeting_for(blair)

    response = login_as(alex).get("/api/meetings")

    assert response.status_code == 200
    assert [meeting["id"] for meeting in response.json()] == [mine["id"]]


def test_create_meeting_makes_creator_an_accepted_participant(make_user, login_as):
    creator = make_user("Creator")
    invitee = make_user("Invitee")

    response = login_as(creator).post(
        "/api/meetings",
        json={
            "name": "Planning",
            "durationMinutes": 30,
            "earliestDate": "2026-11-02",
            "latestDate": "2026-11-06",
            "includeRoles": [],
            "excludeRoles": [],
            "includeUserIds": [invitee["id"]],
            "excludeUserIds": [],
        },
    )

    assert response.status_code == 201
    meeting = response.json()
    assert meeting["creatorId"] == creator["id"]
    assert meeting["status"] == "scheduling"
    assert {(p["userId"], p["response"]) for p in meeting["participants"]} == {
        (creator["id"], "accepted"),
        (invitee["id"], "pending"),
    }


def test_get_meeting_returns_it_to_a_participant(make_user, login_as, meeting_for):
    creator = make_user("Creator")
    invitee = make_user("Invitee")
    meeting = meeting_for(creator, [invitee])

    response = login_as(invitee).get(f"/api/meetings/{meeting['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == meeting["id"]


def test_add_participant(make_user, login_as, meeting_for):
    creator = make_user("Creator")
    newcomer = make_user("Newcomer")
    meeting = meeting_for(creator)

    response = login_as(creator).post(
        f"/api/meetings/{meeting['id']}/participants", json={"userId": newcomer["id"]}
    )

    assert response.status_code == 200
    assert newcomer["id"] in response.json()["participantIds"]


def test_remove_participant(make_user, login_as, meeting_for):
    creator = make_user("Creator")
    invitee = make_user("Invitee")
    meeting = meeting_for(creator, [invitee])

    response = login_as(creator).delete(
        f"/api/meetings/{meeting['id']}/participants/{invitee['id']}"
    )

    assert response.status_code == 200
    assert response.json()["participantIds"] == [creator["id"]]


def test_respond_to_meeting(make_user, login_as, meeting_for):
    creator = make_user("Creator")
    invitee = make_user("Invitee")
    meeting = meeting_for(creator, [invitee])

    response = login_as(invitee).post(
        f"/api/meetings/{meeting['id']}/respond", json={"response": "declined"}
    )

    assert response.status_code == 200
    responses = {p["userId"]: p["response"] for p in response.json()["participants"]}
    assert responses[invitee["id"]] == "declined"


def test_cancel_meeting(make_user, login_as, meeting_for):
    creator = make_user("Creator")
    meeting = meeting_for(creator)

    response = login_as(creator).post(f"/api/meetings/{meeting['id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_find_slots_saves_candidate_slots(make_user, login_as, meeting_for):
    creator = make_user("Creator")
    invitee = make_user("Invitee")
    meeting = meeting_for(creator, [invitee])

    response = login_as(creator).post(f"/api/meetings/{meeting['id']}/find-slots")

    assert response.status_code == 200
    slots = response.json()["candidateSlots"]
    assert 0 < len(slots) <= 10
    assert slots[0]["availableCount"] == 2
    assert set(slots[0]["availableUserIds"]) == {creator["id"], invitee["id"]}


def test_finalise_meeting(make_user, login_as, meeting_for):
    creator = make_user("Creator")
    meeting = meeting_for(creator)
    creator_client = login_as(creator)
    slot = creator_client.post(f"/api/meetings/{meeting['id']}/find-slots").json()[
        "candidateSlots"
    ][0]

    response = creator_client.post(
        f"/api/meetings/{meeting['id']}/finalise",
        json={"slot": {"start": slot["start"], "end": slot["end"]}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "scheduled"
    assert body["finalSlot"]["start"] == slot["start"]
    assert body["finalSlot"]["forced"] is False


def test_finalise_with_force_records_unavailable_participants(
    db, make_user, login_as, meeting_for
):
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
        json={"slot": {"start": slot["start"], "end": slot["end"]}, "force": True},
    )

    assert response.status_code == 200
    assert response.json()["finalSlot"]["forced"] is True
    assert response.json()["finalSlot"]["unavailableUserIds"] == [busy["id"]]
