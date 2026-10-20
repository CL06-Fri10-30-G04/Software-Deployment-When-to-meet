import os
from urllib.parse import urlparse

from azure.cosmos import CosmosClient

_LOCAL_EMULATOR_HOSTS = {"localhost", "127.0.0.1", "::1", "cosmos-emulator"}


def _environment_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise RuntimeError(f"{name} must be set to true or false")


def create_client() -> CosmosClient:
    """Create a Cosmos client from the configured endpoint and account key."""
    endpoint = os.getenv("COSMOS_ENDPOINT")
    key = os.getenv("COSMOS_KEY")
    if not endpoint:
        raise RuntimeError("COSMOS_ENDPOINT must be configured")
    if not key:
        raise RuntimeError("COSMOS_KEY must be configured")

    verify_ssl = _environment_bool("COSMOS_VERIFY_SSL", True)
    if not verify_ssl and urlparse(endpoint).hostname not in _LOCAL_EMULATOR_HOSTS:
        raise RuntimeError("COSMOS_VERIFY_SSL=false is allowed only for the local emulator")
    return CosmosClient(endpoint, key, connection_verify=verify_ssl)
