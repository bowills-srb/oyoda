import json
import sys
import types

from app.services.observability.deployment_runtime import (
    get_config_revision,
    get_deployment_runtime_snapshot,
    get_runtime_signal_snapshot,
    get_secret_propagation_snapshot,
    is_railway_runtime,
)


def test_config_revision_prefers_oyvoda_specific_env(monkeypatch):
    monkeypatch.setenv("CONFIG_REVISION", "generic-rev")
    monkeypatch.setenv("OYVODA_CONFIG_REVISION", "app-rev-42")

    revision = get_config_revision()

    assert revision["name"] == "OYVODA_CONFIG_REVISION"
    assert revision["value"] == "app-rev-42"
    assert revision["fingerprint"]


def test_secret_propagation_snapshot_redacts_values(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-secret-value")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    snapshot = {item["name"]: item for item in get_secret_propagation_snapshot()}

    assert snapshot["GROQ_API_KEY"]["present"] is True
    assert snapshot["GROQ_API_KEY"]["fingerprint"]
    assert "value" not in snapshot["GROQ_API_KEY"]
    assert snapshot["ANTHROPIC_API_KEY"]["present"] is False
    assert snapshot["ANTHROPIC_API_KEY"]["fingerprint"] is None


def test_deployment_runtime_snapshot_includes_railway_metadata(monkeypatch):
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "api")
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "dep-123")
    monkeypatch.setenv("SECRET_EPOCH", "2026-05-29-1")

    snapshot = get_deployment_runtime_snapshot()

    assert is_railway_runtime() is True
    assert snapshot["railway_runtime"] is True
    assert snapshot["railway_metadata"]["RAILWAY_SERVICE_NAME"] == "api"
    assert snapshot["railway_metadata"]["RAILWAY_DEPLOYMENT_ID"] == "dep-123"
    assert snapshot["config_revision"]["name"] == "SECRET_EPOCH"
    assert snapshot["config_revision"]["value"] == "2026-05-29-1"
    assert snapshot["critical_secret_summary"]["present_count"] >= 0


def test_runtime_signal_snapshot_reads_service_payloads(monkeypatch):
    class FakeRedisClient:
        def __init__(self, payloads):
            self.payloads = payloads

        def get(self, key):
            return self.payloads.get(key)

    payloads = {
        "oyvoda:deploy-guard:oyvoda": json.dumps(
            {"service_name": "oyvoda", "config_revision": {"value": "2026-05-29-1"}}
        ),
        "oyvoda:deploy-guard:oyvoda-worker": json.dumps(
            {"service_name": "oyvoda-worker", "config_revision": {"value": "2026-05-29-1"}}
        ),
    }
    fake_redis_module = types.SimpleNamespace(
        Redis=types.SimpleNamespace(
            from_url=lambda *args, **kwargs: FakeRedisClient(payloads)
        )
    )
    monkeypatch.setitem(sys.modules, "redis", fake_redis_module)

    signals = get_runtime_signal_snapshot("redis://example", ["oyvoda", "oyvoda-worker", "oyvoda-beat"])

    assert signals["connected"] is True
    assert signals["services"]["oyvoda"]["payload"]["config_revision"]["value"] == "2026-05-29-1"
    assert signals["services"]["oyvoda-worker"]["payload"]["service_name"] == "oyvoda-worker"
    assert signals["services"]["oyvoda-beat"]["present"] is False


def test_runtime_signal_snapshot_handles_missing_redis_url():
    signals = get_runtime_signal_snapshot(None, ["oyvoda"])

    assert signals["connected"] is False
    assert signals["error"] == "REDIS_URL unavailable"
    assert signals["services"]["oyvoda"]["present"] is False
