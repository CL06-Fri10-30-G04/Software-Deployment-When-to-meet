import os
from uuid import uuid4

import pytest

from backend.app.db.connection import create_client
from backend.app.db.setup import ensure_database


@pytest.fixture(scope="session")
def cosmos_client():
    os.environ.setdefault("COSMOS_ENDPOINT", "http://127.0.0.1:8081")
    os.environ.setdefault("COSMOS_KEY", "emulator-local-not-a-secret")
    os.environ.setdefault("COSMOS_VERIFY_SSL", "false")
    client = create_client()
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(scope="session")
def cosmos_db(cosmos_client):
    previous_name = os.environ.get("COSMOS_DB_NAME")
    database_name = f"when_to_meet_test_{uuid4().hex}"
    os.environ["COSMOS_DB_NAME"] = database_name
    try:
        database = ensure_database(cosmos_client)
        yield database
    finally:
        cosmos_client.delete_database(database_name)
        if previous_name is None:
            os.environ.pop("COSMOS_DB_NAME", None)
        else:
            os.environ["COSMOS_DB_NAME"] = previous_name
