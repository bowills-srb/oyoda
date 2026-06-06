"""
API v1 router assembly.

The router is built lazily so importing a single endpoint module does not
eagerly import the entire API surface during tests or lightweight scripts.
"""

from fastapi import APIRouter

_ROUTER = None


def _build_router() -> APIRouter:
    from app.core.config import get_settings
    from app.api.v1.endpoints import (
        pricing,
        market,
        bd,
        properties,
        normalize,
        concierge,
        voice,
        phone,
        sms,
        pitch,
        documents,
        opportunity,
        projections,
        intelligence,
        dashboard,
        gateway,
        guest,
        market_intel,
        mobile_v2 as mobile,
        operator,
        operator_policies,
        operator_properties,
        owner_dashboard,
        knowledge,
        onboarding,
        watch,
        operator_dashboard,
        admin_llm_usage,
        agents,
        healer,
        operator_onboarding,
        messaging_webhooks,
        alert_contacts,
        canary_monitoring,
        incidents,
    )

    router = APIRouter()
    settings = get_settings()

    if not settings.focus_concierge_only:
        router.include_router(pricing.router, prefix="/pricing", tags=["Pricing Intelligence"])
    if not settings.focus_concierge_only:
        router.include_router(market.router, prefix="/market", tags=["Market Intelligence"])
    if not settings.focus_concierge_only:
        router.include_router(bd.router, prefix="/bd", tags=["Business Development"])
    if not settings.focus_concierge_only:
        router.include_router(properties.router, prefix="/properties", tags=["Properties"])
    if not settings.focus_concierge_only:
        router.include_router(normalize.router, prefix="/normalize", tags=["Data Normalization"])

    router.include_router(guest.router)
    router.include_router(concierge.router)
    router.include_router(voice.router)
    router.include_router(phone.router)
    router.include_router(sms.router)

    if not settings.focus_concierge_only:
        router.include_router(pitch.router)
    if not settings.focus_concierge_only:
        router.include_router(documents.router)
    if not settings.focus_concierge_only:
        router.include_router(opportunity.router)
    if not settings.focus_concierge_only:
        router.include_router(projections.router)
    if not settings.focus_concierge_only:
        router.include_router(intelligence.router)
    if not settings.focus_concierge_only:
        router.include_router(dashboard.router)
    if not settings.focus_concierge_only:
        router.include_router(gateway.router)

    if settings.enable_market_intel_api:
        router.include_router(market_intel.router)

    router.include_router(mobile.router)
    router.include_router(operator.router)
    router.include_router(operator_policies.router)
    router.include_router(operator_properties.router)

    from app.api.v1.endpoints.operator import _guest_router as _operator_guest_feedback_router
    router.include_router(_operator_guest_feedback_router)

    if not settings.focus_concierge_only:
        router.include_router(owner_dashboard.router)

    router.include_router(knowledge.router)

    if not settings.focus_concierge_only:
        router.include_router(onboarding.router)

    if settings.enable_watch_api:
        router.include_router(watch.router)

    router.include_router(operator_dashboard.router)
    router.include_router(admin_llm_usage.router)
    router.include_router(agents.router)
    router.include_router(healer.router)
    router.include_router(operator_onboarding.router)
    router.include_router(messaging_webhooks.router)
    router.include_router(alert_contacts.router)
    router.include_router(canary_monitoring.router)
    router.include_router(incidents.router)

    return router


def __getattr__(name: str):
    global _ROUTER
    if name != "router":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if _ROUTER is None:
        _ROUTER = _build_router()
    return _ROUTER


__all__ = ["router"]
