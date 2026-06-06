#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any, Dict, Optional

from app.services.observability.deployment_runtime import (
    get_guard_key,
    get_config_revision,
    get_deployment_runtime_snapshot,
    is_railway_runtime,
)


def _canonical_secret_fingerprints(snapshot: Dict[str, Any]) -> Dict[str, Optional[str]]:
    return {
        item["name"]: item["fingerprint"]
        for item in snapshot.get("critical_secrets", [])
    }


def _guard_payload(role: str, service_name: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "role": role,
        "service_name": service_name,
        "booted_at": snapshot["booted_at"],
        "pid": snapshot["pid"],
        "config_revision": snapshot["config_revision"],
        "railway_metadata": snapshot["railway_metadata"],
        "critical_secrets": _canonical_secret_fingerprints(snapshot),
    }


def _guard_key(service_name: str) -> str:
    return get_guard_key(service_name)


def _load_previous_payload(redis_url: str, service_name: str) -> Optional[Dict[str, Any]]:
    import redis

    client = redis.Redis.from_url(redis_url, decode_responses=True)
    raw = client.get(_guard_key(service_name))
    if not raw:
        return None
    return json.loads(raw)


def _store_payload(redis_url: str, service_name: str, payload: Dict[str, Any]) -> None:
    import redis

    client = redis.Redis.from_url(redis_url, decode_responses=True)
    stored_payload = dict(payload)
    stored_payload["recorded_at"] = stored_payload.get("recorded_at") or payload["booted_at"]
    client.set(_guard_key(service_name), json.dumps(stored_payload, sort_keys=True))


def _validate_rotation_contract(
    previous: Optional[Dict[str, Any]],
    current: Dict[str, Any],
) -> Optional[str]:
    current_revision = ((current.get("config_revision") or {}).get("value") or "").strip()
    if not current_revision:
        return (
            "Railway startup requires OYVODA_CONFIG_REVISION, CONFIG_REVISION, or SECRET_EPOCH. "
            "Set a non-secret revision marker and redeploy all services together."
        )

    if not previous:
        return None

    previous_revision = ((previous.get("config_revision") or {}).get("value") or "").strip()
    previous_secrets = dict(previous.get("critical_secrets") or {})
    current_secrets = dict(current.get("critical_secrets") or {})
    if previous_revision == current_revision and previous_secrets != current_secrets:
        changed = sorted(
            name
            for name in set(previous_secrets) | set(current_secrets)
            if previous_secrets.get(name) != current_secrets.get(name)
        )
        changed_csv = ", ".join(changed) if changed else "<unknown>"
        return (
            "Critical secret fingerprints changed without a config revision bump. "
            f"Service={current.get('service_name')} revision={current_revision} changed={changed_csv}. "
            "Bump OYVODA_CONFIG_REVISION (or CONFIG_REVISION / SECRET_EPOCH) and redeploy API, worker, and beat together."
        )

    return None


def run_guard(role: str, service_name: str, redis_url: Optional[str]) -> Dict[str, Any]:
    snapshot = get_deployment_runtime_snapshot()
    payload = _guard_payload(role=role, service_name=service_name, snapshot=snapshot)
    if not is_railway_runtime():
        return payload

    if not redis_url:
        raise RuntimeError(
            "Railway startup requires REDIS_URL so the deployment guard can validate config propagation."
        )

    previous = _load_previous_payload(redis_url, service_name)
    error = _validate_rotation_contract(previous, payload)
    if error:
        raise RuntimeError(error)

    _store_payload(redis_url, service_name, payload)
    return payload


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Oyvoda Railway bootstrap guard. Validates config revision / secret propagation before starting a service."
    )
    parser.add_argument("--role", required=True, help="Logical role: api, worker, or beat")
    parser.add_argument(
        "--service-name",
        default="",
        help="Service name override. Defaults to Railway service name or role.",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to exec after the guard passes. Prefix with -- to separate it from guard flags.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]

    service_name = (
        args.service_name.strip()
        or os.getenv("RAILWAY_SERVICE_NAME", "").strip()
        or args.role.strip()
    )
    redis_url = os.getenv("REDIS_URL", "").strip() or os.getenv("CELERY_BROKER_URL", "").strip()

    payload = run_guard(role=args.role.strip(), service_name=service_name, redis_url=redis_url or None)
    revision = ((payload.get("config_revision") or {}).get("value") or "").strip()
    print(
        f"[railway-bootstrap] service={service_name} role={args.role.strip()} "
        f"revision={revision or '<unset>'} booted_at={payload['booted_at']}",
        flush=True,
    )

    if not command:
        return 0

    completed = subprocess.run(command, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except RuntimeError as exc:
        print(f"[railway-bootstrap] ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
