from datetime import datetime, timezone
from types import SimpleNamespace

from backend.app.monitoring.azure import AzureMonitorConfig, AzureMonitorReader

CONTAINER_APP_ID = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.App/containerApps/app"
APP_INSIGHTS_ID = "/subscriptions/s/resourceGroups/rg/providers/microsoft.insights/components/ai"
T0 = datetime(2026, 10, 22, 1, 0, tzinfo=timezone.utc)


class FakeMetricsClient:
    def __init__(self, failing=()):
        self.calls = []
        self.failing = set(failing)

    def query_resources(self, *, resource_ids, metric_namespace, metric_names, aggregations, **_):
        self.calls.append((metric_namespace, metric_names[0]))
        if metric_names[0] in self.failing:
            raise RuntimeError(f"Metric {metric_names[0]} is not supported")
        attribute = aggregations[0].lower()
        values = [SimpleNamespace(timestamp=T0, **{attribute: 42.0})]
        series = SimpleNamespace(data=values)
        return [SimpleNamespace(metrics=[SimpleNamespace(timeseries=[series])])]


class FakeLogsClient:
    def query_resource(self, resource_id, query, timespan):
        assert resource_id == APP_INSIGHTS_ID
        if "percentile(DurationMs, 50)" in query:
            columns = ["TimeGenerated", "p50", "p95", "p99", "requests"]
            rows = [[T0, 12.34, 50.0, 80.0, 7]]
        else:
            columns = ["Name", "requests", "avgMs", "p95Ms"]
            rows = [["GET /api/meetings", 7, 20.0, 50.0]]
        return SimpleNamespace(tables=[SimpleNamespace(columns=columns, rows=rows)])


def make_reader(metrics_client, clock=None):
    config = AzureMonitorConfig(
        region="australiaeast",
        container_app_id=CONTAINER_APP_ID,
        app_insights_id=APP_INSIGHTS_ID,
    )
    return AzureMonitorReader(
        config,
        credential_factory=lambda: object(),
        metrics_client_factory=lambda region, credential: metrics_client,
        logs_client_factory=lambda credential: FakeLogsClient(),
        clock=clock or (lambda: 0.0),
    )


def test_unconfigured_reader_lists_missing_settings():
    reader = AzureMonitorReader(AzureMonitorConfig(None, None, None))

    assert reader.read("1h") == {
        "configured": False,
        "missing": [
            "AZURE_MONITOR_CONTAINER_APP_ID",
            "AZURE_MONITOR_APP_INSIGHTS_ID",
            "AZURE_MONITOR_REGION",
        ],
    }


def test_reader_collects_metrics_and_log_queries():
    metrics_client = FakeMetricsClient()

    result = make_reader(metrics_client).read("1h")

    assert result["configured"] is True
    assert result["granularitySeconds"] == 60
    cpu = result["containerApp"]["metrics"]["cpuPercent"]
    assert cpu["points"] == [{"t": int(T0.timestamp() * 1000), "v": 42.0}]
    assert ("Microsoft.App/containerapps", "CpuPercentage") in metrics_client.calls
    io = result["appInsights"]["metrics"]["processIo"]
    assert io["label"] == "Process IO rate (disk I/O)"
    assert result["appInsights"]["latency"] == [
        {"t": int(T0.timestamp() * 1000), "p50": 12.3, "p95": 50.0, "p99": 80.0, "requests": 7}
    ]
    assert result["appInsights"]["slowestRoutes"][0]["Name"] == "GET /api/meetings"


def test_one_failing_metric_does_not_hide_the_others():
    result = make_reader(FakeMetricsClient(failing={"ResponseTime"})).read("1h")

    container_app = result["containerApp"]
    assert "not supported" in container_app["errors"]["responseTime"]
    assert container_app["metrics"]["responseTime"]["points"] == []
    assert container_app["metrics"]["cpuPercent"]["points"]


def test_results_are_cached_per_range():
    now = [0.0]
    metrics_client = FakeMetricsClient()
    reader = make_reader(metrics_client, clock=lambda: now[0])

    reader.read("1h")
    calls_after_first = len(metrics_client.calls)
    reader.read("1h")
    assert len(metrics_client.calls) == calls_after_first

    now[0] = 61
    reader.read("1h")
    assert len(metrics_client.calls) == calls_after_first * 2
