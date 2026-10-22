# HTTP API contract

This contract is derived from the calls the frontend makes in `frontend/js/`.
All request and response bodies are JSON. Timestamps are ISO-8601 UTC strings,
dates are `YYYY-MM-DD`, clock times are `HH:MM`.

## Conventions

- **Auth**: session cookie set by `register` and `login`, cleared by `logout`.
  Every endpoint except `register`, `login`, `logout` and `health` requires it.
- **Users** are never returned with `passwordHash`.
- **Errors** always have the body `{"error": "<code>", "message": "<text>"}`.

| Status | `error`                    | When                                                  |
| ------ | -------------------------- | ----------------------------------------------------- |
| 400    | `validation_error`         | Body fails validation, or data violates the contract  |
| 401    | `unauthenticated`          | No valid session                                      |
| 401    | `invalid_credentials`      | Login email/password do not match                     |
| 403    | `forbidden`                | The user may not perform this action                  |
| 404    | `not_found`                | Meeting, user, participant or item does not exist     |
| 409    | `duplicate_email`          | Registering an email that is already registered       |
| 409    | `participants_unavailable` | Finalising a slot some participants can't attend      |
| 409    | `concurrency_conflict`     | The document kept changing during the update; retry   |
| 500    | `internal_error`           | Unexpected server failure                             |

## Types

**User**

```json
{
  "id": "uuid", "type": "user", "name": "Alex", "email": "alex@example.com",
  "role": "Admin | Manager | Senior Staff | Staff | Junior Staff | null",
  "timezone": "Australia/Melbourne",
  "availability": [Availability], "unavailability": [Unavailability],
  "createdAt": "timestamp", "updatedAt": "timestamp"
}
```

**Availability**: `{"dayOfWeek": 0-6 (0 = Sunday), "start": "HH:MM", "end": "HH:MM"}`

**Unavailability**: one of

```json
{"id": "uuid", "label": "Dentist", "type": "once", "start": "timestamp", "end": "timestamp"}
{"id": "uuid", "label": "Gym", "type": "recurring", "daysOfWeek": [1, 3],
 "startTime": "HH:MM", "endTime": "HH:MM", "recurUntil": "YYYY-MM-DD | null"}
```

**Meeting**

```json
{
  "id": "uuid", "type": "meeting", "name": "Planning", "creatorId": "uuid",
  "durationMinutes": 30, "earliestDate": "YYYY-MM-DD", "latestDate": "YYYY-MM-DD",
  "inviteRules": {"includeRoles": [], "excludeRoles": [], "includeUserIds": [], "excludeUserIds": []},
  "participants": [{"userId": "uuid", "name": "Alex", "role": "Staff", "response": "pending | accepted | declined"}],
  "participantIds": ["uuid"],
  "candidateSlots": [Slot],
  "status": "scheduling | scheduled | cancelled",
  "finalSlot": {"start": "timestamp", "end": "timestamp", "forced": false, "unavailableUserIds": []} | null,
  "createdAt": "timestamp", "updatedAt": "timestamp"
}
```

**Slot**: `{"start", "end", "availableCount", "availableUserIds", "unavailableUserIds"}`

**Editor** of a meeting: its creator, or any user with role `Admin` or `Manager`.

## Health

| Method | Path          | Response                 |
| ------ | ------------- | ------------------------ |
| GET    | `/api/health` | 200 `{"status": "ok"}`   |

## Auth

| Method | Path                 | Body                                                    | Response          |
| ------ | -------------------- | ------------------------------------------------------- | ----------------- |
| POST   | `/api/auth/register` | `{name, email, password, role?: Role \| null, timezone?}` | 201 User, logs in |
| POST   | `/api/auth/login`    | `{email, password}`                                     | 200 User          |
| POST   | `/api/auth/logout`   | none                                                    | 200 `{"ok": true}` |
| GET    | `/api/auth/me`       | none                                                    | 200 User          |

`register` returns 409 `duplicate_email` for a taken email. `login` returns
401 `invalid_credentials` for an unknown email or a wrong password.

## Users

| Method | Path         | Response     |
| ------ | ------------ | ------------ |
| GET    | `/api/users` | 200 `[User]` |

## Availability (current user)

| Method | Path                            | Body                         | Response                                             |
| ------ | ------------------------------- | ---------------------------- | ---------------------------------------------------- |
| GET    | `/api/me/availability`          | none                         | 200 `{timezone, availability, unavailability}`       |
| PUT    | `/api/me/availability`          | `{availability: [Availability]}` | 200 `{timezone, availability, unavailability}`   |
| POST   | `/api/me/unavailability`        | Unavailability without `id`  | 201 Unavailability (with its new `id`)               |
| DELETE | `/api/me/unavailability/{id}`   | none                         | 204, 404 if no such item                             |

## Meetings

| Method | Path                                         | Body                                   | Who            | Response        |
| ------ | -------------------------------------------- | -------------------------------------- | -------------- | --------------- |
| GET    | `/api/meetings`                              | none                                   | any user       | 200 `[Meeting]` where the user is a participant |
| POST   | `/api/meetings`                              | see below                              | any user       | 201 Meeting     |
| GET    | `/api/meetings/{id}`                         | none                                   | participant or editor | 200 Meeting |
| POST   | `/api/meetings/{id}/participants`            | `{userId}`                             | editor         | 200 Meeting     |
| DELETE | `/api/meetings/{id}/participants/{userId}`   | none                                   | editor         | 200 Meeting     |
| POST   | `/api/meetings/{id}/respond`                 | `{response: "accepted" \| "declined"}` | participant    | 200 Meeting     |
| POST   | `/api/meetings/{id}/cancel`                  | none                                   | editor         | 200 Meeting     |
| POST   | `/api/meetings/{id}/find-slots`              | none                                   | participant or editor | 200 Meeting with fresh `candidateSlots` |
| POST   | `/api/meetings/{id}/finalise`                | `{slot: {start, end}, force?: false}`  | editor         | 200 Meeting     |

Create body:

```json
{
  "name": "Planning", "durationMinutes": 30,
  "earliestDate": "YYYY-MM-DD", "latestDate": "YYYY-MM-DD",
  "includeRoles": [], "excludeRoles": [], "includeUserIds": [], "excludeUserIds": []
}
```

The creator is always a participant with response `accepted`. Explicit
`includeUserIds` take precedence over `includeRoles`; exclusions are applied after.

Adding or removing a participant clears `candidateSlots` and `finalSlot` and
returns the meeting to `scheduling`. Removing the creator is a 400.

`finalise` accepts only a slot that is among the current `candidateSlots`
(otherwise 400). If any participant is unavailable in that slot it returns
409 `participants_unavailable` unless `force` is `true`, in which case
`finalSlot.forced` is `true` and `finalSlot.unavailableUserIds` lists them.

## Calendar

| Method | Path | Query | Response |
| ------ | ---- | ----- | -------- |
| GET | `/api/calendar` | see below | 200 `{start, end, items: [CalendarItem]}` |

Query parameters:

| Name | Required | Values |
| ---- | -------- | ------ |
| `start`, `end` | yes | ISO-8601 timestamps; `end` after `start`, at most 62 days apart |
| `show` | no | `all` (default), `attending` (you accepted), `invited` (you haven't replied), `declined`, `created` (you created it) |
| `role` | no | A Role: meetings with at least one participant of that role |
| `scope` | no | `mine` (default): meetings you're in. `everyone`: all meetings, Admin and Manager only (403 `forbidden` otherwise) |
| `cancelled` | no | `true` to include cancelled meetings (default `false`) |

A scheduled meeting is included when its `finalSlot` overlaps `[start, end)`.
A meeting still being planned is included when its `earliestDate`–`latestDate`
range overlaps the dates of `start`–`end`. Items are sorted by start time
(planned meetings by `earliestDate`).

**CalendarItem**

```json
{
  "id": "uuid", "name": "Planning", "status": "scheduling | scheduled | cancelled",
  "start": "timestamp | null", "end": "timestamp | null", "forced": false,
  "earliestDate": "YYYY-MM-DD", "latestDate": "YYYY-MM-DD", "durationMinutes": 60,
  "creatorId": "uuid", "creatorName": "Alex",
  "myResponse": "accepted | pending | declined | null",
  "participantCount": 3, "acceptedCount": 2,
  "roles": ["Manager", "Staff"]
}
```

`start`/`end` are the final slot, or `null` while the meeting is being planned.
`myResponse` is `null` when you aren't a participant (only possible with
`scope=everyone`).

## Monitoring (Admin only)

| Method | Path | Query | Response |
| ------ | ---- | ----- | -------- |
| GET | `/api/monitoring/live` | none | 200 `{system, requests}`: this server's CPU, memory, disk I/O and network samples for the last hour, and request latency stats |
| GET | `/api/monitoring/azure` | `range=1h\|6h\|24h` (default `1h`) | 200 Azure Monitor metrics for the range, or `{configured: false, missing: [...]}` when not set up |
| GET | `/monitoring.html` | none | The monitoring page. Logged out: 303 to `login.html`. Not Admin: 403 page |

Both API endpoints return 401 `unauthenticated` when logged out and
403 `forbidden` for users whose role is not `Admin`. See `docs/monitoring.md`.
