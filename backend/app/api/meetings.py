from typing import Any

from fastapi import APIRouter, Depends

from ..db.exceptions import NotFound, PermissionDenied
from ..db.repositories.meetings import (
    EDIT_ROLES,
    add_participant,
    cancel_meeting,
    create_meeting,
    finalise_meeting,
    get_meeting,
    list_meetings_for_user,
    remove_participant,
    respond_to_meeting,
    set_candidate_slots,
)
from ..db.repositories.users import get_users_by_ids
from ..scheduler import find_slots
from .deps import current_user, get_db
from .schemas import (
    AddParticipantRequest,
    CreateMeetingRequest,
    FinaliseRequest,
    RespondRequest,
)

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


def _visible_meeting(db: Any, meeting_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """Load a meeting the user may view: a participant, or anyone with an edit role."""
    meeting = get_meeting(db, meeting_id)
    if meeting is None:
        raise NotFound("meeting was not found")
    if user["id"] not in meeting["participantIds"] and user.get("role") not in EDIT_ROLES:
        raise PermissionDenied("you are not a participant in this meeting")
    return meeting


@router.get("")
def list_meetings(
    db: Any = Depends(get_db), user: dict[str, Any] = Depends(current_user)
) -> list[dict[str, Any]]:
    return list_meetings_for_user(db, user["id"])


@router.post("", status_code=201)
def post_meeting(
    body: CreateMeetingRequest,
    db: Any = Depends(get_db),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return create_meeting(
        db,
        user["id"],
        body.name,
        body.durationMinutes,
        body.earliestDate,
        body.latestDate,
        body.includeRoles,
        body.excludeRoles,
        body.includeUserIds,
        body.excludeUserIds,
    )


@router.get("/{meeting_id}")
def read_meeting(
    meeting_id: str,
    db: Any = Depends(get_db),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return _visible_meeting(db, meeting_id, user)


@router.post("/{meeting_id}/participants")
def post_participant(
    meeting_id: str,
    body: AddParticipantRequest,
    db: Any = Depends(get_db),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return add_participant(db, meeting_id, user["id"], body.userId)


@router.delete("/{meeting_id}/participants/{user_id}")
def delete_participant(
    meeting_id: str,
    user_id: str,
    db: Any = Depends(get_db),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return remove_participant(db, meeting_id, user["id"], user_id)


@router.post("/{meeting_id}/respond")
def respond(
    meeting_id: str,
    body: RespondRequest,
    db: Any = Depends(get_db),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return respond_to_meeting(db, meeting_id, user["id"], body.response)


@router.post("/{meeting_id}/cancel")
def cancel(
    meeting_id: str,
    db: Any = Depends(get_db),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return cancel_meeting(db, meeting_id, user["id"])


@router.post("/{meeting_id}/find-slots")
def post_find_slots(
    meeting_id: str,
    db: Any = Depends(get_db),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    meeting = _visible_meeting(db, meeting_id, user)
    participants = get_users_by_ids(db, meeting["participantIds"])
    slots = find_slots(
        participants,
        meeting["durationMinutes"],
        meeting["earliestDate"],
        meeting["latestDate"],
    )
    set_candidate_slots(db, meeting["id"], list(slots))
    return _visible_meeting(db, meeting["id"], user)


@router.post("/{meeting_id}/finalise")
def finalise(
    meeting_id: str,
    body: FinaliseRequest,
    db: Any = Depends(get_db),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return finalise_meeting(
        db, meeting_id, user["id"], body.slot.model_dump(), force=body.force
    )
