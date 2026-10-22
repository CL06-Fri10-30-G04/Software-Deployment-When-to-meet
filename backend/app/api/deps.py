from typing import Any

from fastapi import Depends, Request

from ..db.connection import create_client
from ..db.exceptions import ValidationError
from ..db.repositories.users import get_user_by_id
from ..db.setup import ensure_database
from .errors import ApiError

SESSION_USER_KEY = "user_id"


def get_db(request: Request) -> Any:
    """Return the Cosmos database, connecting on first use.

    Tests replace this dependency through ``app.dependency_overrides``.
    """
    database = getattr(request.app.state, "db", None)
    if database is None:
        database = ensure_database(create_client())
        request.app.state.db = database
    return database


def unauthenticated() -> ApiError:
    return ApiError(401, "unauthenticated", "Authentication required.")


def current_user(request: Request, db: Any = Depends(get_db)) -> dict[str, Any]:
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        raise unauthenticated()
    try:
        user = get_user_by_id(db, user_id)
    except ValidationError:
        user = None
    if user is None:
        request.session.clear()
        raise unauthenticated()
    return user
