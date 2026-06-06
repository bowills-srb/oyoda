from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

TRUSTED_MATCH_TYPES = frozenset(
    {
        "canonical_ref",
        "pms_exact",
        "address_exact",
        "community_unique",
    }
)


class PropertyResolutionWriteback:
    """Propagate trusted property resolution to pre_booking_inquiries."""

    async def writeback_for_inquiry(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        draft_id: str,
        resolved_property_code: str,
        match_type: str,
    ) -> bool:
        resolved_property_code = (resolved_property_code or "").strip()
        draft_id = (draft_id or "").strip()
        match_type = (match_type or "").strip()
        if not resolved_property_code or not draft_id:
            return False
        if match_type not in TRUSTED_MATCH_TYPES:
            logger.debug(
                "[PropertyResolutionWriteback] skipped non-trusted match_type=%s draft_id=%s",
                match_type,
                draft_id,
            )
            return False

        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT property_external_id
                        FROM pre_booking_inquiries
                        WHERE company_id = CAST(:tid AS uuid)
                          AND draft_id = :draft_id
                        LIMIT 1
                        """
                    ),
                    {"tid": str(tenant_id), "draft_id": draft_id},
                )
            ).fetchone()
            if not row:
                logger.warning(
                    "[PropertyResolutionWriteback] inquiry not found draft_id=%s tenant=%s",
                    draft_id,
                    tenant_id,
                )
                return False

            current_property_id = str(row[0] or "").strip()
            if current_property_id == resolved_property_code:
                return False

            audit_payload = {
                "previous_value": current_property_id or None,
                "new_value": resolved_property_code,
                "source": "brain_resolution",
                "match_type": match_type,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            await session.execute(
                text(
                    """
                    UPDATE pre_booking_inquiries
                    SET property_external_id = :new_property,
                        property_external_id_source = CAST(:audit AS jsonb)
                    WHERE company_id = CAST(:tid AS uuid)
                      AND draft_id = :draft_id
                    """
                ),
                {
                    "tid": str(tenant_id),
                    "draft_id": draft_id,
                    "new_property": resolved_property_code,
                    "audit": json.dumps(audit_payload),
                },
            )
            await session.commit()
            logger.info(
                "[PropertyResolutionWriteback] writeback draft_id=%s previous=%s new=%s match_type=%s",
                draft_id,
                current_property_id or "(empty)",
                resolved_property_code,
                match_type,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[PropertyResolutionWriteback] failed draft_id=%s error=%s",
                draft_id,
                exc,
            )
            try:
                await session.rollback()
            except Exception:
                pass
            return False


_SERVICE: Optional[PropertyResolutionWriteback] = None


def get_property_resolution_writeback() -> PropertyResolutionWriteback:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = PropertyResolutionWriteback()
    return _SERVICE
