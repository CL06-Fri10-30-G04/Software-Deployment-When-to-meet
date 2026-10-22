import sys
import types

import pytest

from backend.app import telemetry
from backend.app.main import create_app


@pytest.fixture
def fake_azure_monitor(monkeypatch):
    """Replace configure_azure_monitor so tests never contact Azure."""
    calls = []
    module = types.ModuleType("azure.monitor.opentelemetry")
    module.configure_azure_monitor = lambda **kwargs: calls.append(kwargs)
    monkeypatch.setitem(sys.modules, "azure.monitor.opentelemetry", module)
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    return calls


def test_telemetry_is_off_without_a_connection_string(monkeypatch, fake_azure_monitor):
    monkeypatch.delenv(telemetry.CONNECTION_STRING_VARIABLE, raising=False)

    assert telemetry.configure_telemetry() is False
    assert fake_azure_monitor == []


def test_telemetry_is_configured_once_with_a_connection_string(
    monkeypatch, fake_azure_monitor
):
    monkeypatch.setenv(telemetry.CONNECTION_STRING_VARIABLE, "InstrumentationKey=test")

    assert telemetry.configure_telemetry() is True
    assert telemetry.configure_telemetry() is True

    assert fake_azure_monitor == [
        {
            "logger_name": "backend.app",
            "instrumentation_options": {"fastapi": {"enabled": False}},
        }
    ]
    assert telemetry.os.environ["OTEL_SERVICE_NAME"] == "when-to-meet"


def test_create_app_enables_telemetry_when_configured(monkeypatch, fake_azure_monitor):
    monkeypatch.setenv(telemetry.CONNECTION_STRING_VARIABLE, "InstrumentationKey=test")

    create_app(session_secret="test-session-secret")

    assert len(fake_azure_monitor) == 1


def test_health_checks_are_excluded_from_request_telemetry():
    exclude = telemetry.fastapi_telemetry_config()["exclude"]

    assert exclude({"type": "http", "path": "/api/health"}) is True
    assert exclude({"type": "http", "path": "/api/auth/login"}) is False
