from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)


DEFAULT_RETENTION_POLICY: dict[str, Any] = {
    "active_search_window_days": 30,
    "post_stay_follow_up_days": 21,
    "raw_guest_content_retention_days": 90,
    "pre_booking_record_retention_days": 120,
    "guest_session_shell_retention_days": 730,
    "structured_signal_retention_days": 365,
    "auto_cleanup_enabled": True,
    "preserve_guest_identity": True,
}


def merge_retention_policy(extra: dict[str, Any] | None) -> dict[str, Any]:
    extra = extra or {}
    incoming = extra.get("retention_policy") if isinstance(extra, dict) else {}
    incoming = incoming if isinstance(incoming, dict) else {}

    policy = dict(DEFAULT_RETENTION_POLICY)
    policy["active_search_window_days"] = _clamp_int(
        incoming.get("active_search_window_days"),
        DEFAULT_RETENTION_POLICY["active_search_window_days"],
        minimum=7,
        maximum=90,
    )
    policy["post_stay_follow_up_days"] = _clamp_int(
        incoming.get("post_stay_follow_up_days"),
        DEFAULT_RETENTION_POLICY["post_stay_follow_up_days"],
        minimum=3,
        maximum=60,
    )
    policy["raw_guest_content_retention_days"] = _clamp_int(
        incoming.get("raw_guest_content_retention_days"),
        DEFAULT_RETENTION_POLICY["raw_guest_content_retention_days"],
        minimum=30,
        maximum=180,
    )
    policy["pre_booking_record_retention_days"] = _clamp_int(
        incoming.get("pre_booking_record_retention_days"),
        DEFAULT_RETENTION_POLICY["pre_booking_record_retention_days"],
        minimum=45,
        maximum=365,
    )
    policy["guest_session_shell_retention_days"] = _clamp_int(
        incoming.get("guest_session_shell_retention_days"),
        DEFAULT_RETENTION_POLICY["guest_session_shell_retention_days"],
        minimum=90,
        maximum=730,
    )
    policy["structured_signal_retention_days"] = _clamp_int(
        incoming.get("structured_signal_retention_days"),
        DEFAULT_RETENTION_POLICY["structured_signal_retention_days"],
        minimum=90,
        maximum=730,
    )
    policy["auto_cleanup_enabled"] = bool(
        incoming.get("auto_cleanup_enabled", DEFAULT_RETENTION_POLICY["auto_cleanup_enabled"])
    )
    policy["preserve_guest_identity"] = bool(
        incoming.get("preserve_guest_identity", DEFAULT_RETENTION_POLICY["preserve_guest_identity"])
    )

    if policy["pre_booking_record_retention_days"] < policy["raw_guest_content_retention_days"]:
        policy["pre_booking_record_retention_days"] = policy["raw_guest_content_retention_days"]
    if policy["guest_session_shell_retention_days"] < policy["raw_guest_content_retention_days"]:
        policy["guest_session_shell_retention_days"] = policy["raw_guest_content_retention_days"]
    if policy["structured_signal_retention_days"] < policy["raw_guest_content_retention_days"]:
        policy["structured_signal_retention_days"] = policy["raw_guest_content_retention_days"]

    return policy


def _clamp_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except Exception:
        return default


class MessageRetentionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._table_columns_cache: dict[str, set[str]] = {}

    async def run_all_tenants(self) -> dict[str, Any]:
        tenant_ids = await self._tenant_ids()
        summary = {
            "tenants_considered": len(tenant_ids),
            "tenants_processed": 0,
            "tenants_skipped": 0,
            "message_normalizations_scrubbed": 0,
            "message_normalizations_deleted": 0,
            "messages_deleted": 0,
            "pre_booking_scrubbed": 0,
            "pre_booking_deleted": 0,
            "guest_sessions_scrubbed": 0,
            "guest_session_shells_deleted": 0,
        }
        for tenant_id in tenant_ids:
            result = await self.run_for_tenant(tenant_id)
            if result.get("skipped"):
                summary["tenants_skipped"] += 1
                continue
            summary["tenants_processed"] += 1
            for key in (
                "message_normalizations_scrubbed",
                "message_normalizations_deleted",
                "messages_deleted",
                "pre_booking_scrubbed",
                "pre_booking_deleted",
                "guest_sessions_scrubbed",
                "guest_session_shells_deleted",
            ):
                summary[key] += int(result.get(key) or 0)
        return summary

    async def run_for_tenant(self, tenant_id: str) -> dict[str, Any]:
        policy = await self._load_policy(tenant_id)
        if not policy["auto_cleanup_enabled"]:
            return {"tenant_id": tenant_id, "skipped": True, "reason": "disabled", "policy": policy}

        result = {"tenant_id": tenant_id, "policy": policy}
        result["message_normalizations_scrubbed"] = await self._scrub_message_normalizations(
            tenant_id,
            policy["raw_guest_content_retention_days"],
            preserve_guest_identity=policy["preserve_guest_identity"],
        )
        result["messages_deleted"] = await self._delete_messages(
            tenant_id, policy["raw_guest_content_retention_days"]
        )
        result["pre_booking_scrubbed"] = await self._scrub_pre_booking_inquiries(
            tenant_id,
            policy["raw_guest_content_retention_days"],
            preserve_guest_identity=policy["preserve_guest_identity"],
        )
        result["pre_booking_deleted"] = await self._delete_pre_booking_inquiries(
            tenant_id, policy["pre_booking_record_retention_days"]
        )
        result["guest_sessions_scrubbed"] = await self._scrub_guest_sessions(
            tenant_id,
            policy["raw_guest_content_retention_days"],
            preserve_guest_identity=policy["preserve_guest_identity"],
        )
        result["guest_session_shells_deleted"] = await self._delete_guest_session_shells(
            tenant_id, policy["guest_session_shell_retention_days"]
        )
        result["message_normalizations_deleted"] = await self._delete_message_normalizations(
            tenant_id, policy["structured_signal_retention_days"]
        )
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        return result

    async def _tenant_ids(self) -> list[str]:
        rows = (
            await self.db.execute(
                text(
                    """
                    SELECT DISTINCT tenant_id::text AS tenant_id
                    FROM (
                        SELECT tenant_id FROM operator_settings
                        UNION
                        SELECT tenant_id FROM message_normalizations
                        UNION
                        SELECT tenant_id FROM concierge_guest_sessions
                        UNION
                        SELECT company_id AS tenant_id FROM pre_booking_inquiries
                    ) ids
                    WHERE tenant_id IS NOT NULL
                    """
                )
            )
        ).mappings().all()
        return [str(row["tenant_id"]) for row in rows if row.get("tenant_id")]

    async def _load_policy(self, tenant_id: str) -> dict[str, Any]:
        row = (
            await self.db.execute(
                text(
                    """
                    SELECT extra
                    FROM operator_settings
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id},
            )
        ).mappings().first()
        extra = row.get("extra") if row else {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        extra = extra if isinstance(extra, dict) else {}
        return merge_retention_policy(extra)

    async def _scrub_message_normalizations(
        self,
        tenant_id: str,
        retention_days: int,
        *,
        preserve_guest_identity: bool,
    ) -> int:
        if not await self._table_exists("message_normalizations"):
            return 0
        columns = await self._columns("message_normalizations")
        if "sent_at" not in columns:
            return 0
        scrub_cols = [
            col for col in (
                *(() if preserve_guest_identity else ("sender_display_name", "sender_address")),
                "raw_subject",
                "latest_guest_turn",
                "prior_thread_context",
                "full_message_text",
            )
            if col in columns
        ]
        return await self._nullify_old_fields(
            table_name="message_normalizations",
            tenant_column="tenant_id",
            cutoff_column="sent_at",
            retention_days=retention_days,
            scrub_columns=scrub_cols,
            tenant_id=tenant_id,
        )

    async def _delete_message_normalizations(self, tenant_id: str, retention_days: int) -> int:
        if not await self._table_exists("message_normalizations"):
            return 0
        columns = await self._columns("message_normalizations")
        if "sent_at" not in columns:
            return 0
        row = await self.db.execute(
            text(
                """
                DELETE FROM message_normalizations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND sent_at < NOW() - (:days || ' days')::interval
                """
            ),
            {"tenant_id": tenant_id, "days": str(retention_days)},
        )
        return int(getattr(row, "rowcount", 0) or 0)

    async def _delete_messages(self, tenant_id: str, retention_days: int) -> int:
        if not await self._table_exists("messages") or not await self._table_exists("conversations"):
            return 0
        convo_columns = await self._columns("conversations")
        if "tenant_id" not in convo_columns:
            return 0
        message_columns = await self._columns("messages")
        if "sent_at" not in message_columns or "conversation_id" not in message_columns:
            return 0
        row = await self.db.execute(
            text(
                """
                DELETE FROM messages m
                USING conversations c
                WHERE m.conversation_id = c.conversation_id
                  AND c.tenant_id = CAST(:tenant_id AS uuid)
                  AND m.sent_at < NOW() - (:days || ' days')::interval
                """
            ),
            {"tenant_id": tenant_id, "days": str(retention_days)},
        )
        return int(getattr(row, "rowcount", 0) or 0)

    async def _scrub_pre_booking_inquiries(
        self,
        tenant_id: str,
        retention_days: int,
        *,
        preserve_guest_identity: bool,
    ) -> int:
        if not await self._table_exists("pre_booking_inquiries"):
            return 0
        columns = await self._columns("pre_booking_inquiries")
        if "received_at" not in columns:
            return 0
        scrub_cols = [
            col for col in (
                "message_text",
                "draft_text",
                *(() if preserve_guest_identity else ("guest_name", "guest_email")),
            )
            if col in columns
        ]
        return await self._nullify_old_fields(
            table_name="pre_booking_inquiries",
            tenant_column="company_id",
            cutoff_column="received_at",
            retention_days=retention_days,
            scrub_columns=scrub_cols,
            tenant_id=tenant_id,
        )

    async def _delete_pre_booking_inquiries(self, tenant_id: str, retention_days: int) -> int:
        if not await self._table_exists("pre_booking_inquiries"):
            return 0
        columns = await self._columns("pre_booking_inquiries")
        if "received_at" not in columns:
            return 0
        status_filter = ""
        if "status" in columns:
            status_filter = " AND COALESCE(status, '') NOT IN ('pending_review', 'pending_send')"
        row = await self.db.execute(
            text(
                f"""
                DELETE FROM pre_booking_inquiries
                WHERE company_id = CAST(:tenant_id AS uuid)
                  AND received_at < NOW() - (:days || ' days')::interval
                  {status_filter}
                """
            ),
            {"tenant_id": tenant_id, "days": str(retention_days)},
        )
        return int(getattr(row, "rowcount", 0) or 0)

    async def _scrub_guest_sessions(
        self,
        tenant_id: str,
        retention_days: int,
        *,
        preserve_guest_identity: bool,
    ) -> int:
        if not await self._table_exists("concierge_guest_sessions"):
            return 0
        columns = await self._columns("concierge_guest_sessions")
        if "check_out" not in columns:
            return 0
        scrub_cols = [
            col for col in (
                *(
                    ()
                    if preserve_guest_identity
                    else (
                        "guest_name",
                        "guest_email",
                        "guest_phone",
                        "guest_phone_e164",
                        "guest_first_name",
                        "guest_last_name",
                    )
                ),
                "thread_context",
                "latest_message_preview",
                "latest_guest_message",
                "latest_operator_message",
                "session_summary",
                "notes",
                "raw_payload",
            )
            if col in columns
        ]
        set_pairs = [f"{col} = NULL" for col in scrub_cols]
        if "status" in columns:
            set_pairs.append("status = 'archived'")
        if "updated_at" in columns:
            set_pairs.append("updated_at = NOW()")
        if not set_pairs:
            return 0
        any_present = " OR ".join(f"{col} IS NOT NULL" for col in scrub_cols) or "FALSE"
        row = await self.db.execute(
            text(
                f"""
                UPDATE concierge_guest_sessions
                SET {', '.join(set_pairs)}
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND check_out < CURRENT_DATE - CAST(:days AS integer)
                  AND ({any_present})
                """
            ),
            {"tenant_id": tenant_id, "days": retention_days},
        )
        return int(getattr(row, "rowcount", 0) or 0)

    async def _delete_guest_session_shells(self, tenant_id: str, retention_days: int) -> int:
        if not await self._table_exists("concierge_guest_sessions"):
            return 0
        columns = await self._columns("concierge_guest_sessions")
        if "check_out" not in columns:
            return 0
        status_filter = ""
        if "status" in columns:
            status_filter = " AND COALESCE(status, '') IN ('closed', 'expired', 'archived')"
        row = await self.db.execute(
            text(
                f"""
                DELETE FROM concierge_guest_sessions
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND check_out < CURRENT_DATE - CAST(:days AS integer)
                  {status_filter}
                """
            ),
            {"tenant_id": tenant_id, "days": retention_days},
        )
        return int(getattr(row, "rowcount", 0) or 0)

    async def _nullify_old_fields(
        self,
        *,
        table_name: str,
        tenant_column: str,
        cutoff_column: str,
        retention_days: int,
        scrub_columns: list[str],
        tenant_id: str,
    ) -> int:
        if not scrub_columns:
            return 0
        set_pairs = [f"{col} = NULL" for col in scrub_columns]
        columns = await self._columns(table_name)
        if "updated_at" in columns:
            set_pairs.append("updated_at = NOW()")
        any_present = " OR ".join(f"{col} IS NOT NULL" for col in scrub_columns)
        row = await self.db.execute(
            text(
                f"""
                UPDATE {table_name}
                SET {', '.join(set_pairs)}
                WHERE {tenant_column} = CAST(:tenant_id AS uuid)
                  AND {cutoff_column} < NOW() - (:days || ' days')::interval
                  AND ({any_present})
                """
            ),
            {"tenant_id": tenant_id, "days": str(retention_days)},
        )
        return int(getattr(row, "rowcount", 0) or 0)

    async def _table_exists(self, table_name: str) -> bool:
        return bool(await self._columns(table_name))

    async def _columns(self, table_name: str) -> set[str]:
        cached = self._table_columns_cache.get(table_name)
        if cached is not None:
            return cached
        try:
            rows = (
                await self.db.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = :table_name
                        """
                    ),
                    {"table_name": table_name},
                )
            ).fetchall()
            cols = {str(row[0]) for row in rows}
        except Exception:
            cols = set()
        self._table_columns_cache[table_name] = cols
        return cols
