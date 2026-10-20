from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from backend.app.db.models import (
    Availability,
    OnceUnavailability,
    RecurringUnavailability,
    User,
)
from backend.app.db.repositories.users import (
    DEFAULT_AVAILABILITY,
    _validate_availability,
    _validate_email,
    _validate_unavailability_item,
)
from backend.app.db.exceptions import ValidationError


def _user_document():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid4()),
        "type": "user",
        "name": "Alex",
        "email": "alex@example.com",
        "passwordHash": "bcrypt-hash",
        "role": "Staff",
        "timezone": "Australia/Melbourne",
        "availability": DEFAULT_AVAILABILITY,
        "unavailability": [],
        "createdAt": now,
        "updatedAt": now,
    }


def test_default_availability_is_weekdays_nine_to_five():
    assert DEFAULT_AVAILABILITY == [
        {"dayOfWeek": day, "start": "09:00", "end": "17:00"}
        for day in range(1, 6)
    ]


def test_user_model_requires_uuid_lowercase_email_and_known_role():
    user = User.model_validate(_user_document())

    assert user.type == "user"
    assert user.email == "alex@example.com"
    assert user.model_dump(mode="json")["createdAt"].endswith("+00:00")

    for change in (
        {"id": "not-a-uuid"},
        {"email": "Alex@example.com"},
        {"role": "Owner"},
    ):
        with pytest.raises(PydanticValidationError):
            User.model_validate({**_user_document(), **change})


def test_availability_model_validates_day_time_and_range():
    assert Availability.model_validate(
        {"dayOfWeek": 1, "start": "09:00", "end": "17:00"}
    )
    for invalid in (
        {"dayOfWeek": 7, "start": "09:00", "end": "17:00"},
        {"dayOfWeek": 1, "start": "9am", "end": "17:00"},
        {"dayOfWeek": 1, "start": "17:00", "end": "09:00"},
    ):
        with pytest.raises(PydanticValidationError):
            Availability.model_validate(invalid)


def test_one_off_and_recurring_unavailability_models():
    item_id = str(uuid4())
    start = datetime(2026, 11, 3, 1, tzinfo=timezone.utc).isoformat()
    once = OnceUnavailability.model_validate(
        {
            "id": item_id,
            "label": "Appointment",
            "type": "once",
            "start": start,
            "end": "2026-11-03T02:00:00+00:00",
        }
    )
    recurring = RecurringUnavailability.model_validate(
        {
            "id": str(uuid4()),
            "label": "Class",
            "type": "recurring",
            "daysOfWeek": [1, 3],
            "startTime": "09:00",
            "endTime": "10:00",
            "recurUntil": "2026-12-31",
        }
    )

    assert once.id == item_id
    assert recurring.daysOfWeek == [1, 3]
    with pytest.raises(PydanticValidationError):
        RecurringUnavailability.model_validate(
            {
                "id": str(uuid4()),
                "label": "Invalid",
                "type": "recurring",
                "daysOfWeek": [1, 1],
                "startTime": "09:00",
                "endTime": "10:00",
                "recurUntil": None,
            }
        )


def test_user_repository_pure_validation_normalizes_email_and_unavailability():
    assert _validate_email(" Alex@Example.com ") == "alex@example.com"
    with pytest.raises(ValidationError):
        _validate_email("not-an-email")
    with pytest.raises(ValidationError):
        _validate_availability([{"dayOfWeek": 1, "start": "17:00", "end": "09:00"}])

    item = _validate_unavailability_item(
        {
            "label": "Appointment",
            "type": "once",
            "start": datetime(2026, 11, 3, 1, tzinfo=timezone.utc),
            "end": datetime(2026, 11, 3, 2, tzinfo=timezone.utc),
        }
    )
    assert item["type"] == "once"
    assert item["id"]
