from typing import Any

from fastapi import APIRouter, Depends, Response

from ..db.exceptions import NotFound
from ..db.repositories.users import (
    add_unavailability,
    get_user_by_id,
    remove_unavailability,
    set_availability,
)
from .deps import current_user, get_db
from .schemas import AvailabilityRequest, UnavailabilityRequest

router = APIRouter(prefix="/api/me", tags=["availability"])


def _availability_view(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "timezone": user["timezone"],
        "availability": user["availability"],
        "unavailability": user["unavailability"],
    }


def _reload_user(db: Any, user_id: str) -> dict[str, Any]:
    user = get_user_by_id(db, user_id)
    if user is None:
        raise NotFound("user was not found")
    return user


@router.get("/availability")
def get_availability(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return _availability_view(user)


@router.put("/availability")
def put_availability(
    body: AvailabilityRequest,
    db: Any = Depends(get_db),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    set_availability(
        db, user["id"], [entry.model_dump(mode="json") for entry in body.availability]
    )
    return _availability_view(_reload_user(db, user["id"]))


@router.post("/unavailability", status_code=201)
def post_unavailability(
    body: UnavailabilityRequest,
    db: Any = Depends(get_db),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    item_id = add_unavailability(db, user["id"], body.model_dump(mode="json"))
    stored = _reload_user(db, user["id"])["unavailability"]
    return next(item for item in stored if item["id"] == item_id)


@router.delete("/unavailability/{item_id}", status_code=204)
def delete_unavailability(
    item_id: str,
    db: Any = Depends(get_db),
    user: dict[str, Any] = Depends(current_user),
) -> Response:
    remove_unavailability(db, user["id"], item_id)
    return Response(status_code=204)
