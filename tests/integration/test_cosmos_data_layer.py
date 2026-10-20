from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
import pytest
from azure.core import MatchConditions
from azure.cosmos.container import ContainerProxy
from azure.cosmos.exceptions import CosmosHttpResponseError

from backend.app.db.exceptions import (
    DuplicateEmailError,
    ParticipantsUnavailable,
    PermissionDenied,
)
from backend.app.db.repositories.meetings import (
    add_participant,
    create_meeting,
    finalise_meeting,
    list_meetings_for_user,
    set_candidate_slots,
    update_meeting,
)
from backend.app.db.repositories.users import (
    add_unavailability,
    create_user,
    get_user_by_id,
    get_user_for_auth,
    remove_unavailability,
    set_availability,
)
from backend.app.db.setup import ensure_database


def _create_user(db, name, role="Staff"):
    return create_user(
        db,
        name,
        f"{uuid4().hex}@example.com",
        "integration password",
        role=role,
    )


def _create_meeting(db, creator_id, participant_ids=None, **rules):
    return create_meeting(
        db,
        creator_id,
        "Integration meeting",
        30,
        "2026-11-01",
        "2026-11-30",
        rules.get("include_roles", []),
        rules.get("exclude_roles", []),
        participant_ids or [],
        rules.get("exclude_user_ids", []),
    )


def test_unique_email_is_enforced_by_cosmos(cosmos_db):
    email = f"{uuid4().hex}@example.com"
    create_user(cosmos_db, "First", email, "integration password")

    with pytest.raises(DuplicateEmailError):
        create_user(cosmos_db, "Second", email.upper(), "integration password")


def test_user_array_updates_are_persisted(cosmos_db):
    user = _create_user(cosmos_db, "Availability")
    set_availability(
        cosmos_db,
        user["id"],
        [{"dayOfWeek": 1, "start": "08:30", "end": "12:30"}],
    )
    start = datetime(2026, 11, 3, 1, tzinfo=timezone.utc)
    item_id = add_unavailability(
        cosmos_db,
        user["id"],
        {
            "label": "Appointment",
            "type": "once",
            "start": start,
            "end": start + timedelta(hours=1),
        },
    )
    assert len(get_user_by_id(cosmos_db, user["id"])["unavailability"]) == 1

    remove_unavailability(cosmos_db, user["id"], item_id)

    saved = get_user_by_id(cosmos_db, user["id"])
    assert saved["availability"] == [
        {"dayOfWeek": 1, "start": "08:30", "end": "12:30"}
    ]
    assert saved["unavailability"] == []


def test_etag_conflict_retries_and_preserves_nested_update(cosmos_db, monkeypatch):
    user = _create_user(cosmos_db, "Before race")
    original_replace = ContainerProxy.replace_item
    conflict_injected = False

    def inject_conflict(proxy, *args, **kwargs):
        nonlocal conflict_injected
        item_id = kwargs.get("item", args[0] if args else None)
        if not conflict_injected and item_id == user["id"]:
            current = proxy.read_item(item=item_id, partition_key=user["email"])
            latest = {
                key: value
                for key, value in current.items()
                if key not in {"_rid", "_self", "_ts", "_attachments", "_etag"}
            }
            latest["name"] = "Concurrent update"
            original_replace(
                proxy,
                item=item_id,
                body=latest,
                etag=current["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
            conflict_injected = True
        return original_replace(proxy, *args, **kwargs)

    monkeypatch.setattr(ContainerProxy, "replace_item", inject_conflict)
    set_availability(
        cosmos_db,
        user["id"],
        [{"dayOfWeek": 2, "start": "10:00", "end": "11:00"}],
    )

    saved = get_user_by_id(cosmos_db, user["id"])
    assert conflict_injected
    assert saved["name"] == "Concurrent update"
    assert saved["availability"] == [
        {"dayOfWeek": 2, "start": "10:00", "end": "11:00"}
    ]


def test_password_hash_is_not_exposed_by_user_read_and_auth_still_works(cosmos_db):
    user = _create_user(cosmos_db, "Auth")

    assert "passwordHash" not in get_user_by_id(cosmos_db, user["id"])
    auth_user = get_user_for_auth(cosmos_db, user["email"])
    assert bcrypt.checkpw(b"integration password", auth_user["passwordHash"].encode())


def test_invite_rules_snapshots_and_creator_inclusion(cosmos_db):
    creator = _create_user(cosmos_db, "Creator", role="Admin")
    role_match = _create_user(cosmos_db, "Role match", role="Staff")
    custom_invitee = _create_user(cosmos_db, "Custom", role="Junior Staff")

    meeting = create_meeting(
        cosmos_db,
        creator["id"],
        "Invite rules",
        30,
        "2026-11-01",
        "2026-11-30",
        ["Staff"],
        [],
        [custom_invitee["id"]],
        [],
    )

    assert set(meeting["participantIds"]) == {creator["id"], custom_invitee["id"]}
    assert role_match["id"] not in meeting["participantIds"]
    custom_snapshot = next(
        participant
        for participant in meeting["participants"]
        if participant["userId"] == custom_invitee["id"]
    )
    assert custom_snapshot["name"] == "Custom"
    assert custom_snapshot["role"] == "Junior Staff"
    assert custom_snapshot["response"] == "pending"


def test_array_contains_listing_and_participant_add_is_idempotent(cosmos_db):
    creator = _create_user(cosmos_db, "Meeting creator", role="Admin")
    invitee = _create_user(cosmos_db, "Invitee")
    other = _create_user(cosmos_db, "Other")
    meeting = _create_meeting(cosmos_db, creator["id"], [invitee["id"]])

    assert [item["id"] for item in list_meetings_for_user(cosmos_db, invitee["id"])] == [
        meeting["id"]
    ]
    assert list_meetings_for_user(cosmos_db, other["id"]) == []

    added = add_participant(cosmos_db, meeting["id"], creator["id"], other["id"])
    timestamp = added["updatedAt"]
    repeated = add_participant(cosmos_db, meeting["id"], creator["id"], other["id"])

    assert repeated["updatedAt"] == timestamp
    assert repeated["participantIds"].count(other["id"]) == 1
    assert len(repeated["participants"]) == len(repeated["participantIds"])


def test_non_editor_cannot_update_meeting(cosmos_db):
    creator = _create_user(cosmos_db, "Creator")
    actor = _create_user(cosmos_db, "Unauthorized")
    meeting = _create_meeting(cosmos_db, creator["id"])

    with pytest.raises(PermissionDenied):
        update_meeting(
            cosmos_db,
            meeting["id"],
            actor["id"],
            {"name": "Not allowed"},
        )


def test_finalization_rejects_unavailable_unless_forced(cosmos_db):
    creator = _create_user(cosmos_db, "Creator", role="Admin")
    participant = _create_user(cosmos_db, "Participant")
    meeting = _create_meeting(cosmos_db, creator["id"], [participant["id"]])
    start = datetime(2026, 11, 3, 1, tzinfo=timezone.utc)
    slot = {
        "start": start,
        "end": start + timedelta(minutes=30),
        "availableCount": 1,
        "availableUserIds": [creator["id"]],
        "unavailableUserIds": [participant["id"]],
    }
    set_candidate_slots(cosmos_db, meeting["id"], [slot])

    with pytest.raises(ParticipantsUnavailable):
        finalise_meeting(
            cosmos_db,
            meeting["id"],
            creator["id"],
            {"start": start, "end": slot["end"]},
        )

    finalized = finalise_meeting(
        cosmos_db,
        meeting["id"],
        creator["id"],
        {"start": start, "end": slot["end"]},
        force=True,
    )
    assert finalized["finalSlot"]["forced"] is True
    assert finalized["finalSlot"]["unavailableUserIds"] == [participant["id"]]


def test_finalization_succeeds_without_force_when_everyone_is_available(cosmos_db):
    creator = _create_user(cosmos_db, "Available", role="Admin")
    meeting = _create_meeting(cosmos_db, creator["id"])
    start = datetime(2026, 11, 4, 1, tzinfo=timezone.utc)
    slot = {
        "start": start,
        "end": start + timedelta(minutes=30),
        "availableCount": 1,
        "availableUserIds": [creator["id"]],
        "unavailableUserIds": [],
    }
    set_candidate_slots(cosmos_db, meeting["id"], [slot])

    finalized = finalise_meeting(
        cosmos_db,
        meeting["id"],
        creator["id"],
        {"start": start, "end": slot["end"]},
    )

    assert finalized["status"] == "scheduled"
    assert finalized["finalSlot"]["forced"] is False
    assert finalized["finalSlot"]["unavailableUserIds"] == []


def test_ensure_database_is_idempotent(cosmos_client, cosmos_db):
    database = ensure_database(cosmos_client)
    assert database.id == cosmos_db.id
    assert database.get_container_client("users").read()["partitionKey"]["paths"] == [
        "/email"
    ]
    assert database.get_container_client("meetings").read()["partitionKey"]["paths"] == [
        "/id"
    ]


@pytest.mark.cosmos_smoke
def test_staging_cosmos_create_read_delete_smoke():
    import os

    from backend.app.db.connection import create_client

    required = ("COSMOS_ENDPOINT", "COSMOS_KEY", "COSMOS_DB_NAME")
    if (
        os.getenv("COSMOS_SMOKE_ENABLED", "").lower() != "true"
        or not all(os.getenv(name) for name in required)
    ):
        pytest.skip("Staging Cosmos smoke-test settings are not configured")
    client = create_client()
    item_id = str(uuid4())
    container = client.get_database_client(
        os.environ["COSMOS_DB_NAME"]
    ).get_container_client("meetings")
    document = {
        "id": item_id,
        "type": "smoke",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    try:
        container.create_item(body=document)
        assert container.read_item(item=item_id, partition_key=item_id)["id"] == item_id
    finally:
        try:
            container.delete_item(item=item_id, partition_key=item_id)
        except CosmosHttpResponseError as error:
            if error.status_code != 404:
                raise
        client.close()
