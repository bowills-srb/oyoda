"""Persistence helper for rich-context shadow-mode observations."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, TypedDict

from sqlalchemy import text


logger = logging.getLogger(__name__)


class ShadowExceptionEntry(TypedDict):
    type: str
    message: str


class ShadowExceptions(TypedDict, total=False):
    richness: ShadowExceptionEntry
    evidence: ShadowExceptionEntry
    preferences: ShadowExceptionEntry


def build_exception_entry(exc: BaseException) -> ShadowExceptionEntry:
    """Construct a structured exception entry for a sub-computation failure."""
    return {
        "type": type(exc).__name__,
        "message": str(exc)[:500],
    }


async def record_rich_context_shadow_observation(
    db: Any,
    *,
    tenant_id: str,
    property_code: Optional[str],
    message_id: str,
    intent: str,
    richness_shadow: Dict[str, Any],
    evidence_shadow: List[Dict[str, Any]],
    preferences_block_shadow: str,
    shadow_exceptions: ShadowExceptions,
) -> None:
    """Persist a single rich-context shadow observation row.

    Failures are logged at warning and swallowed; this writer must
    never raise into the inbound message path.
    """
    try:
        await db.execute(
            text(
                """
                INSERT INTO rich_context_shadow_observations (
                    tenant_id, property_code, message_id, intent,
                    richness_shadow, evidence_shadow,
                    preferences_block_shadow, shadow_exceptions
                ) VALUES (
                    :tenant_id, :property_code, :message_id, :intent,
                    CAST(:richness_shadow AS jsonb),
                    CAST(:evidence_shadow AS jsonb),
                    :preferences_block_shadow,
                    CAST(:shadow_exceptions AS jsonb)
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "property_code": property_code,
                "message_id": message_id,
                "intent": intent,
                "richness_shadow": json.dumps(richness_shadow),
                "evidence_shadow": json.dumps(evidence_shadow),
                "preferences_block_shadow": preferences_block_shadow,
                "shadow_exceptions": json.dumps(shadow_exceptions),
            },
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "rich_context_shadow: failed to record observation: %s",
            exc,
            exc_info=True,
        )
