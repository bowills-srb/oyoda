"""
test_brain_invariants.py — Structural invariants for the messaging brain.

Two categories:
  * Hard assertions enforced at runtime (import-time or register-time raises).
    These tests confirm the production setup is clean.
  * xfail tests for known, tracked violations that flip to passing when the
    named migration step lands.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# ── Repository root (two levels up from tests/unit/) ────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_no_duplicate_specialist_topics():
    """No two registered specialists claim the same topic.

    Enforced by register_specialist() in GuestMessageBrainOrchestrator.
    This test confirms the full production specialist set (all agents
    registered in __init__) is clean.
    """
    from app.services.messaging_brain.orchestrator import GuestMessageBrainOrchestrator

    # Constructor calls register_specialist for every default agent.
    # A topic overlap raises RuntimeError — so reaching here means clean.
    GuestMessageBrainOrchestrator()


def test_prompt_topics_subset_of_known_intent_topics():
    """Every topic in the LLM intake PROMPT is in KNOWN_INTENT_TOPICS.

    Enforced at module import time via _PROMPT_TOPICS assertion in
    llm_intake_agent.py. Importing the module here re-runs the check.
    """
    import app.services.messaging_brain.agents.llm_intake_agent  # noqa: F401


def test_auto_track_from_message_sole_writer_invariant():
    """BRAIN_SCHEMA_LOCKDOWN invariant 1.

    auto_track_from_message may only appear in two allowlisted files:
      - app/services/concierge/maintenance_service.py  (the definition)
      - app/services/messaging_brain/modules/maintenance_module.py  (the caller)

    Any other occurrence means a new caller has bypassed MaintenanceModule
    and written directly to concierge_maintenance_events — a schema violation.
    The /concierge/message legacy write was retired in Step 10.
    """
    # Search for actual call-sites (trailing paren) to exclude comment /
    # docstring mentions that legitimately name the symbol.
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py", "auto_track_from_message(", str(_REPO_ROOT / "app")],
        capture_output=True,
        text=True,
    )
    hitting_lines = [line for line in result.stdout.splitlines() if line.strip()]

    _ALLOWLIST = {
        str(_REPO_ROOT / "app/services/concierge/maintenance_service.py"),
        str(_REPO_ROOT / "app/services/messaging_brain/modules/maintenance_module.py"),
    }

    violations = [
        line for line in hitting_lines
        if not any(line.startswith(allowed) for allowed in _ALLOWLIST)
    ]

    assert not violations, (
        "auto_track_from_message called outside allowlisted files "
        "(BRAIN_SCHEMA_LOCKDOWN invariant 1 violated):\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_booking_data_provider_per_request_isolation():
    """Multi-PMS booking stack invariant: per-request isolation via injection,
    multiple registered providers permitted.

    Multiple concrete BookingDataProvider subclasses are allowed (one per PMS
    vendor). What must hold: each request binds exactly one provider via injection
    into BookingContextAgent. Verified structurally:

      - AdapterBackedBookingDataProvider routes by provider_key — adding a PMS
        means a new provider_key value, not a new subclass.
      - BookingContextAgent accepts data_provider by injection; per-request
        isolation is enforced by construction, not by singleton enforcement.
      - BookingContextAgent must remain (it is the per-request binder, not the
        module to be retired).
    """
    import inspect

    from app.services.connectors.adapter_backed_booking_data_provider import (
        AdapterBackedBookingDataProvider,
    )
    from app.services.connectors.booking_data_provider import BookingDataProvider
    from app.services.messaging_brain.agents.booking_context_agent import BookingContextAgent

    assert issubclass(AdapterBackedBookingDataProvider, BookingDataProvider)

    assert hasattr(AdapterBackedBookingDataProvider, "provider_key"), (
        "AdapterBackedBookingDataProvider must expose provider_key for multi-PMS dispatch; "
        "new PMS systems are a new provider_key value, not a new subclass."
    )

    sig = inspect.signature(BookingContextAgent.__init__)
    assert "data_provider" in sig.parameters, (
        "BookingContextAgent must accept data_provider injection — do not delete this module; "
        "it is the per-request isolation mechanism."
    )
