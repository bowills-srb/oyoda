from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from app.services.integrations.email_routing import decide_email_route


@dataclass
class EmailPipelineServices:
    find_active_session: Callable[[Any], Awaitable[Any]]
    evaluate_reservation_routing: Optional[Callable[[Any], Awaitable[Any]]]
    dispatch_system_event: Callable[[Any], Awaitable[str]]
    dispatch_in_stay: Callable[[Any, Any], Awaitable[str]]
    dispatch_confirmed_guest: Callable[[Any, Any], Awaitable[str]]
    dispatch_pre_booking: Callable[[Any], Awaitable[str]]


async def process_routed_email(
    parsed,
    *,
    services: EmailPipelineServices,
) -> str:
    """Shared route-and-dispatch orchestrator for inbound email messages."""
    decision = await decide_email_route(
        parsed,
        find_active_session=services.find_active_session,
        evaluate_reservation_routing=services.evaluate_reservation_routing,
    )
    if decision.routing_metadata:
        setattr(parsed, "_reservation_routing_metadata", decision.routing_metadata)

    if decision.route_kind == "system_event":
        return await services.dispatch_system_event(parsed)
    if decision.route_kind == "in_stay":
        return await services.dispatch_in_stay(parsed, decision.session_row)
    if decision.route_kind == "confirmed_guest":
        return await services.dispatch_confirmed_guest(parsed, decision.reservation_match)
    if decision.route_kind == "drop":
        return "dropped"
    return await services.dispatch_pre_booking(parsed)
