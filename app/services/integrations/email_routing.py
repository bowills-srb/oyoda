from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional


@dataclass
class EmailRouteDecision:
    route_kind: str
    session_row: Any = None
    reservation_match: Any = None
    routing_metadata: Optional[dict[str, Any]] = None


async def decide_email_route(
    parsed,
    *,
    find_active_session: Callable[[Any], Awaitable[Any]],
    evaluate_reservation_routing: Optional[Callable[[Any], Awaitable[Any]]] = None,
) -> EmailRouteDecision:
    """Classify a parsed inbound email before dispatch."""
    if getattr(parsed, "system_generated", False):
        return EmailRouteDecision(route_kind="system_event")

    session_row = await find_active_session(parsed)
    if session_row:
        return EmailRouteDecision(
            route_kind="in_stay",
            session_row=session_row,
            routing_metadata={
                "type": "reservation_routing_metadata",
                "lifecycle_routing_source": "concierge_session",
                "lifecycle_resolved": getattr(parsed, "lifecycle_stage", "") or "in_stay",
            },
        )

    if evaluate_reservation_routing is not None:
        reservation_decision = await evaluate_reservation_routing(parsed)
        if getattr(reservation_decision, "matched_reservation", None) is not None:
            return EmailRouteDecision(
                route_kind="confirmed_guest",
                reservation_match=reservation_decision.matched_reservation,
                routing_metadata=reservation_decision.parser_notes_payload(),
            )

    layer1_decision = (getattr(parsed, "intake_layer1_decision", "") or "").strip().lower()
    if layer1_decision == "admit":
        return EmailRouteDecision(
            route_kind="pre_booking",
            routing_metadata=(
                reservation_decision.parser_notes_payload()
                if evaluate_reservation_routing is not None
                else None
            ),
        )
    if layer1_decision == "drop":
        return EmailRouteDecision(
            route_kind="drop",
            routing_metadata=(
                reservation_decision.parser_notes_payload()
                if evaluate_reservation_routing is not None
                else None
            ),
        )
    if layer1_decision == "unclear":
        return EmailRouteDecision(
            route_kind="pre_booking",
            routing_metadata=(
                reservation_decision.parser_notes_payload()
                if evaluate_reservation_routing is not None
                else None
            ),
        )

    return EmailRouteDecision(
        route_kind="drop",
        routing_metadata=(
            reservation_decision.parser_notes_payload()
            if evaluate_reservation_routing is not None
            else None
        ),
    )
