from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from app.core.database import get_db_session
from app.services.concierge.db_session_service import (
    DEFAULT_TENANT_ID,
    get_db_session_service,
)
from app.services.messaging_brain.session_channel_adapter import (
    run_session_channel_message,
)
from app.services.orchestration.messaging_brain_contracts import MessagingLifecycle

logger = logging.getLogger(__name__)


async def get_ai_response(
    message: str,
    property_context: dict,
    guest_name: str,
    property_name: str,
    operator_id: str = "op_beach_habitats",
    property_code: Optional[str] = None,
    session_token: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    tenant_id: Optional[str] = None,
) -> str:
    """
    Thin legacy wrapper onto the brain-owned session-channel runtime.

    Session C convergence target:
      - brain owns fast-paths, identity, context loading, routing, policy
      - this shim only resolves a session row (or minimal fallback row)
        and returns the brain's response text
    """
    del conversation_history  # legacy param retained for compatibility

    async with get_db_session() as db:
        db_row = await _resolve_session_row(
            db=db,
            session_token=session_token,
            tenant_id=tenant_id,
        )
        if db_row is None:
            db_row = _build_fallback_row(
                tenant_id=tenant_id or str(DEFAULT_TENANT_ID),
                property_context=property_context,
                guest_name=guest_name,
                property_name=property_name,
                property_code=property_code,
                operator_id=operator_id,
                session_token=session_token,
            )

        effective_tenant_id = getattr(db_row, "tenant_id", None) or tenant_id or str(DEFAULT_TENANT_ID)
        result = await run_session_channel_message(
            message_text=message,
            db_session=db,
            db_row=db_row,
            session_tenant_id=effective_tenant_id,
            token=session_token or str(getattr(db_row, "token", "") or ""),
            channel="web_session",
            source_provider="concierge_runner",
            fallback_support_phone=(property_context or {}).get("support_phone"),
            fallback_lifecycle=MessagingLifecycle.IN_STAY,
        )
        return result.response_text


async def _resolve_session_row(
    *,
    db: Any,
    session_token: Optional[str],
    tenant_id: Optional[str],
) -> Optional[Any]:
    if not session_token:
        return None

    bootstrap = get_db_session_service(DEFAULT_TENANT_ID)
    row = await bootstrap.get_session_by_token(db, session_token, tenant_agnostic=True)
    if row is not None:
        return row

    if tenant_id:
        try:
            scoped = get_db_session_service(tenant_id)
            return await scoped.get_session_by_token(db, session_token, tenant_agnostic=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[ai_concierge] scoped session lookup failed: %s", exc)
    return None


def _build_fallback_row(
    *,
    tenant_id: str,
    property_context: Optional[dict[str, Any]],
    guest_name: str,
    property_name: str,
    property_code: Optional[str],
    operator_id: str,
    session_token: Optional[str],
) -> Any:
    context = property_context if isinstance(property_context, dict) else {}
    return SimpleNamespace(
        tenant_id=tenant_id,
        token=session_token or "",
        phase="in_stay",
        property_code=property_code or "",
        property_name=property_name,
        property_context=context,
        operator_id=operator_id,
        guest_name=guest_name,
        guest_phone="",
        guest_email="",
        reservation_id="",
        property_id=None,
        check_in=None,
        check_out=None,
    )
