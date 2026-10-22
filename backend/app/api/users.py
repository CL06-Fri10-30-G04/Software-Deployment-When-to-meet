from typing import Any

from fastapi import APIRouter, Depends

from ..db.repositories._cosmos import container_for, domain_document, query_items
from .deps import current_user, get_db

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("")
def list_users(
    db: Any = Depends(get_db), _user: dict[str, Any] = Depends(current_user)
) -> list[dict[str, Any]]:
    users = query_items(
        container_for(db, "users"),
        "SELECT * FROM c WHERE c.type = @type",
        [{"name": "@type", "value": "user"}],
    )
    public_users = []
    for user in users:
        public_user = domain_document(user)
        public_user.pop("passwordHash", None)
        public_users.append(public_user)
    return public_users
