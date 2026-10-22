from types import SimpleNamespace

from backend.app.monitoring.live import RequestStats, SystemSampler


class FakeClock:
    def __init__(self, now=1_800_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def test_request_stats_summarise_recent_requests_by_route():
    clock = FakeClock()
    stats = RequestStats(clock=clock)
    for duration in (10, 20, 30, 40, 100):
        stats.record("GET", "/api/meetings", 200, duration)
    stats.record("POST", "/api/auth/login", 500, 5)
    clock.now -= 3600
    stats.record("GET", "/api/meetings", 200, 9999)  # outside the 15-minute window
    clock.now += 3600

    summary = stats.summary()

    overall = summary["overall"]
    assert overall["count"] == 6
    assert overall["p50Ms"] == 20
    assert overall["p95Ms"] == 100
    assert overall["maxMs"] == 100
    assert overall["serverErrors"] == 1
    meetings = summary["routes"][0]
    assert (meetings["method"], meetings["route"], meetings["count"]) == ("GET", "/api/meetings", 5)
    assert meetings["avgMs"] == 40
    assert len(summary["series"]) == 60
    assert summary["series"][-1]["count"] == 6


class FakeProcess:
    def __init__(self):
        self.cpu = 0.0
        self.rss = 100 * 1024 * 1024
        self.read = 0
        self.write = 0

    def cpu_times(self):
        return SimpleNamespace(user=self.cpu, system=0.0)

    def memory_info(self):
        return SimpleNamespace(rss=self.rss)

    def io_counters(self):
        return SimpleNamespace(read_bytes=self.read, write_bytes=self.write)

    def create_time(self):
        return 1_800_000_000.0 - 120


def test_system_sampler_turns_counters_into_rates():
    clock = FakeClock()
    process = FakeProcess()
    sampler = SystemSampler(process=process, clock=clock)
    sampler.cpu_limit_cores = 2
    sampler.memory_limit_bytes = 400 * 1024 * 1024

    assert sampler.sample() is None  # first reading only primes the counters
    clock.now += 10
    process.cpu += 5  # 5 CPU seconds in 10 s = half a core = 25% of 2 cores
    process.read += 1000
    process.write += 3000
    sample = sampler.sample()

    assert sample["cpuPercent"] == 25
    assert sample["memoryPercent"] == 25
    assert sample["diskReadBytesPerSec"] == 100
    assert sample["diskWriteBytesPerSec"] == 300
    snapshot = sampler.snapshot()
    assert snapshot["latest"] == sample
    assert snapshot["uptimeSeconds"] == 130
