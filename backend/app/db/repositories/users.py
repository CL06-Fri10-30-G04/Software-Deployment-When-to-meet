import re
from datetime import datetime, timezone as utc_timezone
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import bcrypt
from pydantic import ValidationError as PydanticValidationError

try:
    from azure.cosmos.database import DatabaseProxy
    from azure.cosmos.exceptions import CosmosHttpResponseError
except ImportError:  # pragma: no cover - optional runtime dependency
    DatabaseProxy = Any  # type: ignore[misc,assignment]
    CosmosHttpResponseError = RuntimeError

from ..exceptions import DuplicateEmailError, NotFound, ValidationError
from ..models import (
    Availability,
    OnceUnavailability,
    RecurringUnavailability,
    User,
)
from ._cosmos import (
    container_for,
    domain_document,
    query_items,
    replace_with_etag_retry,
)

ROLES = {"Admin", "Manager", "Senior Staff", "Staff", "Junior Staff"}
DEFAULT_TIMEZONE = "Australia/Melbourne"
DEFAULT_AVAILABILITY = [
    {"dayOfWeek": day, "start": "09:00", "end": "17:00"}
    for day in range(1, 6)
]
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a UUID string")
    try:
        return str(UUID(value))
    except ValueError as error:
        raise ValidationError(f"{field_name} must be a UUID string") from error


def _validate_email(email: str) -> str:
    if not isinstance(email, str):
        raise ValidationError("email must be a string")
    normalized_email = email.strip().lower()
    if not _EMAIL_RE.fullmatch(normalized_email):
        raise ValidationError("email must be a valid email address")
    return normalized_email


def _validate_role(role: str | None) -> None:
    if role is not None and (not isinstance(role, str) or role not in ROLES):
        raise ValidationError("role is not a supported role")


def _validate_timezone(timezone_name: str) -> None:
    try:
        ZoneInfo(timezone_name)
    except (TypeError, ValueError, ZoneInfoNotFoundError) as error:
        raise ValidationError("timezone must be a valid IANA timezone") from error


def _validate_availability(availability: Any) -> list[dict[str, Any]]:
    if not isinstance(availability, list):
        raise ValidationError("availability must be a list")
    try:
        return [
            Availability.model_validate(entry).model_dump(mode="json")
            for entry in availability
        ]
    except PydanticValidationError as error:
        raise ValidationError("availability does not match the required shape") from error


def _validate_unavailability_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValidationError("unavailability item must be an object")
    item_copy = dict(item)
    item_copy.setdefault("id", str(uuid4()))
    model = (
        OnceUnavailability
        if item_copy.get("type") == "once"
        else RecurringUnavailability
    )
    try:
        return model.model_validate(item_copy).model_dump(mode="json")
    except PydanticValidationError as error:
        raise ValidationError("unavailability does not match the required shape") from error


def _model_dump(model_type: type[User], document: dict[str, Any]) -> dict[str, Any]:
    try:
        return model_type.model_validate(document).model_dump(mode="json")
    except PydanticValidationError as error:
        raise ValidationError("user document does not match the required shape") from error


def _public_user(
    document: dict[str, Any] | None, *, include_password: bool = False
) -> dict[str, Any] | None:
    if document is None:
        return None
    result = domain_document(document)
    if not include_password:
        result.pop("passwordHash", None)
    return result


def _find_user_by_id(db: DatabaseProxy, user_id: str) -> dict[str, Any] | None:
    users = container_for(db, "users")
    matches = query_items(
        users,
        "SELECT * FROM c WHERE c.id = @id AND c.type = @type",
        [
            {"name": "@id", "value": user_id},
            {"name": "@type", "value": "user"},
        ],
    )
    return matches[0] if matches else None


def create_user(
    db: DatabaseProxy,
    name: str,
    email: str,
    password: str,
    role: str | None = None,
    timezone: str | None = None,
) -> dict[str, Any]:
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("name is required")
    normalized_email = _validate_email(email)
    _validate_role(role)
    timezone_name = DEFAULT_TIMEZONE if timezone is None else timezone
    if not isinstance(timezone_name, str) or not timezone_name:
        raise ValidationError("timezone must be a valid IANA timezone")
    _validate_timezone(timezone_name)
    if not isinstance(password, str) or not password:
        raise ValidationError("password is required")
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        raise ValidationError("password must be at most 72 UTF-8 bytes")

    now = datetime.now(utc_timezone.utc).isoformat()
    user = {
        "id": str(uuid4()),
        "type": "user",
        "name": name.strip(),
        "email": normalized_email,
        "passwordHash": bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("ascii"),
        "role": role,
        "timezone": timezone_name,
        "availability": DEFAULT_AVAILABILITY,
        "unavailability": [],
        "createdAt": now,
        "updatedAt": now,
    }
    validated_user = _model_dump(User, user)
    try:
        created = container_for(db, "users").create_item(body=validated_user)
    except CosmosHttpResponseError as error:
        if error.status_code == 409:
            raise DuplicateEmailError("email address is already registered") from error
        raise
    return _public_user(created)


def get_user_by_id(db: DatabaseProxy, user_id: str) -> dict[str, Any] | None:
    normalized_id = _validate_id(user_id, "user_id")
    return _public_user(_find_user_by_id(db, normalized_id))


def get_user_by_email(db: DatabaseProxy, email: str) -> dict[str, Any] | None:
    normalized_email = _validate_email(email)
    matches = query_items(
        container_for(db, "users"),
        "SELECT * FROM c WHERE c.email = @email AND c.type = @type",
        [
            {"name": "@email", "value": normalized_email},
            {"name": "@type", "value": "user"},
        ],
        partition_key=normalized_email,
    )
    return _public_user(matches[0] if matches else None)


def get_user_for_auth(db: DatabaseProxy, email: str) -> dict[str, Any] | None:
    normalized_email = _validate_email(email)
    matches = query_items(
        container_for(db, "users"),
        "SELECT * FROM c WHERE c.email = @email AND c.type = @type",
        [
            {"name": "@email", "value": normalized_email},
            {"name": "@type", "value": "user"},
        ],
        partition_key=normalized_email,
    )
    return _public_user(matches[0] if matches else None, include_password=True)


def get_users_by_ids(db: DatabaseProxy, ids: list[str]) -> list[dict[str, Any]]:
    if not isinstance(ids, list):
        raise ValidationError("ids must be a list of UUID strings")
    normalized_ids = [_validate_id(user_id, "user_id") for user_id in ids]
    if not normalized_ids:
        return []
    matches = query_items(
        container_for(db, "users"),
        "SELECT * FROM c WHERE c.type = @type AND ARRAY_CONTAINS(@ids, c.id)",
        [
            {"name": "@type", "value": "user"},
            {"name": "@ids", "value": normalized_ids},
        ],
    )
    return [_public_user(user) for user in matches]


def get_users_by_roles(db: DatabaseProxy, roles: list[str]) -> list[dict[str, Any]]:
    if not isinstance(roles, list) or any(
        not isinstance(role, str) or role not in ROLES for role in roles
    ):
        raise ValidationError("roles must contain only supported roles")
    if not roles:
        return []
    matches = query_items(
        container_for(db, "users"),
        "SELECT * FROM c WHERE c.type = @type AND ARRAY_CONTAINS(@roles, c.role)",
        [
            {"name": "@type", "value": "user"},
            {"name": "@roles", "value": roles},
        ],
    )
    return [_public_user(user) for user in matches]


def set_availability(
    db: DatabaseProxy, user_id: str, availability: list[dict[str, Any]]
) -> None:
    normalized_id = _validate_id(user_id, "user_id")
    validated_availability = _validate_availability(availability)

    def update(document: dict[str, Any]) -> dict[str, Any]:
        document["availability"] = validated_availability
        document["updatedAt"] = datetime.now(utc_timezone.utc).isoformat()
        return _model_dump(User, document)

    try:
        replace_with_etag_retry(
            container_for(db, "users"),
            normalized_id,
            _user_partition_key(db, normalized_id),
            update,
        )
    except NotFound:
        raise NotFound("user was not found") from None


def add_unavailability(db: DatabaseProxy, user_id: str, item: dict[str, Any]) -> str:
    normalized_id = _validate_id(user_id, "user_id")
    validated_item = _validate_unavailability_item(item)

    def update(document: dict[str, Any]) -> dict[str, Any]:
        document["unavailability"].append(validated_item)
        document["updatedAt"] = datetime.now(utc_timezone.utc).isoformat()
        return _model_dump(User, document)

    try:
        replace_with_etag_retry(
            container_for(db, "users"),
            normalized_id,
            _user_partition_key(db, normalized_id),
            update,
        )
    except NotFound:
        raise NotFound("user was not found") from None
    return validated_item["id"]


def remove_unavailability(db: DatabaseProxy, user_id: str, item_id: str) -> None:
    normalized_id = _validate_id(user_id, "user_id")
    normalized_item_id = _validate_id(item_id, "item_id")

    def update(document: dict[str, Any]) -> dict[str, Any]:
        original_count = len(document["unavailability"])
        document["unavailability"] = [
            item
            for item in document["unavailability"]
            if item["id"] != normalized_item_id
        ]
        if len(document["unavailability"]) == original_count:
            raise NotFound("unavailability item was not found")
        document["updatedAt"] = datetime.now(utc_timezone.utc).isoformat()
        return _model_dump(User, document)

    try:
        replace_with_etag_retry(
            container_for(db, "users"),
            normalized_id,
            _user_partition_key(db, normalized_id),
            update,
        )
    except NotFound as error:
        raise NotFound("user or unavailability item was not found") from error


def _user_partition_key(db: DatabaseProxy, user_id: str) -> str:
    user = _find_user_by_id(db, user_id)
    if user is None:
        raise NotFound("user was not found")
    return user["email"]
