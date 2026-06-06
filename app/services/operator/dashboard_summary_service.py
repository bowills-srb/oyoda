from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.messaging_brain.knowledge.dashboard_kb_service import (
    get_dashboard_kb_service,
)


logger = logging.getLogger(__name__)


def default_dashboard_summary() -> dict:
    return {
        "sessions": {
            "active": 0,
            "in_stay": 0,
            "arriving": 0,
            "total_30d": 0,
        },
        "pre_booking": {
            "pending": 0,
            "oldest_pending_age_minutes": 0,
            "replied_30d": 0,
            "total_30d": 0,
            "ai_sent_today": 0,
            "draft_signals": {
                "approved": 0,
                "edited": 0,
                "rejected": 0,
            },
        },
        "escalations": {
            "open": 0,
            "resolved_30d": 0,
        },
        "properties": 0,
        "kb_entries": 0,
        "kb_gaps": 0,
        "vendors": 0,
        "messages_30d": 0,
        "notifications_unread": 0,
        "inbox": {
            "connected": False,
            "email": None,
            "provider": None,
            "connected_at": None,
            "last_polled_at": None,
            "last_poll_success": None,
            "last_poll_summary": None,
            "last_poll_error": None,
            "last_messages_found": None,
            "last_new_pending_inquiries": None,
            "last_query_mode": None,
        },
        "degraded": True,
        "filtered": {"total": 0, "counts": {}, "window": "today"},
    }


class DashboardSummaryService:
    def __init__(self):
        self.knowledge_service = get_dashboard_kb_service()

    def _serialize_inbox(self, inbox_row: Optional[dict]) -> dict:
        return {
            "connected": bool(inbox_row and inbox_row["watched_email"]),
            "email": inbox_row["watched_email"] if inbox_row else None,
            "provider": inbox_row["email_provider"] if inbox_row else None,
            "connected_at": inbox_row["connected_at"].isoformat() if inbox_row and inbox_row["connected_at"] else None,
            "last_polled_at": inbox_row["last_polled_at"].isoformat() if inbox_row and inbox_row["last_polled_at"] else None,
            "last_poll_success": bool(inbox_row["last_poll_success"]) if inbox_row and inbox_row["last_poll_success"] is not None else None,
            "last_poll_summary": inbox_row["last_poll_summary"] if inbox_row else None,
            "last_poll_error": inbox_row["last_poll_error"] if inbox_row else None,
            "last_messages_found": int(inbox_row["last_messages_found"] or 0) if inbox_row and inbox_row["last_messages_found"] is not None else None,
            "last_new_pending_inquiries": int(inbox_row["last_new_pending_inquiries"] or 0) if inbox_row and inbox_row["last_new_pending_inquiries"] is not None else None,
            "last_query_mode": inbox_row["last_query_mode"] if inbox_row else None,
        }

    async def build_summary(
        self,
        session: AsyncSession,
        tenant_id: str,
        operator_id: str,
        *,
        property_meta: Optional[dict],
        notification_filter_sql: str,
        inbox_row: Optional[dict],
        visible_property_codes: Optional[list[str]] = None,
    ) -> dict:
        if visible_property_codes is None:
            cached = await self._load_cached_summary(session, tenant_id)
            if cached:
                return {
                    **cached,
                    "inbox": self._serialize_inbox(inbox_row),
                    "degraded": False,
                    "cache_source": "persisted",
                }

        summary = await self._compute_live_summary(
            session=session,
            tenant_id=tenant_id,
            operator_id=operator_id,
            property_meta=property_meta,
            notification_filter_sql=notification_filter_sql,
            inbox_row=inbox_row,
            visible_property_codes=visible_property_codes,
        )
        if visible_property_codes is None:
            await self._persist_summary(session, tenant_id, summary)
        return {**summary, "degraded": False, "cache_source": "live"}

    async def _table_exists(self, session: AsyncSession, table_name: str) -> bool:
        try:
            exists = await session.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                          AND table_name = :table_name
                    )
                    """
                ),
                {"table_name": table_name},
            )
            return bool(exists)
        except Exception:
            return False

    async def _load_cached_summary(self, session: AsyncSession, tenant_id: str) -> Optional[dict]:
        if not await self._table_exists(session, "operator_dashboard_read_models"):
            return None
        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT summary_json, refreshed_at
                        FROM operator_dashboard_read_models
                        WHERE tenant_id = CAST(:tid AS uuid)
                        LIMIT 1
                        """
                    ),
                    {"tid": tenant_id},
                )
            ).mappings().first()
            if not row or not row["summary_json"]:
                return None
            summary = row["summary_json"]
            if isinstance(summary, str):
                summary = json.loads(summary)
            if not isinstance(summary, dict):
                return None
            refreshed_at = row["refreshed_at"]
            summary["refreshed_at"] = refreshed_at.isoformat() if refreshed_at else None
            return summary
        except Exception as exc:
            logger.warning("[DashboardSummaryService] cached load failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return None

    async def _persist_summary(self, session: AsyncSession, tenant_id: str, summary: dict) -> None:
        if not await self._table_exists(session, "operator_dashboard_read_models"):
            return
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO operator_dashboard_read_models
                        (tenant_id, summary_json, refreshed_at)
                    VALUES
                        (CAST(:tid AS uuid), CAST(:summary_json AS jsonb), NOW())
                    ON CONFLICT (tenant_id) DO UPDATE SET
                        summary_json = EXCLUDED.summary_json,
                        refreshed_at = EXCLUDED.refreshed_at
                    """
                ),
                {"tid": tenant_id, "summary_json": json.dumps(summary)},
            )
            await session.commit()
        except Exception as exc:
            logger.warning("[DashboardSummaryService] persist skipped: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass

    async def _scalar_or(self, session: AsyncSession, default: Any, sql: str, params: dict):
        try:
            return (await session.execute(text(sql), params)).scalar() or default
        except Exception as exc:
            logger.warning("[DashboardSummaryService] scalar fallback: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return default

    async def _fetchone_or(self, session: AsyncSession, defaults: dict, sql: str, params: dict):
        try:
            row = (await session.execute(text(sql), params)).fetchone()
            if not row:
                return defaults
            data = {}
            for key, fallback in defaults.items():
                try:
                    data[key] = getattr(row, key)
                except Exception:
                    data[key] = fallback
            return data
        except Exception as exc:
            logger.warning("[DashboardSummaryService] row fallback: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return defaults

    async def _compute_live_summary(
        self,
        *,
        session: AsyncSession,
        tenant_id: str,
        operator_id: str,
        property_meta: Optional[dict],
        notification_filter_sql: str,
        inbox_row: Optional[dict],
        visible_property_codes: Optional[list[str]] = None,
    ) -> dict:
        sessions_scope = ""
        prebooking_scope = ""
        escalations_scope = ""
        property_scope = ""
        messages_scope = ""
        params: dict[str, Any] = {"tid": tenant_id, "oid": operator_id}
        if visible_property_codes is not None:
            params["visible_property_codes"] = visible_property_codes
            sessions_scope = " AND property_code = ANY(CAST(:visible_property_codes AS text[]))"
            prebooking_scope = " AND property_external_id = ANY(CAST(:visible_property_codes AS text[]))"
            escalations_scope = " AND s.property_code = ANY(CAST(:visible_property_codes AS text[]))"
            messages_scope = " AND s.property_code = ANY(CAST(:visible_property_codes AS text[]))"
            if property_meta:
                property_scope = f" AND {property_meta['code_expr']} = ANY(CAST(:visible_property_codes AS text[]))"

        sess_row = await self._fetchone_or(
            session,
            {"active": 0, "in_stay": 0, "arriving": 0, "total_30d": 0},
            f"""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'active') AS active,
                    COUNT(*) FILTER (WHERE status = 'active' AND phase = 'in_stay') AS in_stay,
                    COUNT(*) FILTER (WHERE status = 'active' AND phase = 'pre_arrival') AS arriving,
                    COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '30 days') AS total_30d
                FROM concierge_guest_sessions
                WHERE tenant_id = CAST(:tid AS uuid)
                {sessions_scope}
            """,
            params,
        )

        pb_row = await self._fetchone_or(
            session,
            {"pending": 0, "oldest_pending_age_minutes": 0, "replied_30d": 0, "total_30d": 0, "ai_sent_today": 0},
            f"""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'pending_review') AS pending,
                    EXTRACT(EPOCH FROM (NOW() - MIN(received_at) FILTER (WHERE status = 'pending_review'))) / 60 AS oldest_pending_age_minutes,
                    COUNT(*) FILTER (WHERE status = 'replied' AND received_at >= NOW() - INTERVAL '30 days') AS replied_30d,
                    COUNT(*) FILTER (WHERE received_at >= NOW() - INTERVAL '30 days') AS total_30d,
                    COUNT(*) FILTER (
                        WHERE status = 'replied'
                          AND replied_at >= date_trunc('day', NOW())
                          AND COALESCE(triggered_by, '') IN ('auto_fresh', 'auto_kb_retry')
                    ) AS ai_sent_today
                FROM pre_booking_inquiries
                WHERE company_id = CAST(:tid AS uuid)
                  AND archived_at IS NULL
                {prebooking_scope}
            """,
            params,
        )

        # Draft learning signals (approve/edit/reject) over the last 30 days.
        # Source: operator_draft_events, written by DraftLearningService when an
        # operator approves/edits/rejects an AI draft (see operator_prebooking.py
        # _record_learning_best_effort). Guarded by _table_exists because the
        # table is optional in older environments; absent table -> zeros, which the
        # frontend renders as an honest "accruing" state rather than a fake rate.
        # Scoped by company_id (== tenant_id here), matching the pb_row query.
        draft_signals = {"approved": 0, "edited": 0, "rejected": 0}
        if await self._table_exists(session, "operator_draft_events"):
            ds_row = await self._fetchone_or(
                session,
                {"approved": 0, "edited": 0, "rejected": 0},
                """
                    SELECT
                        COUNT(*) FILTER (WHERE event_type = 'approved_unchanged') AS approved,
                        COUNT(*) FILTER (WHERE event_type = 'edited') AS edited,
                        COUNT(*) FILTER (WHERE event_type = 'rejected') AS rejected
                    FROM operator_draft_events
                    WHERE company_id = CAST(:tid AS uuid)
                      AND created_at >= NOW() - INTERVAL '30 days'
                """,
                {"tid": tenant_id},
            )
            draft_signals = {
                "approved": int(ds_row["approved"] or 0),
                "edited": int(ds_row["edited"] or 0),
                "rejected": int(ds_row["rejected"] or 0),
            }

        esc_row = await self._fetchone_or(
            session,
            {"open": 0, "resolved_30d": 0},
            f"""
                SELECT
                    COUNT(*) FILTER (WHERE e.status IN ('pending','acknowledged')) AS open,
                    COUNT(*) FILTER (WHERE e.status = 'resolved' AND e.resolved_at >= NOW() - INTERVAL '30 days') AS resolved_30d
                FROM concierge_escalations e
                INNER JOIN concierge_guest_sessions s ON s.token = e.session_token
                WHERE s.tenant_id = CAST(:tid AS uuid)
                {escalations_scope}
            """,
            params,
        )

        prop_count = await self._scalar_or(
            session,
            0,
            (
                f"SELECT COUNT(*) FROM properties WHERE {property_meta['where_sql']}{property_scope}"
                if property_meta else
                "SELECT 0"
            ),
            params,
        )

        try:
            kb_entries = await self.knowledge_service.count_dashboard_entries(
                session=session,
                tenant_id=uuid.UUID(tenant_id),
            )
        except Exception as exc:
            logger.warning("[DashboardSummaryService] KB rows fallback: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            kb_entries = 0

        kb_gaps = await self._scalar_or(
            session,
            0,
            """
                SELECT COUNT(*) FROM concierge_knowledge_gaps
                WHERE tenant_id = CAST(:tid AS uuid) AND resolved = FALSE
            """,
            {"tid": tenant_id},
        )

        vendor_count = await self._scalar_or(
            session,
            0,
            "SELECT COUNT(*) FROM vendors WHERE tenant_id = CAST(:tid AS uuid) AND active = TRUE",
            {"tid": tenant_id},
        )

        has_messages = await self._table_exists(session, "concierge_messages")
        if has_messages:
            msg_row = await self._scalar_or(
                session,
                0,
                f"""
                    SELECT COUNT(*) FROM concierge_messages m
                    JOIN concierge_guest_sessions s ON s.session_id = m.session_id
                    WHERE s.tenant_id = CAST(:tid AS uuid)
                      AND m.created_at >= NOW() - INTERVAL '30 days'
                      AND m.direction = 'outbound'
                      {messages_scope}
                """,
                params,
            )
        else:
            msg_row = 0

        has_notifications = await self._table_exists(session, "operator_notifications")
        if has_notifications:
            notif_unread = await self._scalar_or(
                session,
                0,
                f"""
                    SELECT COUNT(*) FROM operator_notifications
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND read_at IS NULL
                      AND {notification_filter_sql}
                """,
                params,
            )
        else:
            notif_unread = 0

        # Filtered message counts — degraded to zeros on failure so a
        # message_normalizations query error doesn't fail the whole summary.
        filtered_block = {"total": 0, "counts": {}, "window": "today"}
        try:
            from app.services.operator.filtered_recovery_service import compute_filtered_counts
            filtered_block = await compute_filtered_counts(
                session,
                tenant_id,
                window="today",
                visible_property_codes=visible_property_codes,
            )
        except Exception as exc:
            logger.warning("[DashboardSummaryService] filtered counts fallback: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass

        return {
            "sessions": {
                "active": int(sess_row["active"] or 0),
                "in_stay": int(sess_row["in_stay"] or 0),
                "arriving": int(sess_row["arriving"] or 0),
                "total_30d": int(sess_row["total_30d"] or 0),
            },
            "pre_booking": {
                "pending": int(pb_row["pending"] or 0),
                "oldest_pending_age_minutes": int(pb_row["oldest_pending_age_minutes"] or 0),
                "replied_30d": int(pb_row["replied_30d"] or 0),
                "total_30d": int(pb_row["total_30d"] or 0),
                "ai_sent_today": int(pb_row["ai_sent_today"] or 0),
                "draft_signals": draft_signals,
            },
            "escalations": {
                "open": int(esc_row["open"] or 0),
                "resolved_30d": int(esc_row["resolved_30d"] or 0),
            },
            "properties": int(prop_count),
            "kb_entries": int(kb_entries),
            "kb_gaps": int(kb_gaps),
            "vendors": int(vendor_count),
            "messages_30d": int(msg_row),
            "notifications_unread": int(notif_unread),
            "inbox": self._serialize_inbox(inbox_row),
            "filtered": filtered_block,
        }


_dashboard_summary_service: Optional[DashboardSummaryService] = None


def get_dashboard_summary_service() -> DashboardSummaryService:
    global _dashboard_summary_service
    if _dashboard_summary_service is None:
        _dashboard_summary_service = DashboardSummaryService()
    return _dashboard_summary_service
