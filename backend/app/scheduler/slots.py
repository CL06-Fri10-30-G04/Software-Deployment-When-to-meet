import re
from datetime import date, datetime, time, timedelta, timezone
from typing import TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class Slot(TypedDict):
    start: str
    end: str
    availableCount: int
    availableUserIds: list[str]
    unavailableUserIds: list[str]


def _parse_date(value: date | str, field: str) -> date:
    if isinstance(value, datetime):
        raise ValueError(f"{field} must be a date, not a datetime")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a date or YYYY-MM-DD string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be a valid YYYY-MM-DD date") from error
    if parsed.isoformat() != value:
        raise ValueError(f"{field} must be a valid YYYY-MM-DD date")
    return parsed


def _parse_clock(value: object, field: str) -> time:
    if not isinstance(value, str) or not _TIME_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be an HH:MM time")
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour, minute)


def _weekday(day: object, field: str) -> int:
    if type(day) is not int or not 0 <= day <= 6:
        raise ValueError(f"{field} must be an integer from 0 (Sunday) to 6 (Saturday)")
    return day


def _sunday_index(value: date) -> int:
    return (value.weekday() + 1) % 7


def _wall_time_utc(day: date, clock: time, zone: ZoneInfo, *, end: bool) -> datetime:
    wall = datetime.combine(day, clock)
    for offset in range(181):
        candidate_wall = wall + timedelta(minutes=offset)
        instants = []
        for fold in (0, 1):
            candidate = candidate_wall.replace(tzinfo=zone, fold=fold)
            instant = candidate.astimezone(UTC)
            if instant.astimezone(zone).replace(tzinfo=None) == candidate_wall:
                instants.append(instant)
        if instants:
            return max(instants) if end else min(instants)
    raise ValueError(f"cannot resolve local time in timezone {zone.key}")


def _parse_utc_timestamp(value: object, field: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{field} must be a UTC ISO-8601 timestamp") from error
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError(f"{field} must be a UTC ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must include a UTC timezone")
    return parsed.astimezone(UTC)


def _validated_users(users: object) -> list[dict]:
    if not isinstance(users, list):
        raise ValueError("users must be a list")

    result = []
    seen_ids = set()
    for index, user in enumerate(users):
        prefix = f"users[{index}]"
        if not isinstance(user, dict):
            raise ValueError(f"{prefix} must be an object")
        user_id = user.get("id")
        if not isinstance(user_id, str) or not user_id:
            raise ValueError(f"{prefix}.id must be a non-empty string")
        if user_id in seen_ids:
            raise ValueError("user ids must be unique")
        seen_ids.add(user_id)

        timezone_name = user.get("timezone")
        if not isinstance(timezone_name, str) or not timezone_name:
            raise ValueError(f"{prefix}.timezone must be a valid IANA timezone")
        try:
            zone = ZoneInfo(timezone_name)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError(f"{prefix}.timezone must be a valid IANA timezone") from error

        availability = user.get("availability")
        unavailability = user.get("unavailability")
        if not isinstance(availability, list) or not isinstance(unavailability, list):
            raise ValueError(f"{prefix} availability and unavailability must be lists")

        weekly = []
        for item_index, item in enumerate(availability):
            item_prefix = f"{prefix}.availability[{item_index}]"
            if not isinstance(item, dict):
                raise ValueError(f"{item_prefix} must be an object")
            day = _weekday(item.get("dayOfWeek"), f"{item_prefix}.dayOfWeek")
            start = _parse_clock(item.get("start"), f"{item_prefix}.start")
            end = _parse_clock(item.get("end"), f"{item_prefix}.end")
            if end <= start:
                raise ValueError(f"{item_prefix}.end must be after start")
            weekly.append((day, start, end))

        exceptions = []
        for item_index, item in enumerate(unavailability):
            item_prefix = f"{prefix}.unavailability[{item_index}]"
            if not isinstance(item, dict):
                raise ValueError(f"{item_prefix} must be an object")
            kind = item.get("type")
            if kind == "once":
                start = _parse_utc_timestamp(item.get("start"), f"{item_prefix}.start")
                end = _parse_utc_timestamp(item.get("end"), f"{item_prefix}.end")
                if end <= start:
                    raise ValueError(f"{item_prefix}.end must be after start")
                exceptions.append(("once", start, end))
            elif kind == "recurring":
                days = item.get("daysOfWeek")
                if not isinstance(days, list) or not days:
                    raise ValueError(f"{item_prefix}.daysOfWeek must be a non-empty list")
                normalized_days = [_weekday(day, f"{item_prefix}.daysOfWeek") for day in days]
                if len(set(normalized_days)) != len(normalized_days):
                    raise ValueError(f"{item_prefix}.daysOfWeek must not contain duplicates")
                start = _parse_clock(item.get("startTime"), f"{item_prefix}.startTime")
                end = _parse_clock(item.get("endTime"), f"{item_prefix}.endTime")
                if end <= start:
                    raise ValueError(f"{item_prefix}.endTime must be after startTime")
                recur_until_value = item.get("recurUntil")
                recur_until = (
                    None
                    if recur_until_value is None
                    else _parse_date(recur_until_value, f"{item_prefix}.recurUntil")
                )
                exceptions.append(
                    ("recurring", set(normalized_days), start, end, recur_until)
                )
            else:
                raise ValueError(f"{item_prefix}.type must be 'once' or 'recurring'")

        result.append(
            {
                "id": user_id,
                "zone": zone,
                "weekly": weekly,
                "unavailability": exceptions,
            }
        )
    return result


def _is_available(user: dict, start: datetime, end: datetime) -> bool:
    local_start = start.astimezone(user["zone"])
    local_end = end.astimezone(user["zone"])

    available = False
    first_day = local_start.date() - timedelta(days=1)
    last_day = local_end.date()
    for day_offset in range((last_day - first_day).days + 1):
        local_day = first_day + timedelta(days=day_offset)
        weekday = _sunday_index(local_day)
        for available_day, clock_start, clock_end in user["weekly"]:
            if weekday != available_day:
                continue
            window_start = _wall_time_utc(
                local_day, clock_start, user["zone"], end=False
            )
            window_end = _wall_time_utc(
                local_day, clock_end, user["zone"], end=True
            )
            if start >= window_start and end <= window_end:
                available = True
                break
        if available:
            break

    if not available:
        return False

    for item in user["unavailability"]:
        if item[0] == "once":
            _, unavailable_start, unavailable_end = item
            if start < unavailable_end and end > unavailable_start:
                return False
            continue

        _, days, clock_start, clock_end, recur_until = item
        local_start_day = start.astimezone(user["zone"]).date() - timedelta(days=1)
        local_end_day = end.astimezone(user["zone"]).date()
        for day_offset in range((local_end_day - local_start_day).days + 1):
            local_day = local_start_day + timedelta(days=day_offset)
            if _sunday_index(local_day) not in days:
                continue
            if recur_until is not None and local_day > recur_until:
                continue
            unavailable_start = _wall_time_utc(
                local_day, clock_start, user["zone"], end=False
            )
            unavailable_end = _wall_time_utc(
                local_day, clock_end, user["zone"], end=True
            )
            if start < unavailable_end and end > unavailable_start:
                return False
    return True


def find_slots(
    users: list[dict],
    duration_minutes: int,
    earliest_date: date | str,
    latest_date: date | str,
    max_slots: int = 10,
    step_minutes: int = 15,
) -> list[Slot]:
    """Return the highest-attendance UTC slots in the inclusive date range."""
    if type(duration_minutes) is not int or duration_minutes <= 0:
        raise ValueError("duration_minutes must be a positive integer")
    if type(step_minutes) is not int or step_minutes <= 0:
        raise ValueError("step_minutes must be a positive integer")
    if type(max_slots) is not int or max_slots < 0:
        raise ValueError("max_slots must be a non-negative integer")

    first_date = _parse_date(earliest_date, "earliest_date")
    last_date = _parse_date(latest_date, "latest_date")
    if last_date < first_date:
        raise ValueError("latest_date must not be before earliest_date")
    validated_users = _validated_users(users)
    if not validated_users or max_slots == 0:
        return []

    candidate_start = datetime.combine(first_date, time.min, tzinfo=UTC)
    final_start = datetime.combine(last_date + timedelta(days=1), time.min, tzinfo=UTC)
    step = timedelta(minutes=step_minutes)
    duration = timedelta(minutes=duration_minutes)
    ranked: list[tuple[int, datetime, datetime, list[str], list[str]]] = []

    while candidate_start < final_start:
        candidate_end = candidate_start + duration
        available_ids = []
        unavailable_ids = []
        for user in validated_users:
            if _is_available(user, candidate_start, candidate_end):
                available_ids.append(user["id"])
            else:
                unavailable_ids.append(user["id"])
        if available_ids:
            ranked.append(
                (
                    len(available_ids),
                    candidate_start,
                    candidate_end,
                    available_ids,
                    unavailable_ids,
                )
            )
        candidate_start += step

    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected: list[tuple[int, datetime, datetime, list[str], list[str]]] = []
    for candidate in ranked:
        _, start, end, available_ids, _ = candidate
        available_set = frozenset(available_ids)
        if any(
            available_set == frozenset(chosen[3])
            and start < chosen[2]
            and end > chosen[1]
            for chosen in selected
        ):
            continue
        selected.append(candidate)
        if len(selected) >= max_slots:
            break

    return [
        {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "availableCount": count,
            "availableUserIds": available_ids,
            "unavailableUserIds": unavailable_ids,
        }
        for count, start, end, available_ids, unavailable_ids in selected
    ]
