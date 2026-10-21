import os
from typing import Any

try:
    from azure.cosmos import PartitionKey
    from azure.cosmos.database import DatabaseProxy
    from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
except ImportError:  # pragma: no cover - optional runtime dependency
    PartitionKey = None
    DatabaseProxy = Any  # type: ignore[misc,assignment]
    CosmosHttpResponseError = Exception  # type: ignore[misc,assignment]
    CosmosResourceNotFoundError = Exception  # type: ignore[misc,assignment]


def _throughput() -> int:
    value = os.getenv("COSMOS_DB_THROUGHPUT", "400")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 400


def _create_container(database: Any, container_id: str, partition_key: Any, **kwargs: Any) -> Any:
    """Create a container, reusing it if it already exists.

    Container creation can fail when the Cosmos account has a low total
    throughput limit. In that case we fall back to reading an existing
    container instead of aborting startup.
    """
    try:
        return database.create_container_if_not_exists(
            id=container_id,
            partition_key=partition_key,
            **kwargs,
        )
    except CosmosHttpResponseError as exc:
        message = str(exc).lower()
        if "throughput" in message or "ru/s" in message:
            try:
                container = database.get_container_client(container_id)
                container.read()
                return container
            except CosmosResourceNotFoundError:
                raise RuntimeError(
                    f"Unable to create Cosmos container '{container_id}': the account "
                    "throughput limit was reached and the container does not exist yet. "
                    "Increase the account throughput, delete the existing database so it "
                    "can be recreated with shared throughput, or create the container "
                    "manually."
                ) from exc
        raise


def ensure_database(client: Any) -> Any:
    """Create the configured database and containers if they do not exist."""
    if PartitionKey is None:
        raise RuntimeError("azure-cosmos is required. Install it with 'pip install azure-cosmos'.")

    database_name = os.getenv("COSMOS_DB_NAME", "when_to_meet")
    if not database_name:
        raise RuntimeError("COSMOS_DB_NAME must be configured")

    # Use shared (database-level) throughput so the containers share a single
    # RU/s budget instead of each consuming the 400 RU/s minimum.
    database = client.create_database_if_not_exists(
        id=database_name,
        offer_throughput=_throughput(),
    )
    _create_container(
        database,
        "users",
        PartitionKey(path="/email"),
        unique_key_policy={"uniqueKeys": [{"paths": ["/email"]}]},
    )
    _create_container(
        database,
        "meetings",
        PartitionKey(path="/id"),
    )
    return database
