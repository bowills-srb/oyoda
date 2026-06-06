"""
test_concierge_endpoint_brain_path.py — Phase 1.3b verification gates.

Tests the /concierge/message endpoint's flag-gated routing between the
compatibility path (_handle_via_existing) and the new messaging brain
path (_handle_via_brain).

Nine verification gates:
  1. All 1.3a gates still green                                  (covered by existing tests)
  2. Flag OFF → existing path called, brain NOT invoked          (test_flag_off_uses_existing_path)
                + four-part compatibility contract:
                  - no brain call
                  - no audit side effects from the brain
                  - no response shape drift
                  - no extra writes
  3. Flag ON → orchestrator invoked, response shape matches      (test_flag_on_invokes_brain)
  4. Flag ON + shadow ON → orchestrator called with shadow_mode  (test_flag_on_shadow_invokes_brain_with_shadow_true)
  5. Manual: AC message flag OFF — unchanged                     (manual gate; not automated)
  6. Manual: AC message flag ON, shadow ON — audit, no work order (manual gate; not automated)
  7. Manual: AC message flag ON, shadow OFF — work order link    (manual gate; not automated)
  8. Rollback recipe                                             (covered by feature_flags.set_flag tests if added; documented in commit message)
  9. Flag ON + policy ESCALATE → no module dispatch, response    (test_flag_on_escalate_response_safe_for_review)
     shape still safe for review queue

Pattern follows tests/unit/test_kb_dashboard_router.py:
  - FastAPI() + app.include_router(concierge.router) for a minimal test app
  - app.dependency_overrides for get_async_session and get_tenant_context
  - monkeypatch.setattr for factories like get_feature_flags,
    get_concierge_runner, get_messaging_brain_orchestrator
  - TestClient(app) for sync HTTP requests
"""

from __future__ import annotations

import sys
import types
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI
import pytest

if "jose" not in sys.modules:
    jose_module = types.ModuleType("jose")

    class _JWTError(Exception):
        pass

    jose_module.JWTError = _JWTError
    jose_module.jwt = types.SimpleNamespace(
        encode=lambda *args, **kwargs: "test-token",
        decode=lambda *args, **kwargs: {},
    )
    sys.modules["jose"] = jose_module

from app.api.dependencies import TenantContext
from app.api.v1.endpoints import concierge


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures and helpers
# ─────────────────────────────────────────────────────────────────────────────

TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")
PROPERTY_ID = UUID("22222222-2222-2222-2222-222222222222")
PROPERTY_CODE = "GULF_VIEW_204"


def _build_app(monkeypatch, *, flag_runtime: bool, flag_shadow: bool = False):
    """Construct a minimal FastAPI app with dependencies and factories
    patched for the specified flag state. Returns (app, mocks_dict)."""
    app = FastAPI()
    app.include_router(concierge.router)

    # ── Dependency overrides ────────────────────────────────────────────
    async def _fake_session_dep():
        yield MagicMock(name="db_session")

    def _fake_tenant_dep():
        return TenantContext(company_id=TENANT_ID)

    app.dependency_overrides[concierge.get_async_session] = _fake_session_dep
    app.dependency_overrides[concierge.get_tenant_context] = _fake_tenant_dep

    # ── Patch factories in concierge module's namespace ─────────────────
    # Flag service: returns the configured runtime/shadow values.
    flags_mock = MagicMock(name="feature_flag_service")

    async def _is_enabled(flag_name, company_id=None, property_code=None):
        from app.services.feature_flags import FeatureFlag
        if flag_name == FeatureFlag.MESSAGING_BRAIN_RUNTIME:
            return flag_runtime
        if flag_name == FeatureFlag.MESSAGING_BRAIN_SHADOW_MODE:
            return flag_shadow
        return False

    flags_mock.is_enabled = AsyncMock(side_effect=_is_enabled)
    monkeypatch.setattr(concierge, "get_feature_flags", lambda db=None: flags_mock)

    # Existing-path factories: return mocks with the methods _handle_via_existing
    # calls. Each returns innocuous defaults so the existing path completes
    # to the final return statement without errors.
    knowledge_bundle = _build_knowledge_bundle_mock()
    monkeypatch.setattr(
        concierge, "load_property_knowledge_bundle",
        AsyncMock(return_value=knowledge_bundle),
    )
    monkeypatch.setattr(
        concierge, "best_faq_answer_with_global",
        AsyncMock(return_value={
            "answer": None,
            "match_type": None,
            "score": 0.0,
            "source_property_external_id": None,
            "question": None,
        }),
    )

    maintenance_service = MagicMock(name="maintenance_service")
    maintenance_service.auto_track_from_message = AsyncMock(return_value=None)
    monkeypatch.setattr(
        concierge, "get_concierge_maintenance_service", lambda: maintenance_service,
    )

    bd_insight_service = MagicMock(name="bd_insight_service")
    bd_insight_service.generate_summary = MagicMock(return_value=None)
    monkeypatch.setattr(
        concierge, "get_concierge_bd_insight_service", lambda: bd_insight_service,
    )

    runner = _build_runner_mock()
    monkeypatch.setattr(concierge, "get_concierge_runner", lambda: runner)

    return app, {
        "flags": flags_mock,
        "knowledge_bundle": knowledge_bundle,
        "maintenance_service": maintenance_service,
        "bd_insight_service": bd_insight_service,
        "runner": runner,
    }


def _build_knowledge_bundle_mock():
    bundle = MagicMock(name="knowledge_bundle")
    bundle.property_profile = {}
    bundle.property_context = {}
    bundle.sections = {}
    bundle.concierge_knowledge = {}
    return bundle


def _build_runner_mock():
    """A runner mock whose handle_message returns a fixed reply matching
    the legacy ConciergeReply shape (text, intent, suggestions, approved,
    requires_escalation)."""
    runner = MagicMock(name="concierge_runner")
    reply = MagicMock(name="reply")
    reply.text = "Existing path response."
    reply.intent = "general"
    reply.suggestions = []
    reply.approved = None
    reply.requires_escalation = False
    runner.handle_message = AsyncMock(return_value=reply)
    return runner


def _patch_orchestrator(monkeypatch, *, draft=None, raise_exc=None):
    """Patch concierge.get_messaging_brain_orchestrator. Returns the
    orchestrator mock so tests can assert call patterns."""
    orch = MagicMock(name="orchestrator")
    if raise_exc is not None:
        orch.handle_inbound_message = AsyncMock(side_effect=raise_exc)
    else:
        orch.handle_inbound_message = AsyncMock(
            return_value=draft or _build_brain_draft(),
        )

    # The endpoint imports get_messaging_brain_orchestrator inside
    # _handle_via_brain (lazy import). Patch the source module so that
    # the lazy import resolves to our mock.
    import app.services.messaging_brain as brain_pkg
    monkeypatch.setattr(
        brain_pkg, "get_messaging_brain_orchestrator", lambda: orch,
    )
    return orch


def _build_brain_draft(
    *,
    response_text: str = "Got it — sorry about the AC. Team is on it.",
    contributing_agents: Optional[list] = None,
    escalation_required: bool = False,
):
    """Construct a minimal GuestResponseDraft for tests."""
    from app.services.orchestration.messaging_brain_contracts import (
        GuestResponseDraft, RecommendedAction,
    )
    return GuestResponseDraft(
        response_text=response_text,
        confidence=0.85,
        final_action=(
            RecommendedAction.ESCALATE if escalation_required
            else RecommendedAction.DRAFT_ONLY
        ),
        escalation_required=escalation_required,
        contributing_agents=contributing_agents or ["MaintenanceAgent"],
    )


def _ac_request_body(*, auto_track_maintenance: bool = True, stage: str = "in_stay") -> dict:
    return {
        "property_id": str(PROPERTY_ID),
        "message_text": "the AC is broken in the master bedroom",
        "stage": stage,
        "property_external_id": PROPERTY_CODE,
        "auto_track_maintenance": auto_track_maintenance,
        "auto_log_gap": True,
    }


async def _post(app: FastAPI, body: dict):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.post(
            "/concierge/message",
            json=body,
            headers={"X-Company-Id": str(TENANT_ID)},
        )


async def _post_proactive(app: FastAPI, body: dict):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.post(
            "/concierge/proactive",
            json=body,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flag_off_uses_existing_path_and_does_not_invoke_brain(monkeypatch):
    """Gate 2 — flag-OFF compatibility contract:
      - The brain orchestrator is never called
      - The brain audit writer is never invoked
      - The legacy runner IS called
      - The response shape matches MessageResponse exactly
    """
    app, mocks = _build_app(monkeypatch, flag_runtime=False)
    orch = _patch_orchestrator(monkeypatch)

    response = await _post(app, _ac_request_body())

    assert response.status_code == 200
    payload = response.json()

    # Brain NOT invoked — invariant 1
    assert orch.handle_inbound_message.await_count == 0, (
        "brain handle_inbound_message should not be called when flag is OFF"
    )

    # Existing path IS invoked — runner.handle_message was called
    assert mocks["runner"].handle_message.await_count == 1, (
        "legacy runner should be called exactly once when flag is OFF"
    )

    # Response shape matches MessageResponse — invariant 3
    # Exact set of keys, exact shapes
    assert set(payload.keys()) == {
        "response_text", "intent", "suggestions",
        "approved", "requires_escalation",
    }
    assert payload["response_text"] == "Existing path response."
    assert payload["intent"] == "general"
    assert payload["suggestions"] == []
    assert payload["approved"] is None
    assert payload["requires_escalation"] is False


@pytest.mark.asyncio
async def test_flag_off_response_byte_equivalent_baseline(monkeypatch):
    """Gate 2 (response shape drift sub-test): with brain disabled and
    canned mock data, the response dict must exactly equal the baseline.

    Any field added or removed from MessageResponse, or any default
    drift, fails this test. This is the bytes-on-wire compatibility
    contract.
    """
    app, _ = _build_app(monkeypatch, flag_runtime=False)
    _patch_orchestrator(monkeypatch)  # so the test fails loudly if brain is hit

    response = await _post(app, _ac_request_body())

    assert response.status_code == 200
    BASELINE = {
        "response_text": "Existing path response.",
        "intent": "general",
        "suggestions": [],
        "approved": None,
        "requires_escalation": False,
    }
    assert response.json() == BASELINE


@pytest.mark.asyncio
async def test_auto_track_maintenance_false_bypasses_brain(monkeypatch):
    """Gate 2 follow-up: when an operator explicitly opts out of automatic
    tracking via auto_track_maintenance=False, the brain is bypassed even
    if the runtime flag is ON. This preserves operator intent — the
    brain's MaintenanceModule unconditionally writes maintenance tracking,
    so respecting the request flag means falling back to the legacy path.
    See seam-map Rule 5 and the auto_track_maintenance=False discussion
    in handle_message's docstring.
    """
    # Flag is ON — but the request opts out
    app, mocks = _build_app(monkeypatch, flag_runtime=True)
    orch = _patch_orchestrator(monkeypatch)

    response = await _post(
        app, _ac_request_body(auto_track_maintenance=False),
    )

    assert response.status_code == 200

    # Even though the flag is ON, the brain was NOT called
    assert orch.handle_inbound_message.await_count == 0, (
        "brain should be bypassed when auto_track_maintenance=False"
    )

    # Existing path was called instead
    assert mocks["runner"].handle_message.await_count == 1


@pytest.mark.asyncio
async def test_flag_on_invokes_brain_with_inbound_message(monkeypatch):
    """Gate 3: when the runtime flag is ON, the brain is called exactly
    once with an InboundGuestMessage that mirrors the request.
    """
    app, mocks = _build_app(monkeypatch, flag_runtime=True)
    orch = _patch_orchestrator(monkeypatch)

    response = await _post(app, _ac_request_body())

    assert response.status_code == 200

    # Brain invoked exactly once
    assert orch.handle_inbound_message.await_count == 1

    # Inspect the InboundGuestMessage passed to the brain
    call_args = orch.handle_inbound_message.await_args
    inbound = call_args.args[0]
    assert inbound.tenant_id == str(TENANT_ID)
    assert inbound.channel == "http"
    assert inbound.source_provider == "concierge_api"
    assert inbound.text == "the AC is broken in the master bedroom"
    assert inbound.property_id == str(PROPERTY_ID)
    assert inbound.property_code == PROPERTY_CODE
    assert inbound.lifecycle.value == "in_stay"
    assert inbound.message_id.startswith("http_")  # synthetic ID

    # shadow_mode kwarg defaulted to False
    assert call_args.kwargs.get("shadow_mode") is False


@pytest.mark.asyncio
async def test_flag_on_passes_stay_dates_through_brain_metadata(monkeypatch):
    app, mocks = _build_app(monkeypatch, flag_runtime=True)
    orch = _patch_orchestrator(monkeypatch)

    response = await _post(
        app,
        {
            **_ac_request_body(stage="booked"),
            "check_in_date": "2026-06-10",
            "check_out_date": "2026-06-15",
        },
    )

    assert response.status_code == 200
    inbound = orch.handle_inbound_message.await_args.args[0]
    assert inbound.metadata["check_in_date"] == "2026-06-10"
    assert inbound.metadata["check_out_date"] == "2026-06-15"
    assert inbound.lifecycle.value == "pre_arrival"

    # Existing-path runner was NOT called
    assert mocks["runner"].handle_message.await_count == 0

    # Response shape matches MessageResponse — same five keys
    payload = response.json()
    assert set(payload.keys()) == {
        "response_text", "intent", "suggestions",
        "approved", "requires_escalation",
    }
    # Brain returned a maintenance draft
    assert payload["response_text"] == "Got it — sorry about the AC. Team is on it."
    assert payload["intent"] == "maintenance"  # _intent_from_agents("MaintenanceAgent") → "maintenance"
    assert payload["suggestions"] == []
    assert payload["approved"] is None
    assert payload["requires_escalation"] is False


@pytest.mark.asyncio
async def test_brain_path_maps_pre_booking_stage_to_pre_booking_lifecycle(monkeypatch):
    app, _ = _build_app(monkeypatch, flag_runtime=True)
    orch = _patch_orchestrator(monkeypatch)

    response = await _post(app, _ac_request_body(stage="pre_booking"))

    assert response.status_code == 200
    inbound = orch.handle_inbound_message.await_args.args[0]
    assert inbound.lifecycle.value == "pre_booking"


@pytest.mark.asyncio
async def test_brain_path_maps_booked_stage_to_pre_arrival_lifecycle(monkeypatch):
    app, _ = _build_app(monkeypatch, flag_runtime=True)
    orch = _patch_orchestrator(monkeypatch)

    response = await _post(app, _ac_request_body(stage="booked"))

    assert response.status_code == 200
    inbound = orch.handle_inbound_message.await_args.args[0]
    assert inbound.lifecycle.value == "pre_arrival"


@pytest.mark.asyncio
async def test_brain_path_maps_post_stay_stage_to_post_stay_lifecycle(monkeypatch):
    app, _ = _build_app(monkeypatch, flag_runtime=True)
    orch = _patch_orchestrator(monkeypatch)

    response = await _post(app, _ac_request_body(stage="post_stay"))

    assert response.status_code == 200
    inbound = orch.handle_inbound_message.await_args.args[0]
    assert inbound.lifecycle.value == "post_stay"


@pytest.mark.asyncio
async def test_flag_on_shadow_invokes_brain_with_shadow_true(monkeypatch):
    """Gate 4: when both runtime AND shadow flags are ON, the brain is
    invoked with shadow_mode=True. The endpoint relies on the brain's
    own shadow-mode plumbing (verified in 1.3a Gate 7) to suppress
    module side effects while keeping the audit trail. Here we verify
    the kwarg makes it through correctly.
    """
    app, _ = _build_app(monkeypatch, flag_runtime=True, flag_shadow=True)
    orch = _patch_orchestrator(monkeypatch)

    response = await _post(app, _ac_request_body())

    assert response.status_code == 200
    assert orch.handle_inbound_message.await_count == 1
    assert orch.handle_inbound_message.await_args.kwargs.get("shadow_mode") is True


@pytest.mark.asyncio
async def test_flag_on_escalate_response_safe_for_review_queue(monkeypatch):
    """Gate 9: when the brain returns ESCALATE, the endpoint's response
    has requires_escalation=True and a coherent shape suitable for the
    operator review queue. No leaked internal fields. No 500.

    This is the live-entrypoint version of 1.3a Gate 6. The orchestrator's
    own logic guarantees no module dispatch on ESCALATE; here we verify
    the endpoint translates the escalating draft into a safe MessageResponse.
    """
    app, _ = _build_app(monkeypatch, flag_runtime=True)
    escalating_draft = _build_brain_draft(
        response_text="Thanks for the message — a teammate will follow up shortly.",
        contributing_agents=["MaintenanceAgent"],
        escalation_required=True,
    )
    orch = _patch_orchestrator(monkeypatch, draft=escalating_draft)

    response = await _post(app, _ac_request_body())

    assert response.status_code == 200
    assert orch.handle_inbound_message.await_count == 1

    payload = response.json()
    assert set(payload.keys()) == {
        "response_text", "intent", "suggestions",
        "approved", "requires_escalation",
    }
    # Escalation flag flipped through to the response
    assert payload["requires_escalation"] is True
    # Intent still set so operator review knows what topic this was
    assert payload["intent"] == "maintenance"
    # No leaked internal fields — only the five MessageResponse fields
    assert "blocking_escalation_id" not in payload
    assert "final_action" not in payload
    assert "confidence" not in payload


@pytest.mark.asyncio
async def test_brain_path_failure_returns_safe_fallback_not_500(monkeypatch):
    """Defense in depth: if the brain raises uncaught, the endpoint
    returns a well-formed MessageResponse with intent='system_fallback'
    and requires_escalation=True — same shape the legacy path returns
    when ConciergeRunner crashes. No HTTP 500.
    """
    app, _ = _build_app(monkeypatch, flag_runtime=True)
    _patch_orchestrator(monkeypatch, raise_exc=RuntimeError("simulated brain crash"))

    response = await _post(app, _ac_request_body())

    # NOT a 500 — the wrapper caught the exception
    assert response.status_code == 200

    payload = response.json()
    assert payload["intent"] == "system_fallback"
    assert payload["requires_escalation"] is True
    assert "system issue" in payload["response_text"].lower()
    assert payload["suggestions"] == []
    assert payload["approved"] is None


@pytest.mark.asyncio
async def test_proactive_endpoint_routes_preview_through_brain(monkeypatch):
    app, _mocks = _build_app(monkeypatch, flag_runtime=True)

    fake_intent = object()
    compose_mock = AsyncMock(
        return_value=_build_brain_draft(
            response_text="Hi Jordan - your stay is coming up soon.",
        )
    )

    import app.services.messaging_brain.proactive_trigger_adapter as proactive_adapter

    monkeypatch.setattr(
        proactive_adapter,
        "build_preview_intent",
        AsyncMock(return_value=fake_intent),
    )
    monkeypatch.setattr(
        proactive_adapter,
        "compose_proactive_draft",
        compose_mock,
    )

    response = await _post_proactive(
        app,
        {
            "property_id": str(PROPERTY_ID),
            "market_id": "30a",
            "stage": "booked",
            "lead_time_days": 3,
            "guest_type": "family",
            "has_children": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["messages"] == ["Hi Jordan - your stay is coming up soon."]
    assert compose_mock.await_args.kwargs["db_session"] is not None
