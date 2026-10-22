from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from ..db.exceptions import PermissionDenied, ValidationError
from ..db.models import Role
from ..db.repositories.meetings import EDIT_ROLES, list_all_meetings, list_meetings_for_user
from .deps import current_user, get_db

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

MAX_RANGE = timedelta(days=62)

# Which of the user's own meetings to show; the response filters use the
# user's reply as a participant.
Show = Literal["all", "attending", "invited", "declined", "created"]
_RESPONSE_FOR_SHOW = {"attending": "accepted", "invited": "pending", "declined": "declined"}


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _overlaps(meeting: dict[str, Any], start: datetime, end: datetime) -> bool:
    final_slot = meeting["finalSlot"]
    if final_slot:
        return _parse_utc(final_slot["start"]) < end and _parse_utc(final_slot["end"]) > start
    # Not scheduled yet: compare the meeting's candidate date range by day.
    earliest = date.fromisoformat(meeting["earliestDate"])
    latest = date.fromisoformat(meeting["latestDate"])
    return earliest <= end.date() and latest >= start.date()


def _calendar_item(meeting: dict[str, Any], user_id: str) -> dict[str, Any]:
    participants = meeting["participants"]
    mine = next((p for p in participants if p["userId"] == user_id), None)
    creator = next((p for p in participants if p["userId"] == meeting["creatorId"]), None)
    final_slot = meeting["finalSlot"]
    return {
        "id": meeting["id"],
        "name": meeting["name"],
        "status": meeting["status"],
        "start": final_slot["start"] if final_slot else None,
        "end": final_slot["end"] if final_slot else None,
        "forced": bool(final_slot and final_slot["forced"]),
        "earliestDate": meeting["earliestDate"],
        "latestDate": meeting["latestDate"],
        "durationMinutes": meeting["durationMinutes"],
        "creatorId": meeting["creatorId"],
        "creatorName": creator["name"] if creator else None,
        "myResponse": mine["response"] if mine else None,
        "participantCount": len(participants),
        "acceptedCount": sum(1 for p in participants if p["response"] == "accepted"),
        "roles": sorted({p["role"] for p in participants if p["role"]}),
    }


def _sort_key(item: dict[str, Any]) -> str:
    return item["start"] or f"{item['earliestDate']}T00:00:00"


@router.get("")
def calendar(
    start: datetime,
    end: datetime,
    show: Show = "all",
    role: Role | None = None,
    scope: Literal["mine", "everyone"] = "mine",
    cancelled: bool = False,
    db: Any = Depends(get_db),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """Meetings that fall within [start, end) and match the filters."""
    start, end = _as_utc(start), _as_utc(end)
    if end <= start:
        raise ValidationError("end must be after start")
    if end - start > MAX_RANGE:
        raise ValidationError("the date range can be at most 62 days")
    if scope == "everyone":
        if user.get("role") not in EDIT_ROLES:
            raise PermissionDenied("only Admin and Manager users can view everyone's meetings")
        meetings = list_all_meetings(db)
    else:
        meetings = list_meetings_for_user(db, user["id"])

    items = []
    for meeting in meetings:
        if meeting["status"] == "cancelled" and not cancelled:
            continue
        if not _overlaps(meeting, start, end):
            continue
        item = _calendar_item(meeting, user["id"])
        if show == "created" and item["creatorId"] != user["id"]:
            continue
        if show in _RESPONSE_FOR_SHOW and item["myResponse"] != _RESPONSE_FOR_SHOW[show]:
            continue
        if role and role not in item["roles"]:
            continue
        items.append(item)
    items.sort(key=_sort_key)
    return {"start": start.isoformat(), "end": end.isoformat(), "items": items}
