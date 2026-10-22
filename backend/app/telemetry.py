import logging
import os
from collections.abc import MutableMapping
from typing import Any

from fastapi.telemetry import TelemetryConfig

logger = logging.getLogger(__name__)

CONNECTION_STRING_VARIABLE = "APPLICATIONINSIGHTS_CONNECTION_STRING"
SERVICE_NAME = "when-to-meet"
# Health checks and the monitoring page's own polling are frequent and fast;
# tracing them would skew latency charts and add cost.
EXCLUDED_PATH_PREFIXES = ("/api/health", "/api/monitoring/")

_configured = False


def _is_excluded(scope: MutableMapping[str, Any]) -> bool:
    return str(scope.get("path", "")).startswith(EXCLUDED_PATH_PREFIXES)


def fastapi_telemetry_config() -> TelemetryConfig:
    """Settings for FastAPI's built-in OpenTelemetry request spans and metrics.

    FastAPI only emits telemetry once configure_telemetry() has installed providers.
    """
    return {
        "exclude": _is_excluded,
        # Per-request dependency/endpoint/serialization spans add volume, not insight.
        "operation_spans": False,
    }


def configure_telemetry() -> bool:
    """Send requests, dependencies, logs and performance counters to Application Insights.

    Telemetry is only enabled when APPLICATIONINSIGHTS_CONNECTION_STRING is set, so
    local runs and tests send nothing. Returns whether telemetry is enabled.
    """
    global _configured
    if _configured:
        return True
    if not os.getenv(CONNECTION_STRING_VARIABLE):
        return False

    from azure.monitor.opentelemetry import configure_azure_monitor

    os.environ.setdefault("OTEL_SERVICE_NAME", SERVICE_NAME)
    # Collect this app's own logs only, not the Azure SDK's.
    app_logger_name = __name__.rpartition(".")[0]
    configure_azure_monitor(
        logger_name=app_logger_name,
        # FastAPI's built-in telemetry already records each request.
        instrumentation_options={"fastapi": {"enabled": False}},
    )
    logging.getLogger(app_logger_name).setLevel(logging.INFO)
    _configured = True
    logger.info("Application Insights telemetry enabled")
    return True
