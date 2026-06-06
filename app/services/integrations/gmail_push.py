from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session_safety import safe_rollback as _safe_rollback
from app.services.integrations.gmail_inbox_poller import GMAIL_API_BASE, GmailTokenManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GmailPushNotification:
    watched_email: str
    history_id: str
    subscription: str = ""
    message_id: str = ""
    publish_time: str = ""


@dataclass(frozen=True)
class GmailWatchRegistrationResult:
    status: str
    operator_id: str
    watched_email: str
    history_id: str = ""
    expires_at: str = ""
    reason: str = ""


@dataclass(frozen=True)
class GmailPushDispatchResult:
    status: str
    operator_id: str = ""
    tenant_id: str = ""
    watched_email: str = ""
    history_id: str = ""
    previous_history_id: str = ""
    should_trigger: bool = False
    reason: str = ""


def gmail_push_topic() -> str:
    return (os.getenv("GMAIL_PUBSUB_TOPIC") or "").strip()


def gmail_push_webhook_token() -> str:
    return (os.getenv("GMAIL_PUSH_WEBHOOK_TOKEN") or "").strip()


def decode_gmail_push_pubsub_payload(payload: dict[str, Any]) -> GmailPushNotification:
    message = payload.get("message")
    if not isinstance(message, dict):
        raise ValueError("Missing Pub/Sub message envelope")

    raw_data = str(message.get("data") or "").strip()
    if not raw_data:
        raise ValueError("Missing Pub/Sub message data")

    padding = "=" * (-len(raw_data) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{raw_data}{padding}")
        inner = json.loads(decoded.decode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive parse guard
        raise ValueError("Invalid Pub/Sub Gmail payload") from exc

    watched_email = str(inner.get("emailAddress") or "").strip().lower()
    history_id = str(inner.get("historyId") or "").strip()
    if not watched_email or not history_id:
        raise ValueError("Gmail push payload missing emailAddress/historyId")

    return GmailPushNotification(
        watched_email=watched_email,
        history_id=history_id,
        subscription=str(payload.get("subscription") or "").strip(),
        message_id=str(message.get("messageId") or "").strip(),
        publish_time=str(message.get("publishTime") or "").strip(),
    )


def _history_id_as_int(value: str) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except Exception:
        return None


def should_trigger_push_sync(
    *,
    incoming_history_id: str,
    last_known_history_id: str,
) -> bool:
    incoming = _history_id_as_int(incoming_history_id)
    previous = _history_id_as_int(last_known_history_id)
    if incoming is None:
        return False
    if previous is None:
        return True
    return incoming > previous


async def ensure_gmail_push_schema(db: AsyncSession) -> None:
    try:
        await db.execute(
            text(
                """
                ALTER TABLE operator_gmail_creds
                    ADD COLUMN IF NOT EXISTS gmail_watch_history_id TEXT,
                    ADD COLUMN IF NOT EXISTS gmail_watch_expires_at TIMESTAMPTZ,
                    ADD COLUMN IF NOT EXISTS last_push_received_at TIMESTAMPTZ,
                    ADD COLUMN IF NOT EXISTS last_push_history_id TEXT,
                    ADD COLUMN IF NOT EXISTS last_push_error TEXT
                """
            )
        )
        await db.commit()
    except Exception:
        await _safe_rollback(db)
        logger.debug("[GmailPush] schema ensure failed", exc_info=True)


async def register_gmail_watch(
    db: AsyncSession,
    *,
    operator_id: str,
    tenant_id: str,
    watched_email: str,
    refresh_token: str,
    poll_label: str = "INBOX",
) -> GmailWatchRegistrationResult:
    await ensure_gmail_push_schema(db)
    topic_name = gmail_push_topic()
    watched = (watched_email or "").strip()
    if not topic_name:
        return GmailWatchRegistrationResult(
            status="skipped",
            operator_id=operator_id,
            watched_email=watched,
            reason="gmail_push_topic_missing",
        )
    if not watched or not refresh_token:
        return GmailWatchRegistrationResult(
            status="skipped",
            operator_id=operator_id,
            watched_email=watched,
            reason="gmail_watch_credentials_missing",
        )

    client_id = (os.getenv("GMAIL_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("GMAIL_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        return GmailWatchRegistrationResult(
            status="skipped",
            operator_id=operator_id,
            watched_email=watched,
            reason="gmail_oauth_client_missing",
        )

    token_manager = GmailTokenManager(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
    )

    expires_at_iso = ""
    history_id = ""
    try:
        token = await token_manager.get_access_token()
        headers = token_manager.auth_header(token)
        headers["Content-Type"] = "application/json"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{GMAIL_API_BASE}/users/me/watch",
                headers=headers,
                json={
                    "topicName": topic_name,
                    "labelIds": [poll_label or "INBOX"],
                },
            )
            resp.raise_for_status()
            payload = resp.json()

        history_id = str(payload.get("historyId") or "").strip()
        expiration_raw = str(payload.get("expiration") or "").strip()
        expires_at = None
        if expiration_raw.isdigit():
            expires_at = datetime.fromtimestamp(int(expiration_raw) / 1000.0, tz=timezone.utc)
            expires_at_iso = expires_at.isoformat()

        await db.execute(
            text(
                """
                UPDATE operator_gmail_creds
                SET gmail_watch_history_id = :history_id,
                    gmail_watch_expires_at = :expires_at,
                    last_push_error = NULL,
                    updated_at = NOW()
                WHERE operator_id = CAST(:operator_id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                """
            ),
            {
                "operator_id": operator_id,
                "tenant_id": tenant_id,
                "history_id": history_id or None,
                "expires_at": expires_at,
            },
        )
        await db.commit()
        logger.info(
            "[GmailPush] watch registered operator=%s watched_email=%s expires_at=%s",
            operator_id,
            watched,
            expires_at_iso or "unknown",
        )
        return GmailWatchRegistrationResult(
            status="ok",
            operator_id=operator_id,
            watched_email=watched,
            history_id=history_id,
            expires_at=expires_at_iso,
        )
    except Exception as exc:
        await _safe_rollback(db)
        try:
            await db.execute(
                text(
                    """
                    UPDATE operator_gmail_creds
                    SET last_push_error = :error,
                        updated_at = NOW()
                    WHERE operator_id = CAST(:operator_id AS uuid)
                    """
                ),
                {
                    "operator_id": operator_id,
                    "error": str(exc)[:500],
                },
            )
            await db.commit()
        except Exception:
            await _safe_rollback(db)
        logger.warning(
            "[GmailPush] watch registration failed operator=%s watched_email=%s error=%s",
            operator_id,
            watched,
            exc,
        )
        return GmailWatchRegistrationResult(
            status="error",
            operator_id=operator_id,
            watched_email=watched,
            history_id=history_id,
            expires_at=expires_at_iso,
            reason=str(exc),
        )


async def record_gmail_push_notification(
    db: AsyncSession,
    *,
    notification: GmailPushNotification,
) -> GmailPushDispatchResult:
    await ensure_gmail_push_schema(db)
    row = (
        await db.execute(
            text(
                """
                SELECT
                    operator_id,
                    tenant_id,
                    watched_email,
                    COALESCE(gmail_watch_history_id, last_push_history_id, '') AS last_known_history_id
                FROM operator_gmail_creds
                WHERE LOWER(watched_email) = LOWER(:watched_email)
                  AND COALESCE(email_provider, 'gmail') IN ('gmail', 'google')
                ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
                LIMIT 1
                """
            ),
            {"watched_email": notification.watched_email},
        )
    ).mappings().first()

    if not row:
        return GmailPushDispatchResult(
            status="ignored",
            watched_email=notification.watched_email,
            history_id=notification.history_id,
            reason="no_matching_operator",
        )

    last_known = str(row.get("last_known_history_id") or "")
    should_trigger = should_trigger_push_sync(
        incoming_history_id=notification.history_id,
        last_known_history_id=last_known,
    )
    await db.execute(
        text(
            """
            UPDATE operator_gmail_creds
            SET last_push_received_at = NOW(),
                last_push_history_id = :history_id,
                gmail_watch_history_id = CASE
                    WHEN :should_trigger THEN :history_id
                    ELSE COALESCE(gmail_watch_history_id, :history_id)
                END,
                last_push_error = NULL,
                updated_at = NOW()
            WHERE operator_id = CAST(:operator_id AS uuid)
            """
        ),
        {
            "operator_id": str(row["operator_id"]),
            "history_id": notification.history_id,
            "should_trigger": should_trigger,
        },
    )
    await db.commit()

    return GmailPushDispatchResult(
        status="ok",
        operator_id=str(row["operator_id"]),
        tenant_id=str(row["tenant_id"]),
        watched_email=str(row["watched_email"] or notification.watched_email),
        history_id=notification.history_id,
        previous_history_id=last_known,
        should_trigger=should_trigger,
        reason="duplicate_or_stale_history_id" if not should_trigger else "",
    )


def watch_needs_refresh(expires_at: datetime | None, *, renew_before: timedelta | None = None) -> bool:
    if expires_at is None:
        return True
    threshold = renew_before or timedelta(hours=24)
    return expires_at <= datetime.now(timezone.utc) + threshold
