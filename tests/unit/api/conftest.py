from copy import deepcopy
from itertools import count

import bcrypt
import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError
from fastapi.testclient import TestClient

from backend.app.api.deps import get_db
from backend.app.db.repositories.meetings import create_meeting
from backend.app.db.repositories.users import create_user
from backend.app.main import create_app

PASSWORD = "correct horse battery"

# Each query parameter the repositories send maps to a document predicate.
_QUERY_FILTERS = {
    "@type": lambda doc, value: doc.get("type") == value,
    "@id": lambda doc, value: doc.get("id") == value,
    "@email": lambda doc, value: doc.get("email") == value,
    "@ids": lambda doc, value: doc.get("id") in value,
    "@roles": lambda doc, value: doc.get("role") in value,
    "@uid": lambda doc, value: value in doc.get("participantIds", []),
}


class FakeContainer:
    """In-memory stand-in for the Cosmos ContainerProxy methods the repositories use."""

    def __init__(self, unique_field=None):
        self.items = {}
        self.unique_field = unique_field
        self.always_conflict = False
        self._etags = count(1)

    def _stored(self, document):
        stored = deepcopy(document)
        stored["_etag"] = f"etag-{next(self._etags)}"
        self.items[stored["id"]] = stored
        return deepcopy(stored)

    def create_item(self, body):
        duplicate = body["id"] in self.items or (
            self.unique_field is not None
            and any(
                item[self.unique_field] == body[self.unique_field]
                for item in self.items.values()
            )
        )
        if duplicate:
            raise CosmosHttpResponseError(status_code=409, message="Conflict")
        return self._stored(body)

    def read_item(self, item, partition_key):
        if item not in self.items:
            raise CosmosHttpResponseError(status_code=404, message="Not found")
        return deepcopy(self.items[item])

    def replace_item(self, item, body, etag, match_condition):
        if item not in self.items:
            raise CosmosHttpResponseError(status_code=404, message="Not found")
        if self.always_conflict or self.items[item]["_etag"] != etag:
            raise CosmosHttpResponseError(status_code=412, message="Precondition failed")
        return self._stored(body)

    def query_items(self, query, parameters, **_options):
        filters = [
            (_QUERY_FILTERS[parameter["name"]], parameter["value"])
            for parameter in parameters
        ]
        return [
            deepcopy(document)
            for document in self.items.values()
            if all(matches(document, value) for matches, value in filters)
        ]


class FakeDatabase:
    def __init__(self):
        self.containers = {
            "users": FakeContainer(unique_field="email"),
            "meetings": FakeContainer(),
        }

    def get_container_client(self, name):
        return self.containers[name]


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch):
    real_gensalt = bcrypt.gensalt
    monkeypatch.setattr(bcrypt, "gensalt", lambda rounds=4, prefix=b"2b": real_gensalt(4, prefix))


@pytest.fixture
def password():
    return PASSWORD


@pytest.fixture
def db():
    return FakeDatabase()


@pytest.fixture
def app(db):
    application = create_app(session_secret="test-session-secret")
    application.dependency_overrides[get_db] = lambda: db
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def make_user(db):
    def make(name="Alex", role="Staff", email=None):
        email = email or f"{name.lower().replace(' ', '.')}@example.com"
        return create_user(db, name, email, PASSWORD, role=role, timezone="UTC")

    return make


@pytest.fixture
def login_as(app):
    """Return a fresh TestClient logged in as the given user."""

    def login(user):
        user_client = TestClient(app)
        response = user_client.post(
            "/api/auth/login", json={"email": user["email"], "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
        return user_client

    return login


@pytest.fixture
def meeting_for(db):
    """Create a meeting on Mon 2 to Tue 3 Nov 2026 with the given creator and invitees."""

    def make(creator, invitees=(), duration=60):
        return create_meeting(
            db,
            creator["id"],
            "Planning",
            duration,
            "2026-11-02",
            "2026-11-03",
            [],
            [],
            [user["id"] for user in invitees],
            [],
        )

    return make
