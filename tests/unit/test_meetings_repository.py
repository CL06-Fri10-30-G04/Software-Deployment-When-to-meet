from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from backend.app.db.exceptions import ValidationError
from backend.app.db.models import FinalSlot, Meeting, Participant, Slot
from backend.app.db.repositories.meetings import (
    _validate_date,
    _validate_id,
    _validate_invite_rules,
    _validate_slot,
)


def test_meeting_model_requires_creator_participant_and_matching_participant_ids():
    creator_id = str(uuid4())
    meeting = {
        "id": str(uuid4()),
        "type": "meeting",
        "name": "Planning",
        "creatorId": creator_id,
        "durationMinutes": 30,
        "earliestDate": "2026-11-01",
        "latestDate": "2026-11-30",
        "inviteRules": {
            "includeRoles": [],
            "excludeRoles": [],
            "includeUserIds": [],
            "excludeUserIds": [],
        },
        "participants": [
            {
                "userId": creator_id,
                "name": "Creator",
                "role": "Staff",
                "response": "accepted",
            }
        ],
        "participantIds": [creator_id],
        "candidateSlots": [],
        "status": "scheduling",
        "finalSlot": None,
        "createdAt": "2026-10-19T00:00:00+00:00",
        "updatedAt": "2026-10-19T00:00:00+00:00",
    }

    assert Meeting.model_validate(meeting).creatorId == creator_id
    with pytest.raises(PydanticValidationError):
        Meeting.model_validate({**meeting, "latestDate": "2026-10-31"})
    with pytest.raises(PydanticValidationError):
        Meeting.model_validate({**meeting, "participantIds": []})


def test_slot_and_final_slot_models_validate_utc_ranges_and_counts():
    start = datetime(2026, 11, 3, 1, tzinfo=timezone.utc)
    user_id = str(uuid4())
    slot = Slot.model_validate(
        {
            "start": start,
            "end": start + timedelta(minutes=30),
            "availableCount": 1,
            "availableUserIds": [user_id],
            "unavailableUserIds": [],
        }
    )
    final_slot = FinalSlot.model_validate(
        {
            "start": slot.start,
            "end": slot.end,
            "forced": False,
            "unavailableUserIds": [],
        }
    )

    assert final_slot.start.utcoffset() == timedelta(0)
    with pytest.raises(PydanticValidationError):
        Slot.model_validate(
            {
                "start": start,
                "end": start + timedelta(minutes=30),
                "availableCount": 2,
                "availableUserIds": [user_id],
                "unavailableUserIds": [],
            }
        )


def test_meeting_repository_pure_validation_for_ids_dates_invites_and_slots():
    included = str(uuid4())
    assert _validate_id(included, "user_id") == included
    assert _validate_date("2026-11-30", "latestDate") == "2026-11-30"
    assert _validate_invite_rules(
        ["Staff", "Staff"], [], [included, included], []
    ) == {
        "includeRoles": ["Staff"],
        "excludeRoles": [],
        "includeUserIds": [included],
        "excludeUserIds": [],
    }
    with pytest.raises(ValidationError):
        _validate_date("2026-02-30", "earliestDate")
    with pytest.raises(ValidationError):
        _validate_id("not-a-uuid", "user_id")
    with pytest.raises(ValidationError):
        _validate_invite_rules(["Unknown"], [], [], [])

    with pytest.raises(ValidationError):
        _validate_slot({"start": "not-a-time"})


def test_participant_model_validates_response_enum():
    user_id = str(uuid4())
    participant = Participant.model_validate(
        {"userId": user_id, "name": "Pat", "role": None, "response": "pending"}
    )
    assert participant.userId == user_id
    with pytest.raises(PydanticValidationError):
        Participant.model_validate(
            {"userId": user_id, "name": "Pat", "role": None, "response": "maybe"}
        )
