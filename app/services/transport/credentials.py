from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def normalize_channel(channel: str) -> str:
    value = (channel or "").strip().lower()
    if value in {"google", "gmail"}:
        return "gmail"
    if value in {"microsoft", "outlook", "office365", "m365"}:
        return "outlook"
    return value


@dataclass(frozen=True)
class OperatorCredentialRecord:
    """Operator-scoped credential payload for a transport provider."""

    operator_id: str
    channel: str
    tenant_id: Optional[str] = None
    watched_address: str = ""
    credential_blob: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


class OperatorCredentialStore(ABC):
    """Abstract credential lookup service used by the transport factory."""

    @abstractmethod
    async def get_transport_credentials(
        self,
        *,
        operator_id: str,
        channel: str,
        tenant_id: Optional[str] = None,
    ) -> Optional[OperatorCredentialRecord]:
        """Return a normalized credential record or None if not configured."""


class SqlOperatorCredentialStore(OperatorCredentialStore):
    """SQL-backed operator credential store.

    Phase 1 intentionally supports the currently-lived inbox credential table
    (`operator_gmail_creds`) for Gmail and Outlook/Microsoft. Future PMS inbox
    transports can extend this store or provide a separate implementation
    without changing the transport contract.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_transport_credentials(
        self,
        *,
        operator_id: str,
        channel: str,
        tenant_id: Optional[str] = None,
    ) -> Optional[OperatorCredentialRecord]:
        normalized_channel = normalize_channel(channel)
        if normalized_channel not in {"gmail", "outlook"}:
            return None

        result = await self.db.execute(
            text(
                """
                SELECT
                    gc.operator_id,
                    gc.tenant_id,
                    gc.watched_email,
                    gc.refresh_token,
                    COALESCE(gc.email_provider, 'gmail') AS email_provider
                FROM operator_gmail_creds gc
                WHERE gc.operator_id = :operator_id
                  AND (:tenant_id = '' OR gc.tenant_id = CAST(:tenant_id AS uuid))
                ORDER BY gc.created_at DESC NULLS LAST
                LIMIT 1
                """
            ),
            {
                "operator_id": operator_id,
                "tenant_id": tenant_id or "",
            },
        )
        row = result.mappings().first()
        if not row:
            return None

        provider_key = normalize_channel(str(row.get("email_provider") or "gmail"))
        if provider_key != normalized_channel:
            # Credentials exist, but not for the requested normalized channel.
            return None

        return OperatorCredentialRecord(
            operator_id=str(row["operator_id"]),
            channel=normalized_channel,
            tenant_id=str(row["tenant_id"]) if row.get("tenant_id") else None,
            watched_address=str(row.get("watched_email") or ""),
            credential_blob={
                "refresh_token": str(row.get("refresh_token") or ""),
            },
            metadata={
                "provider_alias": str(row.get("email_provider") or normalized_channel),
            },
        )
