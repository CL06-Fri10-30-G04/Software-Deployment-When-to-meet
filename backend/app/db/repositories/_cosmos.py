import logging
from copy import deepcopy
from collections.abc import Callable, Sequence
from typing import Any

from azure.core import MatchConditions
from azure.cosmos.container import ContainerProxy
from azure.cosmos.exceptions import CosmosHttpResponseError

from ..exceptions import ConcurrencyError, NotFound

logger = logging.getLogger(__name__)
MAX_ETAG_RETRIES = 3
COSMOS_SYSTEM_FIELDS = {"_rid", "_self", "_ts", "_attachments", "_etag"}


def container_for(database: Any, container_name: str) -> ContainerProxy:
    return database.get_container_client(container_name)


def domain_document(document: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in document.items()
        if key not in COSMOS_SYSTEM_FIELDS
    }


def query_items(
    container: ContainerProxy,
    query: str,
    parameters: Sequence[dict[str, Any]],
    *,
    partition_key: str | None = None,
) -> list[dict[str, Any]]:
    def log_request_charge(headers: dict[str, str], _body: Any) -> None:
        charge = headers.get("x-ms-request-charge")
        if charge is not None:
            logger.debug("Cosmos query request charge: %s RU", charge)

    options: dict[str, Any] = {
        "query": query,
        "parameters": list(parameters),
        "enable_cross_partition_query": partition_key is None,
        "response_hook": log_request_charge,
    }
    if partition_key is not None:
        options["partition_key"] = partition_key
    return list(container.query_items(**options))


def read_item(
    container: ContainerProxy, item_id: str, partition_key: str
) -> dict[str, Any]:
    try:
        return container.read_item(item=item_id, partition_key=partition_key)
    except CosmosHttpResponseError as error:
        if error.status_code == 404:
            raise NotFound("document was not found") from error
        raise


def replace_with_etag_retry(
    container: ContainerProxy,
    item_id: str,
    partition_key: str,
    update: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    retries = 0
    while True:
        current = read_item(container, item_id, partition_key)
        etag = current.get("_etag")
        if not isinstance(etag, str):
            raise RuntimeError("Cosmos response did not include an ETag")
        current_domain = domain_document(current)
        updated = update(deepcopy(current_domain))
        if updated == current_domain:
            return current_domain
        try:
            result = container.replace_item(
                item=item_id,
                body=updated,
                etag=etag,
                match_condition=MatchConditions.IfNotModified,
            )
            return domain_document(result)
        except CosmosHttpResponseError as error:
            if error.status_code == 404:
                raise NotFound("document was not found") from error
            if error.status_code != 412:
                raise
            if retries >= MAX_ETAG_RETRIES:
                raise ConcurrencyError("document changed during repeated updates") from error
            retries += 1
