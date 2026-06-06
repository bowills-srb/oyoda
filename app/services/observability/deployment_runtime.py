from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


_BOOTED_AT = datetime.now(timezone.utc)
DEPLOY_GUARD_KEY_PREFIX = "oyvoda:deploy-guard"
DEFAULT_RUNTIME_SIGNAL_SERVICES = (
    "oyvoda",
    "oyvoda-worker",
    "oyvoda-beat",
)
_CONFIG_REVISION_ENV_NAMES = (
    "OYVODA_CONFIG_REVISION",
    "CONFIG_REVISION",
    "SECRET_EPOCH",
)
_RAILWAY_METADATA_ENV_NAMES = (
    "RAILWAY_PROJECT_ID",
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_SERVICE_ID",
    "RAILWAY_SERVICE_NAME",
    "RAILWAY_DEPLOYMENT_ID",
    "RAILWAY_REPLICA_ID",
    "RAILWAY_GIT_COMMIT_SHA",
    "RAILWAY_GIT_BRANCH",
    "RAILWAY_STATIC_URL",
)
_CRITICAL_SECRET_ENV_NAMES = (
    "ANTHROPIC_API_KEY",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ESCAPIA_API_KEY",
    "TWILIO_AUTH_TOKEN",
    "SENDGRID_API_KEY",
)


def _short_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _value_or_none(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def is_railway_runtime() -> bool:
    return any(_value_or_none(name) for name in _RAILWAY_METADATA_ENV_NAMES)


def get_config_revision() -> Dict[str, Any]:
    for name in _CONFIG_REVISION_ENV_NAMES:
        value = _value_or_none(name)
        if value:
            return {
                "name": name,
                "value": value,
                "fingerprint": _short_fingerprint(value),
            }
    return {
        "name": None,
        "value": None,
        "fingerprint": None,
    }


def get_secret_propagation_snapshot() -> List[Dict[str, Any]]:
    snapshot: List[Dict[str, Any]] = []
    for name in _CRITICAL_SECRET_ENV_NAMES:
        value = _value_or_none(name)
        snapshot.append(
            {
                "name": name,
                "present": bool(value),
                "fingerprint": _short_fingerprint(value) if value else None,
            }
        )
    return snapshot


def get_deployment_runtime_snapshot() -> Dict[str, Any]:
    metadata = {
        name: value
        for name in _RAILWAY_METADATA_ENV_NAMES
        if (value := _value_or_none(name))
    }
    secret_snapshot = get_secret_propagation_snapshot()
    present_secret_names = [item["name"] for item in secret_snapshot if item["present"]]
    missing_secret_names = [item["name"] for item in secret_snapshot if not item["present"]]
    return {
        "booted_at": _BOOTED_AT.isoformat(),
        "pid": os.getpid(),
        "railway_runtime": is_railway_runtime(),
        "config_revision": get_config_revision(),
        "railway_metadata": metadata,
        "critical_secrets": secret_snapshot,
        "critical_secret_summary": {
            "present_count": len(present_secret_names),
            "missing_count": len(missing_secret_names),
            "present_names": present_secret_names,
            "missing_names": missing_secret_names,
        },
    }


def get_guard_key(service_name: str) -> str:
    return f"{DEPLOY_GUARD_KEY_PREFIX}:{service_name}"


def get_runtime_signal_snapshot(
    redis_url: Optional[str],
    service_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    service_names = service_names or list(DEFAULT_RUNTIME_SIGNAL_SERVICES)
    signals: Dict[str, Any] = {
        "connected": False,
        "services": {},
        "error": None,
    }
    if not redis_url:
        signals["error"] = "REDIS_URL unavailable"
        for service_name in service_names:
            signals["services"][service_name] = {"present": False, "payload": None}
        return signals

    try:
        import redis

        client = redis.Redis.from_url(redis_url, decode_responses=True)
        signals["connected"] = True
        for service_name in service_names:
            raw = client.get(get_guard_key(service_name))
            payload = json.loads(raw) if raw else None
            signals["services"][service_name] = {
                "present": payload is not None,
                "payload": payload,
            }
    except Exception as exc:
        signals["error"] = str(exc)
        for service_name in service_names:
            signals["services"].setdefault(
                service_name,
                {"present": False, "payload": None},
            )
    return signals
