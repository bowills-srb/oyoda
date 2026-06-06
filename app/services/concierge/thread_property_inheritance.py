from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.messaging_brain.property_resolution_writeback import (
    TRUSTED_MATCH_TYPES as WRITEBACK_TRUSTED_MATCH_TYPES,
)


logger = logging.getLogger(__name__)

_SAME_THREAD_TRUSTED_MATCH_TYPES = frozenset(
    {
        *WRITEBACK_TRUSTED_MATCH_TYPES,
        "platform_listing_id",
        "platform_unit_id",
        "external_id_hint",
        "raw_property_mention",
        "thread_inheritance",
    }
)


@dataclass(frozen=True)
class InheritedPropertyBinding:
    property_code: str
    inherited_from_message_id: str
    inherited_from_match_type: str
    inheritance_source: str


def _normalise_header_id(value: str) -> str:
    return (value or "").strip().strip("<>").strip().lower()


async def _property_exists(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    property_code: str,
) -> bool:
    row = await db.execute(
        text(
            """
            SELECT 1
            FROM properties
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND property_code = :property_code
            LIMIT 1
            """
        ),
        {
            "tenant_id": str(tenant_id),
            "property_code": property_code,
        },
    )
    return row.scalar_one_or_none() is not None


async def _inherit_from_same_thread(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    source_thread_id: str,
    current_message_id: str,
) -> Optional[InheritedPropertyBinding]:
    if not source_thread_id:
        return None
    rows = (
        await db.execute(
            text(
                """
                SELECT source_message_id, selected_property_code, selected_property_match_type
                FROM message_normalizations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND source_channel IN ('email', 'gmail')
                  AND source_thread_id = :source_thread_id
                  AND source_message_id <> :current_message_id
                  AND selected_property_code IS NOT NULL
                  AND selected_property_code <> ''
                ORDER BY created_at DESC
                LIMIT 10
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "source_thread_id": source_thread_id,
                "current_message_id": current_message_id or "",
            },
        )
    ).fetchall()
    for source_message_id, property_code, match_type in rows:
        prop = (property_code or "").strip()
        if not prop:
            continue
        if match_type and match_type not in _SAME_THREAD_TRUSTED_MATCH_TYPES:
            continue
        if await _property_exists(db, tenant_id=tenant_id, property_code=prop):
            return InheritedPropertyBinding(
                property_code=prop,
                inherited_from_message_id=(source_message_id or "").strip(),
                inherited_from_match_type=(match_type or "").strip(),
                inheritance_source="same_thread",
            )
    return None


async def _inherit_from_reply_headers(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    in_reply_to: str,
    references: Iterable[str],
) -> Optional[InheritedPropertyBinding]:
    candidate_rfc_ids: list[str] = []
    for raw in [in_reply_to, *(references or [])]:
        normalized = _normalise_header_id(raw)
        if normalized and normalized not in candidate_rfc_ids:
            candidate_rfc_ids.append(normalized)
    if not candidate_rfc_ids:
        return None

    rows = (
        await db.execute(
            text(
                """
                SELECT mn.source_message_id,
                       mn.selected_property_code,
                       mn.selected_property_match_type
                FROM gmail_processed_messages gpm
                JOIN message_normalizations mn
                  ON mn.source_message_id = gpm.gmail_message_id
                 AND mn.tenant_id = CAST(:tenant_id AS uuid)
                 AND mn.source_channel IN ('email', 'gmail')
                WHERE lower(trim(both '<>' from coalesce(gpm.rfc_message_id, ''))) = ANY(:candidate_rfc_ids)
                  AND mn.selected_property_code IS NOT NULL
                  AND mn.selected_property_code <> ''
                ORDER BY mn.created_at DESC
                LIMIT 10
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "candidate_rfc_ids": candidate_rfc_ids,
            },
        )
    ).fetchall()
    for source_message_id, property_code, match_type in rows:
        prop = (property_code or "").strip()
        resolved_match_type = (match_type or "").strip()
        if not prop or resolved_match_type not in WRITEBACK_TRUSTED_MATCH_TYPES:
            continue
        if await _property_exists(db, tenant_id=tenant_id, property_code=prop):
            return InheritedPropertyBinding(
                property_code=prop,
                inherited_from_message_id=(source_message_id or "").strip(),
                inherited_from_match_type=resolved_match_type,
                inheritance_source="reply_headers",
            )
    return None


async def inherit_property_from_thread_context(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    source_thread_id: str,
    current_message_id: str,
    in_reply_to: str = "",
    references: Optional[Iterable[str]] = None,
) -> Optional[InheritedPropertyBinding]:
    if not db:
        return None
    try:
        inherited = await _inherit_from_same_thread(
            db,
            tenant_id=tenant_id,
            source_thread_id=source_thread_id,
            current_message_id=current_message_id,
        )
        if inherited:
            return inherited
        return await _inherit_from_reply_headers(
            db,
            tenant_id=tenant_id,
            in_reply_to=in_reply_to,
            references=references or [],
        )
    except Exception as exc:
        logger.warning(
            "[ThreadPropertyInheritance] lookup failed tenant=%s thread_id=%s message_id=%s error=%s",
            tenant_id,
            source_thread_id,
            current_message_id,
            exc,
        )
        return None
