"""
PRESERVATION STATUS (post-Phase-1, 2026-05-23):
This module is preserved for future product surface (pre-arrival,
in-stay, multi-guest, returning-guest personalization, BD-aware
messaging, etc.). It is not currently part of the active brain
runtime path. Do not delete in subsequent phases unless explicitly
retired by product decision.

When the relevant product surface is wired into the brain, this
module relocates to the appropriate messaging_brain/ subdirectory
and stops being marked as preserved.

Dining reservation service for concierge workflows.

This service provides a provider-agnostic interface for:
- searching restaurants
- checking reservation availability
- creating reservations

Current provider behavior:
- Uses the existing OpenTable task-execution tools when possible
- Falls back to a curated 30A catalog with booking links/phones
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agents.task_execution.tool_executor import (
    ActionRequest,
    get_tool_executor,
)

logger = logging.getLogger(__name__)


@dataclass
class RestaurantOption:
    name: str
    area: str
    cuisine: str
    phone: Optional[str] = None
    booking_url: Optional[str] = None


@dataclass
class DiningAvailability:
    restaurant: str
    date: str
    party_size: int
    available_times: List[str] = field(default_factory=list)
    booking_url: Optional[str] = None
    source: str = "fallback"


@dataclass
class DiningReservationResult:
    success: bool
    status: str
    message: str
    restaurant: str
    date: str
    time: str
    party_size: int
    confirmation_id: Optional[str] = None
    booking_url: Optional[str] = None
    source: str = "fallback"


class DiningReservationService:
    """
    Provider-agnostic dining reservation orchestration.

    This keeps booking logic out of MCP and gives us a single place
    to add real OpenTable/Resy/Tock API adapters later.
    """

    _catalog: List[RestaurantOption] = [
        RestaurantOption(
            name="The Bay",
            area="Santa Rosa Beach",
            cuisine="Seafood",
            phone="(850) 622-2291",
            booking_url="https://www.opentable.com",
        ),
        RestaurantOption(
            name="Bud & Alley's",
            area="Seaside",
            cuisine="Seafood",
            phone="(850) 231-5900",
            booking_url="https://www.opentable.com",
        ),
        RestaurantOption(
            name="Pescado",
            area="Rosemary Beach",
            cuisine="Coastal",
            phone="(850) 534-3005",
            booking_url="https://www.opentable.com",
        ),
        RestaurantOption(
            name="Havana Beach Bar & Grill",
            area="Rosemary Beach",
            cuisine="American",
            phone="(850) 588-2882",
            booking_url="https://www.opentable.com",
        ),
        RestaurantOption(
            name="Cafe Thirty-A",
            area="Santa Rosa Beach",
            cuisine="American",
            phone="(850) 231-2166",
            booking_url="https://www.opentable.com",
        ),
    ]

    async def search_restaurants(
        self,
        operator_id: str,
        query: str,
        date: Optional[str] = None,
        time: Optional[str] = None,
        party_size: int = 2,
        area: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search in curated catalog first; keep deterministic for concierge UX."""
        q = (query or "").strip().lower()
        area_q = (area or "").strip().lower()
        results: List[Dict[str, Any]] = []

        for r in self._catalog:
            hay = f"{r.name} {r.area} {r.cuisine}".lower()
            if q and q not in hay:
                continue
            if area_q and area_q not in r.area.lower():
                continue
            results.append(
                {
                    "name": r.name,
                    "area": r.area,
                    "cuisine": r.cuisine,
                    "phone": r.phone,
                    "booking_url": r.booking_url,
                }
            )

        # If no query match, provide top options to keep conversation moving.
        if not results:
            results = [
                {
                    "name": r.name,
                    "area": r.area,
                    "cuisine": r.cuisine,
                    "phone": r.phone,
                    "booking_url": r.booking_url,
                }
                for r in self._catalog[:5]
            ]

        return results[:8]

    async def check_availability(
        self,
        operator_id: str,
        restaurant_name: str,
        date: str,
        party_size: int,
        time: Optional[str] = None,
        area: Optional[str] = None,
    ) -> DiningAvailability:
        """
        Check availability using the existing OpenTable search tool.
        Falls back to static times + booking link if provider call fails.
        """
        pref_time = time or "19:00"
        request = ActionRequest(
            action_type="opentable_search",
            operator_id=operator_id,
            parameters={
                "restaurant_name": restaurant_name,
                "date": date,
                "time": pref_time,
                "party_size": party_size,
                "location": area or "30A, FL",
            },
        )

        try:
            result = await get_tool_executor().execute(request, skip_guardrails=True)
            if result.success:
                data = result.result_data
                return DiningAvailability(
                    restaurant=data.get("restaurant") or restaurant_name,
                    date=data.get("date") or date,
                    party_size=int(data.get("party_size") or party_size),
                    available_times=list(data.get("available_times") or []),
                    booking_url=data.get("booking_url"),
                    source="opentable_tool",
                )
        except Exception as exc:
            logger.warning("Dining availability lookup failed, using fallback: %s", exc)

        return DiningAvailability(
            restaurant=restaurant_name,
            date=date,
            party_size=party_size,
            available_times=["6:30 PM", "7:00 PM", "7:30 PM"],
            booking_url="https://www.opentable.com",
            source="fallback",
        )

    async def create_reservation(
        self,
        operator_id: str,
        restaurant_name: str,
        date: str,
        time: str,
        party_size: int,
        guest_name: str,
        guest_phone: Optional[str] = None,
        guest_email: Optional[str] = None,
        special_requests: Optional[str] = None,
        session_token: Optional[str] = None,
        db_session: Optional[AsyncSession] = None,
    ) -> DiningReservationResult:
        """
        Create reservation with provider tool.
        Requires an email for current OpenTable tool contract; uses a
        placeholder alias if guest email is unavailable.
        """
        safe_email = guest_email or "guest@beachhabitats30a.com"
        request = ActionRequest(
            action_type="opentable_book",
            operator_id=operator_id,
            parameters={
                "restaurant_name": restaurant_name,
                "date": date,
                "time": time,
                "party_size": party_size,
                "guest_name": guest_name,
                "guest_phone": guest_phone or "",
                "guest_email": safe_email,
                "special_requests": special_requests or "",
            },
        )

        request_payload = {
            "restaurant_name": restaurant_name,
            "date": date,
            "time": time,
            "party_size": party_size,
            "guest_name": guest_name,
            "guest_phone": guest_phone or "",
            "guest_email": safe_email,
            "special_requests": special_requests or "",
        }

        execution_error: Optional[str] = None
        try:
            result = await get_tool_executor().execute(request)
            if result.success:
                data = result.result_data
                reservation = DiningReservationResult(
                    success=True,
                    status="confirmed",
                    message=result.message,
                    restaurant=data.get("restaurant") or restaurant_name,
                    date=data.get("date") or date,
                    time=data.get("time") or time,
                    party_size=int(data.get("party_size") or party_size),
                    confirmation_id=data.get("confirmation_id"),
                    source="opentable_tool",
                )
                await self._persist_reservation_attempt(
                    operator_id=operator_id,
                    session_token=session_token,
                    guest_name=guest_name,
                    guest_phone=guest_phone,
                    guest_email=guest_email,
                    request_payload=request_payload,
                    result=reservation,
                    response_payload=data,
                    db_session=db_session,
                )
                return reservation

            # Approval-required is still a valid concierge outcome.
            if result.error_code == "APPROVAL_REQUIRED":
                reservation = DiningReservationResult(
                    success=False,
                    status="approval_required",
                    message=(
                        "I can place this reservation, but it requires a quick "
                        "team approval. I'll follow up as soon as it's confirmed."
                    ),
                    restaurant=restaurant_name,
                    date=date,
                    time=time,
                    party_size=party_size,
                    source="opentable_tool",
                )
                await self._persist_reservation_attempt(
                    operator_id=operator_id,
                    session_token=session_token,
                    guest_name=guest_name,
                    guest_phone=guest_phone,
                    guest_email=guest_email,
                    request_payload=request_payload,
                    result=reservation,
                    response_payload=result.result_data or {},
                    error=result.error_message or result.message,
                    db_session=db_session,
                )
                return reservation
            execution_error = result.error_message or result.message
        except Exception as exc:
            logger.warning("Dining reservation create failed, using fallback: %s", exc)
            execution_error = str(exc)

        reservation = DiningReservationResult(
            success=False,
            status="manual_handoff",
            message=(
                f"I couldn't auto-confirm {restaurant_name} right now, but you can "
                "book quickly using this link."
            ),
            restaurant=restaurant_name,
            date=date,
            time=time,
            party_size=party_size,
            booking_url="https://www.opentable.com",
            source="fallback",
        )
        await self._persist_reservation_attempt(
            operator_id=operator_id,
            session_token=session_token,
            guest_name=guest_name,
            guest_phone=guest_phone,
            guest_email=guest_email,
            request_payload=request_payload,
            result=reservation,
            response_payload={},
            error=execution_error,
            db_session=db_session,
        )
        return reservation

    async def _persist_reservation_attempt(
        self,
        operator_id: str,
        session_token: Optional[str],
        guest_name: str,
        guest_phone: Optional[str],
        guest_email: Optional[str],
        request_payload: Dict[str, Any],
        result: DiningReservationResult,
        response_payload: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        db_session: Optional[AsyncSession] = None,
    ) -> None:
        """Persist booking attempt for auditing; failures are non-fatal."""
        try:
            from db.models.concierge_dining_reservations import (
                ConciergeDiningReservationModel,
            )

            row = ConciergeDiningReservationModel(
                operator_id=operator_id,
                session_token=session_token,
                guest_name=guest_name,
                guest_phone=guest_phone,
                guest_email=guest_email,
                restaurant_name=result.restaurant,
                reservation_date=result.date,
                reservation_time=result.time,
                party_size=result.party_size,
                special_requests=request_payload.get("special_requests"),
                success=result.success,
                status=result.status,
                message=result.message,
                source=result.source,
                confirmation_id=result.confirmation_id,
                booking_url=result.booking_url,
                error=error,
                request_payload=request_payload,
                response_payload=response_payload or {},
            )

            if db_session is not None:
                db_session.add(row)
                await db_session.flush()
                return

            from app.core.database import get_db_session

            async with get_db_session() as session:
                session.add(row)
                await session.flush()
        except Exception as exc:
            logger.warning(
                "Dining reservation audit persistence failed (non-fatal): %s",
                exc,
            )


_dining_service: Optional[DiningReservationService] = None


def get_dining_service() -> DiningReservationService:
    global _dining_service
    if _dining_service is None:
        _dining_service = DiningReservationService()
    return _dining_service
