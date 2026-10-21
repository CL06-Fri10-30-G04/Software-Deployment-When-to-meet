import os
from typing import Any

try:
    from azure.cosmos import PartitionKey
    from azure.cosmos.database import DatabaseProxy
except ImportError:  # pragma: no cover - optional runtime dependency
    PartitionKey = None
    DatabaseProxy = Any  # type: ignore[misc,assignment]


def ensure_database(client: Any) -> Any:
    """Create the configured database and containers if they do not exist."""
    if PartitionKey is None:
        raise RuntimeError("azure-cosmos is required. Install it with 'pip install azure-cosmos'.")

    database_name = os.getenv("COSMOS_DB_NAME")
    if not database_name:
        raise RuntimeError("COSMOS_DB_NAME must be configured")

    database = client.create_database_if_not_exists(id=database_name)
    database.create_container_if_not_exists(
        id="users",
        partition_key=PartitionKey(path="/email"),
        unique_key_policy={"uniqueKeys": [{"paths": ["/email"]}]},
    )
    database.create_container_if_not_exists(
        id="meetings",
        partition_key=PartitionKey(path="/id"),
    )
    return database
