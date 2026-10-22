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


def resolve_db(request: Request) -> Any:
    """get_db for code that only needs the database some of the time.

    Honours ``app.dependency_overrides`` the way ``Depends(get_db)`` would.
    """
    override = request.app.dependency_overrides.get(get_db)
    return override() if override else get_db(request)


def unauthenticated() -> ApiError:
    return ApiError(401, "unauthenticated", "Authentication required.")


def current_user(request: Request) -> dict[str, Any]:
    # Checks the session before touching the database, so logged-out requests
    # get a 401 even when the database is unreachable.
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        raise unauthenticated()
    try:
        user = get_user_by_id(resolve_db(request), user_id)
    except ValidationError:
        user = None
    if user is None:
        request.session.clear()
        raise unauthenticated()
    return user


def require_admin(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if user.get("role") != "Admin":
        raise ApiError(403, "forbidden", "Only Admin users can view monitoring.")
    return user
