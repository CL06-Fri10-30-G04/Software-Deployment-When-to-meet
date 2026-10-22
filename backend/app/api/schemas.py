from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ..db.models import Availability, ClockTime, DateString, DayOfWeek, Role

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(RequestModel):
    name: NonEmptyString
    email: NonEmptyString
    password: Annotated[str, StringConstraints(min_length=1)]
    role: Role | None = None
    timezone: NonEmptyString | None = None


class LoginRequest(RequestModel):
    email: str
    password: str


class AvailabilityRequest(RequestModel):
    availability: list[Availability]


class OnceUnavailabilityRequest(RequestModel):
    label: NonEmptyString
    type: Literal["once"]
    start: str
    end: str


class RecurringUnavailabilityRequest(RequestModel):
    label: NonEmptyString
    type: Literal["recurring"]
    daysOfWeek: list[DayOfWeek] = Field(min_length=1)
    startTime: ClockTime
    endTime: ClockTime
    recurUntil: DateString | None = None


UnavailabilityRequest = Annotated[
    OnceUnavailabilityRequest | RecurringUnavailabilityRequest,
    Field(discriminator="type"),
]


class CreateMeetingRequest(RequestModel):
    name: NonEmptyString
    durationMinutes: int = Field(strict=True, gt=0)
    earliestDate: DateString
    latestDate: DateString
    includeRoles: list[Role] = []
    excludeRoles: list[Role] = []
    includeUserIds: list[str] = []
    excludeUserIds: list[str] = []


class AddParticipantRequest(RequestModel):
    userId: str


class RespondRequest(RequestModel):
    response: Literal["accepted", "declined"]


class SlotTimes(RequestModel):
    start: str
    end: str


class FinaliseRequest(RequestModel):
    slot: SlotTimes
    force: bool = False
