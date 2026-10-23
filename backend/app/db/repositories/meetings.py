import re
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError as PydanticValidationError

try:
    from azure.cosmos.database import DatabaseProxy
except ImportError:  # pragma: no cover - optional runtime dependency
    DatabaseProxy = Any  # type: ignore[misc,assignment]

from ..exceptions import (
    NotFound,
    ParticipantsUnavailable,
    PermissionDenied,
    ValidationError,
)
from ..models import (
    FinalSlot,
    InviteRules,
    Meeting,
    Participant,
    Slot,
    User,
)
from ._cosmos import (
    container_for,
    domain_document,
    query_items,
    read_item,
    replace_with_etag_retry,
)

EDIT_ROLES = {"Admin", "Manager"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MEETING_EDITABLE_FIELDS = {
    "name",
    "durationMinutes",
    "earliestDate",
    "latestDate",
    "inviteRules",
}
_INVITE_RULE_KEYS = {
    "includeRoles",
    "excludeRoles",
    "includeUserIds",
    "excludeUserIds",
}


def _validate_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a UUID string")
    try:
        return str(UUID(value))
    except ValueError as error:
        raise ValidationError(f"{field_name} must be a UUID string") from error


def _validate_date(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise ValidationError(f"{field_name} must be a YYYY-MM-DD date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValidationError(f"{field_name} must be a valid YYYY-MM-DD date") from error
    if parsed.isoformat() != value:
        raise ValidationError(f"{field_name} must be a valid YYYY-MM-DD date")
    return value


def _validate_invite_rules(
    include_roles: Any,
    exclude_roles: Any,
    include_user_ids: Any,
    exclude_user_ids: Any,
) -> dict[str, list[Any]]:
    role_lists = (include_roles, exclude_roles)
    id_lists = (include_user_ids, exclude_user_ids)
    if any(
        not isinstance(roles, list)
        or any(not isinstance(role, str) for role in roles)
        for roles in role_lists
    ):
        raise ValidationError("invite role lists must contain role strings")
    if any(
        not isinstance(user_ids, list)
        or any(not isinstance(user_id, str) for user_id in user_ids)
        for user_ids in id_lists
    ):
        raise ValidationError("invite user id lists must contain UUID strings")
    rules = {
        "includeRoles": list(dict.fromkeys(include_roles)),
        "excludeRoles": list(dict.fromkeys(exclude_roles)),
        "includeUserIds": list(
            dict.fromkeys(_validate_id(user_id, "invite user id") for user_id in include_user_ids)
        ),
        "excludeUserIds": list(
            dict.fromkeys(_validate_id(user_id, "invite user id") for user_id in exclude_user_ids)
        ),
    }
    return _validated_model(InviteRules, rules, "invite rules")


def _read_invite_rules(rules: Any) -> dict[str, list[Any]]:
    if not isinstance(rules, dict) or set(rules) != _INVITE_RULE_KEYS:
        raise ValidationError("inviteRules must contain all four invite lists")
    return _validate_invite_rules(
        rules["includeRoles"],
        rules["excludeRoles"],
        rules["includeUserIds"],
        rules["excludeUserIds"],
    )


def _validated_model(
    model_type: type[Any], document: dict[str, Any], description: str
) -> dict[str, Any]:
    try:
        return model_type.model_validate(document).model_dump(mode="json")
    except PydanticValidationError as error:
        raise ValidationError(f"{description} does not match the required shape") from error


def _actor_id(acting_user: Any) -> str:
    if isinstance(acting_user, str):
        return _validate_id(acting_user, "acting_user")
    if isinstance(acting_user, dict):
        return _validate_id(acting_user.get("id"), "acting_user.id")
    if isinstance(acting_user, User):
        return acting_user.id
    raise ValidationError("acting_user must be a user UUID string or User")


def _meeting_or_not_found(db: DatabaseProxy, meeting_id: str) -> dict[str, Any]:
    normalized_id = _validate_id(meeting_id, "meeting_id")
    try:
        return _meeting_document(
            domain_document(
                read_item(container_for(db, "meetings"), normalized_id, normalized_id)
            )
        )
    except NotFound as error:
        raise NotFound("meeting was not found") from error


def _find_user_by_id(db: DatabaseProxy, user_id: str) -> dict[str, Any] | None:
    document = next(
        iter(
            query_items(
                container_for(db, "users"),
                "SELECT * FROM c WHERE c.id = @id AND c.type = @type",
                [
                    {"name": "@id", "value": user_id},
                    {"name": "@type", "value": "user"},
                ],
            )
        ),
        None,
    )
    if document is None:
        return None
    return _validated_model(User, domain_document(document), "user document")


def _require_editor(
    db: DatabaseProxy, meeting: dict[str, Any], acting_user: Any
) -> str:
    user_id = _actor_id(acting_user)
    if user_id == meeting["creatorId"]:
        return user_id
    actor = _find_user_by_id(db, user_id)
    if actor is None:
        raise NotFound("acting user was not found")
    if actor.get("role") not in EDIT_ROLES:
        raise PermissionDenied("only the creator, Admin, or Manager may edit this meeting")
    return user_id


def _find_users_by_ids(
    db: DatabaseProxy, user_ids: list[str]
) -> list[dict[str, Any]]:
    if not user_ids:
        return []
    return query_items(
        container_for(db, "users"),
        "SELECT * FROM c WHERE c.type = @type AND ARRAY_CONTAINS(@ids, c.id)",
        [
            {"name": "@type", "value": "user"},
            {"name": "@ids", "value": user_ids},
        ],
    )


def _new_participant(user: dict[str, Any], response: str) -> dict[str, Any]:
    return _validated_model(
        Participant,
        {
            "userId": user["id"],
            "name": user["name"],
            "role": user.get("role"),
            "response": response,
        },
        "participant",
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _meeting_document(document: dict[str, Any]) -> dict[str, Any]:
    return _validated_model(Meeting, document, "meeting document")


def create_meeting(
    db: DatabaseProxy,
    creator_id: str,
    name: str,
    duration: int,
    earliest: str,
    latest: str,
    include_roles: list[str],
    exclude_roles: list[str],
    include_user_ids: list[str],
    exclude_user_ids: list[str],
) -> dict[str, Any]:
    normalized_creator_id = _validate_id(creator_id, "creator_id")
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("meeting name is required")
    if type(duration) is not int or duration <= 0:
        raise ValidationError("duration must be a positive integer")
    earliest_date = _validate_date(earliest, "earliestDate")
    latest_date = _validate_date(latest, "latestDate")
    if latest_date < earliest_date:
        raise ValidationError("latestDate must not precede earliestDate")
    invite_rules = _validate_invite_rules(
        include_roles, exclude_roles, include_user_ids, exclude_user_ids
    )

    creator = _find_user_by_id(db, normalized_creator_id)
    if creator is None:
        raise NotFound("creator was not found")

    if invite_rules["includeUserIds"]:
        invited_users = _find_users_by_ids(db, invite_rules["includeUserIds"])
        if {user["id"] for user in invited_users} != set(invite_rules["includeUserIds"]):
            raise NotFound("one or more explicitly invited users were not found")
    elif invite_rules["includeRoles"]:
        invited_users = query_items(
            container_for(db, "users"),
            "SELECT * FROM c WHERE c.type = @type AND ARRAY_CONTAINS(@roles, c.role)",
            [
                {"name": "@type", "value": "user"},
                {"name": "@roles", "value": invite_rules["includeRoles"]},
            ],
        )
    else:
        invited_users = []

    excluded_user_ids = set(invite_rules["excludeUserIds"])
    excluded_roles = set(invite_rules["excludeRoles"])
    selected_users = {
        user["id"]: user
        for user in invited_users
        if user["id"] != normalized_creator_id
        and user["id"] not in excluded_user_ids
        and user.get("role") not in excluded_roles
    }
    participants = [
        _new_participant(creator, "accepted"),
        *(
            _new_participant(user, "pending")
            for user in selected_users.values()
        ),
    ]
    participant_ids = [participant["userId"] for participant in participants]
    now = _now_iso()
    document = _meeting_document(
        {
            "id": str(uuid4()),
            "type": "meeting",
            "name": name.strip(),
            "creatorId": normalized_creator_id,
            "durationMinutes": duration,
            "earliestDate": earliest_date,
            "latestDate": latest_date,
            "inviteRules": invite_rules,
            "participants": participants,
            "participantIds": participant_ids,
            "candidateSlots": [],
            "status": "scheduling",
            "finalSlot": None,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    created = container_for(db, "meetings").create_item(body=document)
    return domain_document(created)


def get_meeting(db: DatabaseProxy, meeting_id: str) -> dict[str, Any] | None:
    try:
        return _meeting_or_not_found(db, meeting_id)
    except NotFound:
        return None


def list_meetings_for_user(
    db: DatabaseProxy, user_id: str
) -> list[dict[str, Any]]:
    normalized_id = _validate_id(user_id, "user_id")
    meetings = query_items(
        container_for(db, "meetings"),
        "SELECT * FROM c WHERE c.type = @type AND ARRAY_CONTAINS(c.participantIds, @uid)",
        [
            {"name": "@type", "value": "meeting"},
            {"name": "@uid", "value": normalized_id},
        ],
    )
    return [_meeting_document(domain_document(meeting)) for meeting in meetings]


def list_all_meetings(db: DatabaseProxy) -> list[dict[str, Any]]:
    """Every meeting, for users whose role lets them view and edit any meeting."""
    meetings = query_items(
        container_for(db, "meetings"),
        "SELECT * FROM c WHERE c.type = @type",
        [{"name": "@type", "value": "meeting"}],
    )
    return [_meeting_document(domain_document(meeting)) for meeting in meetings]


def update_meeting(
    db: DatabaseProxy, meeting_id: str, acting_user: Any, fields: dict[str, Any]
) -> dict[str, Any]:
    normalized_id = _validate_id(meeting_id, "meeting_id")
    current = _meeting_or_not_found(db, normalized_id)
    _require_editor(db, current, acting_user)
    if not isinstance(fields, dict) or not fields:
        raise ValidationError("fields must be a non-empty object")
    if set(fields) - _MEETING_EDITABLE_FIELDS:
        raise ValidationError("fields contain unsupported or derived meeting data")
    changes = dict(fields)
    if "inviteRules" in changes:
        changes["inviteRules"] = _read_invite_rules(changes["inviteRules"])

    def update(document: dict[str, Any]) -> dict[str, Any]:
        document.update(changes)
        if "name" in changes and isinstance(document["name"], str):
            document["name"] = document["name"].strip()
        if {"durationMinutes", "earliestDate", "latestDate"} & set(changes):
            document["candidateSlots"] = []
            document["finalSlot"] = None
            document["status"] = "scheduling"
        document["updatedAt"] = _now_iso()
        return _meeting_document(document)

    result = replace_with_etag_retry(
        container_for(db, "meetings"), normalized_id, normalized_id, update
    )
    return _meeting_or_not_found(db, result["id"])


def add_participant(
    db: DatabaseProxy, meeting_id: str, acting_user: Any, user_id: str
) -> dict[str, Any]:
    normalized_meeting_id = _validate_id(meeting_id, "meeting_id")
    normalized_user_id = _validate_id(user_id, "user_id")
    meeting = _meeting_or_not_found(db, normalized_meeting_id)
    _require_editor(db, meeting, acting_user)
    user = _find_user_by_id(db, normalized_user_id)
    if user is None:
        raise NotFound("participant user was not found")
    participant = _new_participant(user, "pending")

    def update(document: dict[str, Any]) -> dict[str, Any]:
        if normalized_user_id in document["participantIds"]:
            return document
        document["participants"].append(participant)
        document["participantIds"].append(normalized_user_id)
        document["candidateSlots"] = []
        document["finalSlot"] = None
        document["status"] = "scheduling"
        document["updatedAt"] = _now_iso()
        return _meeting_document(document)

    result = replace_with_etag_retry(
        container_for(db, "meetings"),
        normalized_meeting_id,
        normalized_meeting_id,
        update,
    )
    return _meeting_or_not_found(db, result["id"])


def remove_participant(
    db: DatabaseProxy, meeting_id: str, acting_user: Any, user_id: str
) -> dict[str, Any]:
    normalized_meeting_id = _validate_id(meeting_id, "meeting_id")
    normalized_user_id = _validate_id(user_id, "user_id")
    meeting = _meeting_or_not_found(db, normalized_meeting_id)
    _require_editor(db, meeting, acting_user)
    if normalized_user_id == meeting["creatorId"]:
        raise ValidationError("the meeting creator cannot be removed")

    def update(document: dict[str, Any]) -> dict[str, Any]:
        if normalized_user_id not in document["participantIds"]:
            raise NotFound("participant was not found in this meeting")
        document["participants"] = [
            participant
            for participant in document["participants"]
            if participant["userId"] != normalized_user_id
        ]
        document["participantIds"] = [
            participant_id
            for participant_id in document["participantIds"]
            if participant_id != normalized_user_id
        ]
        document["candidateSlots"] = []
        document["finalSlot"] = None
        document["status"] = "scheduling"
        document["updatedAt"] = _now_iso()
        return _meeting_document(document)

    result = replace_with_etag_retry(
        container_for(db, "meetings"),
        normalized_meeting_id,
        normalized_meeting_id,
        update,
    )
    return _meeting_or_not_found(db, result["id"])


def respond_to_meeting(
    db: DatabaseProxy, meeting_id: str, user_id: str, response: str
) -> dict[str, Any]:
    normalized_meeting_id = _validate_id(meeting_id, "meeting_id")
    normalized_user_id = _validate_id(user_id, "user_id")
    if not isinstance(response, str) or response not in {
        "pending",
        "accepted",
        "declined",
    }:
        raise ValidationError("response must be pending, accepted, or declined")

    def update(document: dict[str, Any]) -> dict[str, Any]:
        participant = next(
            (
                participant
                for participant in document["participants"]
                if participant["userId"] == normalized_user_id
            ),
            None,
        )
        if participant is None:
            raise NotFound("user is not a participant in this meeting")
        participant["response"] = response
        document["updatedAt"] = _now_iso()
        return _meeting_document(document)

    result = replace_with_etag_retry(
        container_for(db, "meetings"),
        normalized_meeting_id,
        normalized_meeting_id,
        update,
    )
    return _meeting_or_not_found(db, result["id"])


def _validate_slot(slot: Any) -> dict[str, Any]:
    if not isinstance(slot, dict):
        raise ValidationError("candidate slot must be an object")
    required = {
        "start",
        "end",
        "availableCount",
        "availableUserIds",
        "unavailableUserIds",
    }
    if set(slot) != required:
        raise ValidationError("candidate slot has an invalid shape")
    return _validated_model(Slot, slot, "candidate slot")


def set_candidate_slots(
    db: DatabaseProxy, meeting_id: str, slots: list[dict[str, Any]]
) -> None:
    normalized_id = _validate_id(meeting_id, "meeting_id")
    if not isinstance(slots, list):
        raise ValidationError("slots must be a list")
    validated_slots = [_validate_slot(slot) for slot in slots]
    validated_slots.sort(key=lambda slot: slot["availableCount"], reverse=True)
    validated_slots = validated_slots[:10]

    def update(document: dict[str, Any]) -> dict[str, Any]:
        document["candidateSlots"] = validated_slots
        document["updatedAt"] = _now_iso()
        return _meeting_document(document)

    try:
        replace_with_etag_retry(
            container_for(db, "meetings"), normalized_id, normalized_id, update
        )
    except NotFound as error:
        raise NotFound("meeting was not found") from error


def finalise_meeting(
    db: DatabaseProxy,
    meeting_id: str,
    acting_user: Any,
    slot: dict[str, Any],
    force: bool = False,
) -> dict[str, Any]:
    normalized_id = _validate_id(meeting_id, "meeting_id")
    meeting = _meeting_or_not_found(db, normalized_id)
    _require_editor(db, meeting, acting_user)
    if not isinstance(force, bool):
        raise ValidationError("force must be a boolean")
    if not isinstance(slot, dict) or not {"start", "end"}.issubset(slot):
        raise ValidationError("slot must contain start and end")
    if set(slot) - {
        "start",
        "end",
        "availableCount",
        "availableUserIds",
        "unavailableUserIds",
    }:
        raise ValidationError("slot contains unsupported fields")
    validated_times = _validated_model(
        FinalSlot,
        {
            "start": slot["start"],
            "end": slot["end"],
            "forced": False,
            "unavailableUserIds": [],
        },
        "final slot",
    )
    target_start = validated_times["start"]
    target_end = validated_times["end"]

    def update(document: dict[str, Any]) -> dict[str, Any]:
        candidate = next(
            (
                item
                for item in document["candidateSlots"]
                if item["start"] == target_start and item["end"] == target_end
            ),
            None,
        )
        if candidate is None:
            raise ValidationError("slot is not among the current candidate slots")
        participant_ids = set(document["participantIds"])
        unavailable_ids = [
            user_id
            for user_id in candidate["unavailableUserIds"]
            if user_id in participant_ids
        ]
        if unavailable_ids and not force:
            raise ParticipantsUnavailable("one or more participants are unavailable")
        document["finalSlot"] = {
            "start": target_start,
            "end": target_end,
            "forced": force and bool(unavailable_ids),
            "unavailableUserIds": unavailable_ids if force else [],
        }
        document["status"] = "scheduled"
        document["updatedAt"] = _now_iso()
        return _meeting_document(document)

    result = replace_with_etag_retry(
        container_for(db, "meetings"), normalized_id, normalized_id, update
    )
    return _meeting_or_not_found(db, result["id"])


def cancel_meeting(
    db: DatabaseProxy, meeting_id: str, acting_user: Any
) -> dict[str, Any]:
    normalized_id = _validate_id(meeting_id, "meeting_id")
    meeting = _meeting_or_not_found(db, normalized_id)
    _require_editor(db, meeting, acting_user)

    def update(document: dict[str, Any]) -> dict[str, Any]:
        document["status"] = "cancelled"
        document["updatedAt"] = _now_iso()
        return _meeting_document(document)

    result = replace_with_etag_retry(
        container_for(db, "meetings"), normalized_id, normalized_id, update
    )
    return _meeting_or_not_found(db, result["id"])
