import re
from datetime import date, datetime, timezone
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Role = Literal["Admin", "Manager", "Senior Staff", "Staff", "Junior Staff"]
MeetingStatus = Literal["scheduling", "scheduled", "cancelled"]
Response = Literal["pending", "accepted", "declined"]
DayOfWeek = Annotated[int, Field(strict=True, ge=0, le=6)]
ClockTime = Annotated[
    str,
    StringConstraints(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$"),
]
UuidString = Annotated[str, StringConstraints(min_length=36, max_length=36)]
DateString = Annotated[
    str,
    StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$"),
]
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _uuid_string(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("id must be a UUID string")
    try:
        return str(UUID(value))
    except ValueError as error:
        raise ValueError("id must be a UUID string") from error


def _valid_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("date must be a valid YYYY-MM-DD date") from error
    if parsed.isoformat() != value:
        raise ValueError("date must be a valid YYYY-MM-DD date")
    return value


def _utc_datetime(value: datetime | str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("datetime must be an ISO-8601 timestamp") from error
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError("datetime must be an ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("datetime must include a UTC timezone")
    return parsed.astimezone(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_encoders={datetime: lambda value: value.isoformat()},
    )


class Availability(StrictModel):
    dayOfWeek: DayOfWeek
    start: ClockTime
    end: ClockTime

    @model_validator(mode="after")
    def validate_range(self):
        if self.end <= self.start:
            raise ValueError("availability end must be after start")
        return self


class OnceUnavailability(StrictModel):
    id: UuidString
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    type: Literal["once"]
    start: datetime
    end: datetime

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _uuid_string(value)

    @field_validator("start", "end", mode="before")
    @classmethod
    def validate_utc_time(cls, value: datetime | str) -> datetime:
        return _utc_datetime(value)

    @model_validator(mode="after")
    def validate_range(self):
        if self.end <= self.start:
            raise ValueError("unavailability end must be after start")
        return self


class RecurringUnavailability(StrictModel):
    id: UuidString
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    type: Literal["recurring"]
    daysOfWeek: list[DayOfWeek] = Field(min_length=1)
    startTime: ClockTime
    endTime: ClockTime
    recurUntil: DateString | None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _uuid_string(value)

    @field_validator("daysOfWeek")
    @classmethod
    def validate_days(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("daysOfWeek must contain unique days")
        return value

    @field_validator("recurUntil")
    @classmethod
    def validate_recur_until(cls, value: str | None) -> str | None:
        return None if value is None else _valid_date(value)

    @model_validator(mode="after")
    def validate_range(self):
        if self.endTime <= self.startTime:
            raise ValueError("recurring unavailability endTime must be after startTime")
        return self


Unavailability = Annotated[
    OnceUnavailability | RecurringUnavailability,
    Field(discriminator="type"),
]


class User(StrictModel):
    id: UuidString
    type: Literal["user"]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    email: str
    passwordHash: Annotated[str, StringConstraints(min_length=1)]
    role: Role | None
    timezone: Annotated[str, StringConstraints(min_length=1)] = "Australia/Melbourne"
    availability: list[Availability]
    unavailability: list[Unavailability]
    createdAt: datetime
    updatedAt: datetime

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _uuid_string(value)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if value != value.lower() or not _EMAIL_PATTERN.fullmatch(value):
            raise ValueError("email must be a lowercase valid email address")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (TypeError, ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("timezone must be a valid IANA timezone") from error
        return value

    @field_validator("createdAt", "updatedAt", mode="before")
    @classmethod
    def validate_timestamps(cls, value: datetime | str) -> datetime:
        return _utc_datetime(value)


class Participant(StrictModel):
    userId: UuidString
    name: Annotated[str, StringConstraints(min_length=1)]
    role: Role | None
    response: Response

    @field_validator("userId")
    @classmethod
    def validate_user_id(cls, value: str) -> str:
        return _uuid_string(value)


class Slot(StrictModel):
    start: datetime
    end: datetime
    availableCount: int = Field(strict=True, ge=0)
    availableUserIds: list[UuidString]
    unavailableUserIds: list[UuidString]

    @field_validator("start", "end", mode="before")
    @classmethod
    def validate_utc_times(cls, value: datetime | str) -> datetime:
        return _utc_datetime(value)

    @field_validator("availableUserIds", "unavailableUserIds")
    @classmethod
    def validate_user_ids(cls, value: list[str]) -> list[str]:
        normalized = [_uuid_string(user_id) for user_id in value]
        if len(set(normalized)) != len(normalized):
            raise ValueError("slot user ids must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_slot(self):
        if self.end <= self.start:
            raise ValueError("slot end must be after start")
        if self.availableCount != len(self.availableUserIds):
            raise ValueError("availableCount must match availableUserIds")
        if set(self.availableUserIds).intersection(self.unavailableUserIds):
            raise ValueError("a user cannot be both available and unavailable")
        return self


class FinalSlot(StrictModel):
    start: datetime
    end: datetime
    forced: bool
    unavailableUserIds: list[UuidString]

    @field_validator("start", "end", mode="before")
    @classmethod
    def validate_utc_times(cls, value: datetime | str) -> datetime:
        return _utc_datetime(value)

    @field_validator("unavailableUserIds")
    @classmethod
    def validate_unavailable_ids(cls, value: list[str]) -> list[str]:
        normalized = [_uuid_string(user_id) for user_id in value]
        if len(set(normalized)) != len(normalized):
            raise ValueError("unavailableUserIds must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_range(self):
        if self.end <= self.start:
            raise ValueError("final slot end must be after start")
        return self


class InviteRules(StrictModel):
    includeRoles: list[Role]
    excludeRoles: list[Role]
    includeUserIds: list[UuidString]
    excludeUserIds: list[UuidString]

    @field_validator("includeUserIds", "excludeUserIds")
    @classmethod
    def validate_user_ids(cls, value: list[str]) -> list[str]:
        normalized = [_uuid_string(user_id) for user_id in value]
        if len(set(normalized)) != len(normalized):
            raise ValueError("invite user ids must be unique")
        return normalized


class Meeting(StrictModel):
    id: UuidString
    type: Literal["meeting"]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    creatorId: UuidString
    durationMinutes: int = Field(strict=True, gt=0)
    earliestDate: DateString
    latestDate: DateString
    inviteRules: InviteRules
    participants: list[Participant]
    participantIds: list[UuidString]
    candidateSlots: list[Slot] = Field(max_length=10)
    status: MeetingStatus = "scheduling"
    finalSlot: FinalSlot | None
    createdAt: datetime
    updatedAt: datetime

    @field_validator("id", "creatorId")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return _uuid_string(value)

    @field_validator("participantIds")
    @classmethod
    def validate_participant_ids(cls, value: list[str]) -> list[str]:
        normalized = [_uuid_string(user_id) for user_id in value]
        if len(set(normalized)) != len(normalized):
            raise ValueError("participantIds must be unique")
        return normalized

    @field_validator("earliestDate", "latestDate")
    @classmethod
    def validate_dates(cls, value: str) -> str:
        return _valid_date(value)

    @field_validator("createdAt", "updatedAt", mode="before")
    @classmethod
    def validate_timestamps(cls, value: datetime | str) -> datetime:
        return _utc_datetime(value)

    @model_validator(mode="after")
    def validate_meeting(self):
        if self.latestDate < self.earliestDate:
            raise ValueError("latestDate must not precede earliestDate")
        participant_ids = [participant.userId for participant in self.participants]
        if self.creatorId not in participant_ids:
            raise ValueError("meeting creator must be a participant")
        if set(participant_ids) != set(self.participantIds):
            raise ValueError("participantIds must match participants")
        if len(set(participant_ids)) != len(participant_ids):
            raise ValueError("meeting participants must be unique")
        counts = [slot.availableCount for slot in self.candidateSlots]
        if counts != sorted(counts, reverse=True):
            raise ValueError("candidateSlots must be sorted by availability")
        return self
