"""Historical metrics read back from Azure Monitor for the monitoring page.

Uses the app's managed identity (via DefaultAzureCredential), which needs the
Monitoring Reader role on the Container App and Application Insights resources.
Disabled unless the AZURE_MONITOR_* settings below are present.
"""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

REGION_VARIABLE = "AZURE_MONITOR_REGION"
CONTAINER_APP_VARIABLE = "AZURE_MONITOR_CONTAINER_APP_ID"
APP_INSIGHTS_VARIABLE = "AZURE_MONITOR_APP_INSIGHTS_ID"

# Range key -> (timespan, chart granularity).
RANGES = {
    "1h": (timedelta(hours=1), timedelta(minutes=1)),
    "6h": (timedelta(hours=6), timedelta(minutes=5)),
    "24h": (timedelta(hours=24), timedelta(minutes=15)),
}


@dataclass(frozen=True)
class MetricSpec:
    key: str
    name: str
    aggregation: str
    label: str
    unit: str


CONTAINER_APP_NAMESPACE = "Microsoft.App/containerapps"
CONTAINER_APP_METRICS = (
    MetricSpec("cpuPercent", "CpuPercentage", "Maximum", "CPU usage", "percent"),
    MetricSpec("memoryPercent", "MemoryPercentage", "Maximum", "Memory usage", "percent"),
    MetricSpec("networkIn", "RxBytes", "Total", "Network in", "bytes"),
    MetricSpec("networkOut", "TxBytes", "Total", "Network out", "bytes"),
    MetricSpec("requests", "Requests", "Total", "Requests", "count"),
    MetricSpec("responseTime", "ResponseTime", "Average", "Average response time", "ms"),
)

APP_INSIGHTS_NAMESPACE = "microsoft.insights/components"
APP_INSIGHTS_METRICS = (
    MetricSpec("serverResponseTime", "requests/duration", "Average", "Server response time", "ms"),
    MetricSpec(
        "processIo",
        "performanceCounters/processIOBytesPerSecond",
        "Average",
        "Process IO rate (disk I/O)",
        "bytesPerSecond",
    ),
    MetricSpec(
        "processCpu", "performanceCounters/processCpuPercentage", "Average", "Process CPU", "percent"
    ),
    MetricSpec(
        "processMemory",
        "performanceCounters/processPrivateBytes",
        "Average",
        "Process private bytes",
        "bytes",
    ),
    MetricSpec("dependencyDuration", "dependencies/duration", "Average", "Cosmos DB call time", "ms"),
    MetricSpec("failedRequests", "requests/failed", "Count", "Failed requests", "count"),
)

LATENCY_QUERY = """
AppRequests
| summarize
    p50 = percentile(DurationMs, 50),
    p95 = percentile(DurationMs, 95),
    p99 = percentile(DurationMs, 99),
    requests = sum(ItemCount)
    by bin(TimeGenerated, {bin})
| order by TimeGenerated asc
"""

SLOWEST_ROUTES_QUERY = """
AppRequests
| summarize requests = sum(ItemCount), avgMs = avg(DurationMs), p95Ms = percentile(DurationMs, 95) by Name
| order by p95Ms desc
| take 10
"""


@dataclass(frozen=True)
class AzureMonitorConfig:
    region: str | None
    container_app_id: str | None
    app_insights_id: str | None

    @classmethod
    def from_env(cls) -> "AzureMonitorConfig":
        return cls(
            region=os.getenv(REGION_VARIABLE) or None,
            container_app_id=os.getenv(CONTAINER_APP_VARIABLE) or None,
            app_insights_id=os.getenv(APP_INSIGHTS_VARIABLE) or None,
        )

    @property
    def configured(self) -> bool:
        return bool(self.container_app_id or self.app_insights_id)

    def missing(self) -> list[str]:
        missing = []
        if not self.container_app_id:
            missing.append(CONTAINER_APP_VARIABLE)
        if not self.app_insights_id:
            missing.append(APP_INSIGHTS_VARIABLE)
        if not self.region:
            missing.append(REGION_VARIABLE)
        return missing


def _error_text(error: Exception) -> str:
    message = getattr(error, "message", None) or str(error) or type(error).__name__
    return message.splitlines()[0][:300]


def _bin_text(granularity: timedelta) -> str:
    return f"{int(granularity.total_seconds() // 60)}m"


def _as_epoch_ms(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


def _default_credential() -> Any:
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential()


def _default_metrics_client(region: str, credential: Any) -> Any:
    from azure.monitor.querymetrics import MetricsClient

    return MetricsClient(f"https://{region}.metrics.monitor.azure.com", credential)


def _default_logs_client(credential: Any) -> Any:
    from azure.monitor.query import LogsQueryClient

    return LogsQueryClient(credential)


class AzureMonitorReader:
    def __init__(
        self,
        config: AzureMonitorConfig,
        credential_factory: Callable[[], Any] = _default_credential,
        metrics_client_factory: Callable[[str, Any], Any] = _default_metrics_client,
        logs_client_factory: Callable[[Any], Any] = _default_logs_client,
        cache_seconds: float = 60,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.config = config
        self._credential_factory = credential_factory
        self._metrics_client_factory = metrics_client_factory
        self._logs_client_factory = logs_client_factory
        self._cache_seconds = cache_seconds
        self._clock = clock
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._clients: tuple[Any, Any] | None = None

    def _get_clients(self) -> tuple[Any, Any]:
        if self._clients is None:
            credential = self._credential_factory()
            metrics = (
                self._metrics_client_factory(self.config.region, credential)
                if self.config.region
                else None
            )
            self._clients = (metrics, self._logs_client_factory(credential))
        return self._clients

    def read(self, range_key: str) -> dict[str, Any]:
        if not self.config.configured:
            return {"configured": False, "missing": self.config.missing()}
        with self._lock:
            cached = self._cache.get(range_key)
            if cached and self._clock() - cached[0] < self._cache_seconds:
                return cached[1]
        result = self._read_uncached(range_key)
        with self._lock:
            self._cache[range_key] = (self._clock(), result)
        return result

    def _read_uncached(self, range_key: str) -> dict[str, Any]:
        timespan, granularity = RANGES[range_key]
        result: dict[str, Any] = {
            "configured": True,
            "missing": self.config.missing(),
            "range": range_key,
            "granularitySeconds": int(granularity.total_seconds()),
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "containerApp": None,
            "appInsights": None,
        }
        try:
            metrics_client, logs_client = self._get_clients()
        except Exception as error:  # credential problems surface here
            logger.warning("Azure Monitor clients unavailable: %s", error)
            result["error"] = _error_text(error)
            return result

        with ThreadPoolExecutor(max_workers=8) as pool:
            if self.config.container_app_id:
                result["containerApp"] = self._read_metrics(
                    pool,
                    metrics_client,
                    self.config.container_app_id,
                    CONTAINER_APP_NAMESPACE,
                    CONTAINER_APP_METRICS,
                    timespan,
                    granularity,
                )
            if self.config.app_insights_id:
                app_insights = self._read_metrics(
                    pool,
                    metrics_client,
                    self.config.app_insights_id,
                    APP_INSIGHTS_NAMESPACE,
                    APP_INSIGHTS_METRICS,
                    timespan,
                    granularity,
                )
                latency = pool.submit(
                    self._query_logs,
                    logs_client,
                    LATENCY_QUERY.format(bin=_bin_text(granularity)),
                    timespan,
                )
                slowest = pool.submit(self._query_logs, logs_client, SLOWEST_ROUTES_QUERY, timespan)
                for key, future in (("latency", latency), ("slowestRoutes", slowest)):
                    try:
                        app_insights[key] = future.result()
                    except Exception as error:
                        logger.warning("Azure Monitor log query %s failed: %s", key, error)
                        app_insights[key] = []
                        app_insights["errors"][key] = _error_text(error)
                result["appInsights"] = app_insights
        return result

    def _read_metrics(
        self,
        pool: ThreadPoolExecutor,
        client: Any,
        resource_id: str,
        namespace: str,
        specs: tuple[MetricSpec, ...],
        timespan: timedelta,
        granularity: timedelta,
    ) -> dict[str, Any]:
        section: dict[str, Any] = {"metrics": {}, "errors": {}}
        if client is None:
            section["errors"]["metrics"] = f"{REGION_VARIABLE} is not set"
            return section
        futures = {
            spec.key: pool.submit(
                self._query_metric, client, resource_id, namespace, spec, timespan, granularity
            )
            for spec in specs
        }
        for spec in specs:
            try:
                points = futures[spec.key].result()
            except Exception as error:
                logger.warning("Azure Monitor metric %s failed: %s", spec.name, error)
                section["errors"][spec.key] = _error_text(error)
                points = []
            section["metrics"][spec.key] = {
                "label": spec.label,
                "unit": spec.unit,
                "aggregation": spec.aggregation,
                "points": points,
            }
        return section

    @staticmethod
    def _query_metric(
        client: Any,
        resource_id: str,
        namespace: str,
        spec: MetricSpec,
        timespan: timedelta,
        granularity: timedelta,
    ) -> list[dict[str, Any]]:
        results = client.query_resources(
            resource_ids=[resource_id],
            metric_namespace=namespace,
            metric_names=[spec.name],
            timespan=timespan,
            granularity=granularity,
            aggregations=[spec.aggregation],
        )
        attribute = spec.aggregation.lower()
        points = []
        for result in results:
            for metric in result.metrics:
                for series in metric.timeseries:
                    for value in series.data:
                        points.append(
                            {"t": _as_epoch_ms(value.timestamp), "v": getattr(value, attribute, None)}
                        )
        points.sort(key=lambda point: point["t"])
        return points

    def _query_logs(self, client: Any, query: str, timespan: timedelta) -> list[dict[str, Any]]:
        response = client.query_resource(self.config.app_insights_id, query, timespan=timespan)
        tables = getattr(response, "tables", None) or getattr(response, "partial_data", None) or []
        rows = []
        for table in tables:
            columns = list(table.columns)
            for row in table.rows:
                record = {}
                for column, value in zip(columns, row):
                    if isinstance(value, datetime):
                        record["t" if column == "TimeGenerated" else column] = _as_epoch_ms(value)
                    elif isinstance(value, float):
                        record[column] = round(value, 1)
                    else:
                        record[column] = value
                rows.append(record)
        return rows
