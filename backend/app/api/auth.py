from typing import Any

import bcrypt
from fastapi import APIRouter, Depends, Request

from ..db.exceptions import ValidationError
from ..db.repositories.users import create_user, get_user_for_auth
from .deps import SESSION_USER_KEY, current_user, get_db
from .errors import ApiError
from .schemas import LoginRequest, RegisterRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _invalid_credentials() -> ApiError:
    return ApiError(401, "invalid_credentials", "Invalid email or password.")


def _password_matches(password: str, password_hash: str) -> bool:
    password_bytes = password.encode("utf-8")
    # bcrypt only considers 72 bytes; create_user rejects longer passwords.
    if len(password_bytes) > 72:
        return False
    return bcrypt.checkpw(password_bytes, password_hash.encode("utf-8"))


@router.post("/register", status_code=201)
def register(
    body: RegisterRequest, request: Request, db: Any = Depends(get_db)
) -> dict[str, Any]:
    user = create_user(
        db,
        body.name,
        body.email,
        body.password,
        role=body.role,
        timezone=body.timezone,
    )
    request.session[SESSION_USER_KEY] = user["id"]
    return user


@router.post("/login")
def login(
    body: LoginRequest, request: Request, db: Any = Depends(get_db)
) -> dict[str, Any]:
    try:
        user = get_user_for_auth(db, body.email)
    except ValidationError:
        raise _invalid_credentials() from None
    if user is None or not _password_matches(body.password, user["passwordHash"]):
        raise _invalid_credentials()

    request.session.clear()
    request.session[SESSION_USER_KEY] = user["id"]
    user.pop("passwordHash", None)
    return user


@router.post("/logout")
def logout(request: Request) -> dict[str, bool]:
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return user
