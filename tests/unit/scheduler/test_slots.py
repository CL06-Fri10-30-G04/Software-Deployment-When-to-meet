from datetime import datetime, timedelta, timezone

import pytest

from backend.app.scheduler import find_slots


UTC = timezone.utc


def user(user_id, timezone_name="UTC", availability=None, unavailability=None):
    return {
        "id": user_id,
        "timezone": timezone_name,
        "availability": availability or [],
        "unavailability": unavailability or [],
    }


def weekly(day, start="09:00", end="10:00"):
    return {"dayOfWeek": day, "start": start, "end": end}


def utc_stamp(day, hour, minute=0):
    return datetime(2026, 1, day, hour, minute, tzinfo=UTC).isoformat()


def test_single_user_returns_utc_slot_inside_availability():
    result = find_slots(
        [user("u1", availability=[weekly(4)])],
        60,
        "2026-01-01",
        "2026-01-01",
        step_minutes=60,
    )

    assert result == [
        {
            "start": "2026-01-01T09:00:00+00:00",
            "end": "2026-01-01T10:00:00+00:00",
            "availableCount": 1,
            "availableUserIds": ["u1"],
            "unavailableUserIds": [],
        }
    ]


def test_two_users_rank_overlapping_availability_first():
    users = [
        user("u1", availability=[weekly(4, "09:00", "11:00")]),
        user("u2", availability=[weekly(4, "10:00", "12:00")]),
    ]

    result = find_slots(users, 60, "2026-01-01", "2026-01-01", step_minutes=60)

    assert result[0]["start"] == "2026-01-01T10:00:00+00:00"
    assert result[0]["availableUserIds"] == ["u1", "u2"]
    assert result[0]["availableCount"] == 2


def test_users_in_different_timezones_are_evaluated_locally():
    users = [
        user("mel", "Australia/Melbourne", [weekly(4, "09:00", "10:00")]),
        user("la", "America/Los_Angeles", [weekly(4, "14:00", "15:00")]),
    ]

    result = find_slots(users, 60, "2025-12-31", "2026-01-01", step_minutes=60)

    assert {
        slot["start"]: slot["availableUserIds"] for slot in result
    } == {
        "2025-12-31T22:00:00+00:00": ["mel"],
        "2026-01-01T22:00:00+00:00": ["la"],
    }


def test_recurring_unavailability_blocks_matching_local_time_and_weekday():
    unavailable = {
        "type": "recurring",
        "daysOfWeek": [4],
        "startTime": "09:30",
        "endTime": "10:00",
        "recurUntil": "2026-01-01",
    }
    person = user(
        "u1",
        availability=[weekly(4, "09:00", "11:00")],
        unavailability=[unavailable],
    )

    result = find_slots([person], 60, "2026-01-01", "2026-01-01", step_minutes=30)

    assert [slot["start"] for slot in result] == ["2026-01-01T10:00:00+00:00"]


def test_one_off_unavailability_blocks_overlapping_slot_only():
    person = user(
        "u1",
        availability=[weekly(4, "09:00", "12:00")],
        unavailability=[
            {
                "type": "once",
                "start": "2026-01-01T10:00:00Z",
                "end": "2026-01-01T10:30:00+00:00",
            }
        ],
    )

    result = find_slots([person], 60, "2026-01-01", "2026-01-01", step_minutes=60)

    assert [slot["start"] for slot in result] == [
        "2026-01-01T09:00:00+00:00",
        "2026-01-01T11:00:00+00:00",
    ]


def test_melbourne_dst_boundary_uses_real_utc_duration():
    person = user(
        "mel",
        "Australia/Melbourne",
        [weekly(0, "01:00", "04:00")],
    )

    result = find_slots(
        [person],
        60,
        "2026-10-03",
        "2026-10-03",
        step_minutes=30,
    )

    assert [slot["start"] for slot in result] == [
        "2026-10-03T15:00:00+00:00",
        "2026-10-03T16:00:00+00:00",
    ]
    assert (
        datetime.fromisoformat(result[0]["end"])
        - datetime.fromisoformat(result[0]["start"])
        == timedelta(hours=1)
    )


def test_ranking_then_earliest_order_and_max_slots_limit():
    users = [
        user("a", availability=[weekly(4, "09:00", "12:00")]),
        user("b", availability=[weekly(4, "10:00", "11:00")]),
    ]

    result = find_slots(
        users, 60, "2026-01-01", "2026-01-01", max_slots=2, step_minutes=30
    )

    assert len(result) == 2
    assert [slot["start"] for slot in result] == [
        "2026-01-01T10:00:00+00:00",
        "2026-01-01T09:00:00+00:00",
    ]
    assert result[0]["availableCount"] == 2
    assert result[1]["availableCount"] == 1


def test_empty_users_and_no_matching_availability_return_empty():
    assert find_slots([], 30, "2026-01-01", "2026-01-02") == []
    assert find_slots(
        [user("u1", availability=[weekly(0)])],
        30,
        "2026-01-01",
        "2026-01-01",
    ) == []


@pytest.mark.parametrize(
    ("users", "duration", "earliest", "latest", "kwargs"),
    [
        ([], 0, "2026-01-01", "2026-01-01", {}),
        ([], 30, "2026-01-02", "2026-01-01", {}),
        ([], 30, "invalid", "2026-01-01", {}),
        ([], 30, "2026-01-01", "2026-01-01", {"step_minutes": 0}),
        ([], 30, "2026-01-01", "2026-01-01", {"max_slots": -1}),
        ([user("u1", "Not/AZone")], 30, "2026-01-01", "2026-01-01", {}),
    ],
)
def test_invalid_inputs_raise_value_error(users, duration, earliest, latest, kwargs):
    with pytest.raises(ValueError):
        find_slots(users, duration, earliest, latest, **kwargs)
