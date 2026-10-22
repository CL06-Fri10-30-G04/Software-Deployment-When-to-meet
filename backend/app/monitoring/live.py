"""Live metrics measured inside this app process.

These cover the server that answers the request only. With several replicas,
each one reports its own figures; Azure Monitor gives the combined picture.
"""

import logging
import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import psutil
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Polling the monitoring API and health checks would drown out real traffic.
EXCLUDED_PATH_PREFIXES = ("/api/health", "/api/monitoring/")
STATIC_ROUTE_LABEL = "static files"


@dataclass(frozen=True)
class RequestRecord:
    timestamp: float
    method: str
    route: str
    status: int
    duration_ms: float


def _percentile(sorted_values: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile of an already sorted list."""
    if not sorted_values:
        return None
    index = max(0, math.ceil(fraction * len(sorted_values)) - 1)
    return sorted_values[index]


def _rounded(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def _duration_stats(durations: list[float]) -> dict[str, Any]:
    ordered = sorted(durations)
    return {
        "count": len(ordered),
        "avgMs": _rounded(sum(ordered) / len(ordered)) if ordered else None,
        "p50Ms": _rounded(_percentile(ordered, 0.50)),
        "p95Ms": _rounded(_percentile(ordered, 0.95)),
        "p99Ms": _rounded(_percentile(ordered, 0.99)),
        "maxMs": _rounded(ordered[-1]) if ordered else None,
    }


class RequestStats:
    """Keeps recent request timings in memory and summarises them."""

    def __init__(self, max_records: int = 20_000, clock: Callable[[], float] = time.time):
        self._records: deque[RequestRecord] = deque(maxlen=max_records)
        self._lock = threading.Lock()
        self._clock = clock

    def record(self, method: str, route: str, status: int, duration_ms: float) -> None:
        entry = RequestRecord(self._clock(), method, route, status, duration_ms)
        with self._lock:
            self._records.append(entry)

    def summary(
        self,
        window_seconds: int = 900,
        series_seconds: int = 3600,
        bucket_seconds: int = 60,
        top_routes: int = 15,
    ) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            records = list(self._records)

        recent = [entry for entry in records if entry.timestamp >= now - window_seconds]
        overall = _duration_stats([entry.duration_ms for entry in recent])
        overall["serverErrors"] = sum(1 for entry in recent if entry.status >= 500)
        overall["perMinute"] = round(len(recent) / (window_seconds / 60), 2)

        by_route: dict[tuple[str, str], list[RequestRecord]] = {}
        for entry in recent:
            by_route.setdefault((entry.method, entry.route), []).append(entry)
        routes = [
            {
                "method": method,
                "route": route,
                **_duration_stats([entry.duration_ms for entry in entries]),
                "serverErrors": sum(1 for entry in entries if entry.status >= 500),
            }
            for (method, route), entries in by_route.items()
        ]
        routes.sort(key=lambda row: (-row["count"], row["route"]))

        bucket_count = series_seconds // bucket_seconds
        first_bucket = math.floor(now / bucket_seconds) - bucket_count + 1
        buckets: list[list[float]] = [[] for _ in range(bucket_count)]
        for entry in records:
            index = math.floor(entry.timestamp / bucket_seconds) - first_bucket
            if 0 <= index < bucket_count:
                buckets[index].append(entry.duration_ms)
        series = []
        for index, durations in enumerate(buckets):
            stats = _duration_stats(durations)
            series.append(
                {
                    "t": int((first_bucket + index) * bucket_seconds * 1000),
                    "count": stats["count"],
                    "avgMs": stats["avgMs"],
                    "p95Ms": stats["p95Ms"],
                }
            )

        return {
            "windowSeconds": window_seconds,
            "bucketSeconds": bucket_seconds,
            "overall": overall,
            "routes": routes[:top_routes],
            "series": series,
        }


class RequestTimingMiddleware:
    """Times each HTTP request from arrival until its response is sent."""

    def __init__(self, app: ASGIApp, stats: RequestStats):
        self.app = app
        self.stats = stats

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].startswith(EXCLUDED_PATH_PREFIXES):
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status = 500

        async def send_with_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            route = getattr(scope.get("route"), "path", None) or STATIC_ROUTE_LABEL
            duration_ms = (time.perf_counter() - started) * 1000
            self.stats.record(scope["method"], route, status, duration_ms)


def _read_number(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def container_cpu_limit() -> float | None:
    """CPU cores this container may use, from cgroup v2 or v1, if limited."""
    cpu_max = _read_number(Path("/sys/fs/cgroup/cpu.max"))
    if cpu_max:
        quota, _, period = cpu_max.partition(" ")
        if quota != "max" and period:
            return int(quota) / int(period)
        return None
    quota = _read_number(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"))
    period = _read_number(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us"))
    if quota and period and int(quota) > 0:
        return int(quota) / int(period)
    return None


def container_memory_limit() -> int | None:
    """Memory limit in bytes from cgroup v2 or v1, if lower than the machine's RAM."""
    raw = _read_number(Path("/sys/fs/cgroup/memory.max")) or _read_number(
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    )
    if not raw or raw == "max":
        return None
    limit = int(raw)
    # cgroup v1 reports "unlimited" as a huge number.
    return limit if limit < psutil.virtual_memory().total else None


class SystemSampler:
    """Samples this process's CPU, memory, disk I/O and network use on a timer."""

    def __init__(
        self,
        interval_seconds: float = 5.0,
        history_seconds: int = 3600,
        process: psutil.Process | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.interval_seconds = interval_seconds
        self._process = process or psutil.Process()
        self._clock = clock
        self._samples: deque[dict[str, Any]] = deque(
            maxlen=int(history_seconds // interval_seconds)
        )
        self._previous: dict[str, Any] | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.cpu_limit_cores = container_cpu_limit() or psutil.cpu_count() or 1
        self.memory_limit_bytes = container_memory_limit() or psutil.virtual_memory().total

    def _read_totals(self) -> dict[str, Any]:
        cpu_times = self._process.cpu_times()
        totals: dict[str, Any] = {
            "wall": self._clock(),
            "cpuSeconds": cpu_times.user + cpu_times.system,
            "memoryBytes": self._process.memory_info().rss,
            "diskRead": None,
            "diskWrite": None,
            "networkIn": None,
            "networkOut": None,
        }
        try:
            io_counters = self._process.io_counters()
            totals["diskRead"] = io_counters.read_bytes
            totals["diskWrite"] = io_counters.write_bytes
        except (AttributeError, NotImplementedError, psutil.Error):
            pass
        network = psutil.net_io_counters()
        if network is not None:
            totals["networkIn"] = network.bytes_recv
            totals["networkOut"] = network.bytes_sent
        return totals

    def sample(self) -> dict[str, Any] | None:
        """Take a reading. Rates need two readings, so the first returns None."""
        totals = self._read_totals()
        with self._lock:
            previous, self._previous = self._previous, totals
        if previous is None:
            return None
        elapsed = totals["wall"] - previous["wall"]
        if elapsed <= 0:
            return None

        def rate(key: str) -> float | None:
            if totals[key] is None or previous[key] is None:
                return None
            return round(max(0, totals[key] - previous[key]) / elapsed, 1)

        cpu_cores_used = (totals["cpuSeconds"] - previous["cpuSeconds"]) / elapsed
        sample = {
            "t": int(totals["wall"] * 1000),
            "cpuPercent": round(cpu_cores_used / self.cpu_limit_cores * 100, 2),
            "memoryBytes": totals["memoryBytes"],
            "memoryPercent": round(totals["memoryBytes"] / self.memory_limit_bytes * 100, 2),
            "diskReadBytesPerSec": rate("diskRead"),
            "diskWriteBytesPerSec": rate("diskWrite"),
            "networkInBytesPerSec": rate("networkIn"),
            "networkOutBytesPerSec": rate("networkOut"),
        }
        with self._lock:
            self._samples.append(sample)
        return sample

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.sample()
            except Exception:  # pragma: no cover - keep sampling after a bad read
                logger.exception("System metrics sample failed")

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self.sample()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="system-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_seconds)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            samples = list(self._samples)
        if not samples:
            # Not started (e.g. no lifespan): take two quick readings for a rate.
            self.sample()
            time.sleep(0.2)
            latest = self.sample()
            samples = [latest] if latest else []
        return {
            "intervalSeconds": self.interval_seconds,
            "cpuLimitCores": round(self.cpu_limit_cores, 2),
            "memoryLimitBytes": self.memory_limit_bytes,
            "uptimeSeconds": int(self._clock() - self._process.create_time()),
            "latest": samples[-1] if samples else None,
            "series": samples,
        }
