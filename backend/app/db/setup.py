import os

from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos.database import DatabaseProxy


def ensure_database(client: CosmosClient) -> DatabaseProxy:
    """Create the configured database and containers if they do not exist."""
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
