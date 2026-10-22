import os
from urllib.parse import urlparse

try:
    from azure.cosmos import CosmosClient
except ImportError:  # pragma: no cover - optional runtime dependency
    CosmosClient = None  # type: ignore[assignment]

try:
    from azure.identity import DefaultAzureCredential
except ImportError:  # pragma: no cover - optional runtime dependency
    DefaultAzureCredential = None  # type: ignore[assignment]

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


def create_client():
    """Create a Cosmos client from configuration.

    Uses an account key when ``COSMOS_KEY`` is provided (local emulator or
    key-based deployments). Otherwise falls back to Azure managed identity /
    ``DefaultAzureCredential``, which is appropriate for staging and production
    container apps.
    """
    if CosmosClient is None:
        raise RuntimeError("azure-cosmos is required. Install it with 'pip install azure-cosmos'.")

    endpoint = os.getenv("COSMOS_ENDPOINT")
    if not endpoint:
        raise RuntimeError("COSMOS_ENDPOINT must be configured")

    verify_ssl = _environment_bool("COSMOS_VERIFY_SSL", True)
    if not verify_ssl and urlparse(endpoint).hostname not in _LOCAL_EMULATOR_HOSTS:
        raise RuntimeError("COSMOS_VERIFY_SSL=false is allowed only for the local emulator")

    key = os.getenv("COSMOS_KEY")
    if key:
        return CosmosClient(endpoint, key, connection_verify=verify_ssl)

    if DefaultAzureCredential is None:
        raise RuntimeError(
            "azure-identity is required for managed-identity authentication. "
            "Install it with 'pip install azure-identity'."
        )

    credential = DefaultAzureCredential()
    return CosmosClient(endpoint, credential=credential, connection_verify=verify_ssl)
