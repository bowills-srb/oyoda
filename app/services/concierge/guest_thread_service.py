"""
Unified guest thread service.

Creates one durable thread identity that can span:
  - pre-booking inquiries
  - booked / in-stay sessions
  - escalations

The old system rebuilt this relationship at read time using loose string
matching. This service establishes and reuses a persisted thread id at write
time so downstream workflow state can hang off a stable spine.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _normalise_guest_name(name: Optional[str]) -> str:
    value = " ".join((name or "").strip().lower().split())
    return value[:255]


class GuestThreadService:
    async def ensure_inquiry_thread(
        self,
        db: AsyncSession,
        *,
        tenant_id: Optional[str],
        property_code: Optional[str],
        guest_name: Optional[str],
        inquiry_thread_id: Optional[str],
    ) -> str:
        return await self._ensure_thread(
            db,
            tenant_id=tenant_id,
            property_code=property_code,
            guest_name=guest_name,
            inquiry_thread_id=inquiry_thread_id,
        )

    async def ensure_session_thread(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        property_code: Optional[str],
        guest_name: Optional[str],
        session_token: Optional[str],
    ) -> str:
        return await self._ensure_thread(
            db,
            tenant_id=tenant_id,
            property_code=property_code,
            guest_name=guest_name,
            session_token=session_token,
        )

    async def ensure_escalation_thread(
        self,
        db: AsyncSession,
        *,
        tenant_id: Optional[str],
        property_code: Optional[str],
        guest_name: Optional[str],
        session_token: Optional[str],
        inquiry_thread_id: Optional[str] = None,
    ) -> str:
        return await self._ensure_thread(
            db,
            tenant_id=tenant_id,
            property_code=property_code,
            guest_name=guest_name,
            session_token=session_token,
            inquiry_thread_id=inquiry_thread_id,
        )

    async def _ensure_thread(
        self,
        db: AsyncSession,
        *,
        tenant_id: Optional[str],
        property_code: Optional[str],
        guest_name: Optional[str],
        session_token: Optional[str] = None,
        inquiry_thread_id: Optional[str] = None,
    ) -> str:
        guest_name_norm = _normalise_guest_name(guest_name)
        tenant_clause = "tenant_id = CAST(:tenant_id AS uuid)" if tenant_id else "tenant_id IS NULL"
        params = {
            "tenant_id": tenant_id,
            "property_code": property_code or "",
            "guest_name": (guest_name or "").strip(),
            "guest_name_norm": guest_name_norm,
            "session_token": session_token or "",
            "inquiry_thread_id": inquiry_thread_id or "",
        }

        queries = [
            f"""
            SELECT guest_thread_id
            FROM guest_threads
            WHERE {tenant_clause}
              AND session_token = NULLIF(:session_token, '')
            LIMIT 1
            """,
            f"""
            SELECT guest_thread_id
            FROM guest_threads
            WHERE {tenant_clause}
              AND inquiry_thread_id = NULLIF(:inquiry_thread_id, '')
            LIMIT 1
            """,
        ]
        if property_code and guest_name_norm:
            queries.append(
                f"""
                SELECT guest_thread_id
                FROM guest_threads
                WHERE {tenant_clause}
                  AND property_code = NULLIF(:property_code, '')
                  AND guest_name_norm = :guest_name_norm
                ORDER BY updated_at DESC
                LIMIT 1
                """
            )
        for query in queries:
            row = (await db.execute(text(query), params)).scalar_one_or_none()
            if row:
                guest_thread_id = str(row)
                await self._refresh_thread(
                    db,
                    guest_thread_id=guest_thread_id,
                    session_token=session_token,
                    inquiry_thread_id=inquiry_thread_id,
                    property_code=property_code,
                    guest_name=guest_name,
                    guest_name_norm=guest_name_norm,
                )
                return guest_thread_id

        row = (
            await db.execute(
                text(
                    """
                    INSERT INTO guest_threads (
                        guest_thread_id,
                        tenant_id,
                        property_code,
                        guest_name,
                        guest_name_norm,
                        inquiry_thread_id,
                        session_token,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        gen_random_uuid(),
                        CAST(NULLIF(:tenant_id, '') AS uuid),
                        NULLIF(:property_code, ''),
                        NULLIF(:guest_name, ''),
                        :guest_name_norm,
                        NULLIF(:inquiry_thread_id, ''),
                        NULLIF(:session_token, ''),
                        NOW(),
                        NOW()
                    )
                    RETURNING guest_thread_id
                    """
                ),
                params,
            )
        ).scalar_one()
        return str(row)

    async def _refresh_thread(
        self,
        db: AsyncSession,
        *,
        guest_thread_id: str,
        session_token: Optional[str],
        inquiry_thread_id: Optional[str],
        property_code: Optional[str],
        guest_name: Optional[str],
        guest_name_norm: str,
    ) -> None:
        await db.execute(
            text(
                """
                UPDATE guest_threads
                SET property_code = COALESCE(NULLIF(:property_code, ''), property_code),
                    guest_name = COALESCE(NULLIF(:guest_name, ''), guest_name),
                    guest_name_norm = CASE
                        WHEN :guest_name_norm <> '' THEN :guest_name_norm
                        ELSE guest_name_norm
                    END,
                    inquiry_thread_id = COALESCE(NULLIF(:inquiry_thread_id, ''), inquiry_thread_id),
                    session_token = COALESCE(NULLIF(:session_token, ''), session_token),
                    updated_at = NOW()
                WHERE guest_thread_id = CAST(:guest_thread_id AS uuid)
                """
            ),
            {
                "guest_thread_id": guest_thread_id,
                "property_code": property_code or "",
                "guest_name": (guest_name or "").strip(),
                "guest_name_norm": guest_name_norm,
                "inquiry_thread_id": inquiry_thread_id or "",
                "session_token": session_token or "",
            },
        )


_service: Optional[GuestThreadService] = None


def get_guest_thread_service() -> GuestThreadService:
    global _service
    if _service is None:
        _service = GuestThreadService()
    return _service
