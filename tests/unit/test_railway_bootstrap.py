from app.services.observability.deployment_runtime import get_deployment_runtime_snapshot
from scripts.railway_bootstrap import _guard_payload, _validate_rotation_contract


def _payload(revision: str, secrets: dict[str, str | None], *, service_name: str = "oyvoda") -> dict:
    snapshot = get_deployment_runtime_snapshot()
    snapshot["config_revision"] = {
        "name": "OYVODA_CONFIG_REVISION",
        "value": revision,
        "fingerprint": "fp",
    }
    snapshot["critical_secrets"] = [
        {"name": name, "present": value is not None, "fingerprint": value}
        for name, value in secrets.items()
    ]
    snapshot["railway_metadata"] = {"RAILWAY_SERVICE_NAME": service_name}
    return _guard_payload("api", service_name, snapshot)


def test_rotation_contract_requires_revision_marker():
    current = _payload("", {"GROQ_API_KEY": "abc"})

    error = _validate_rotation_contract(None, current)

    assert error is not None
    assert "requires OYVODA_CONFIG_REVISION" in error


def test_rotation_contract_allows_first_boot_with_revision():
    current = _payload("2026-05-29-1", {"GROQ_API_KEY": "abc"})

    error = _validate_rotation_contract(None, current)

    assert error is None


def test_rotation_contract_rejects_secret_change_without_revision_bump():
    previous = _payload("2026-05-29-1", {"GROQ_API_KEY": "abc"})
    current = _payload("2026-05-29-1", {"GROQ_API_KEY": "xyz"})

    error = _validate_rotation_contract(previous, current)

    assert error is not None
    assert "changed without a config revision bump" in error
    assert "GROQ_API_KEY" in error


def test_rotation_contract_allows_secret_change_with_revision_bump():
    previous = _payload("2026-05-29-1", {"GROQ_API_KEY": "abc"})
    current = _payload("2026-05-29-2", {"GROQ_API_KEY": "xyz"})

    error = _validate_rotation_contract(previous, current)

    assert error is None
