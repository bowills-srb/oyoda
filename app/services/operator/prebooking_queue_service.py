from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)


def _safe_json_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return value if isinstance(value, list) else []


class PrebookingQueueService:
    async def sync_draft(
        self,
        session: AsyncSession,
        tenant_id: str,
        draft_id: str,
    ) -> bool:
        if not draft_id:
            return False
        try:
            rows = await self._compute_live_rows(
                session=session,
                tenant_id=tenant_id,
                status="all",
                limit=1,
                property_external_id="",
                unbound_only=False,
                draft_id=draft_id,
            )
            if not rows:
                return False
            await self._persist_rows(session, tenant_id, rows)
            return True
        except Exception as exc:
            logger.warning("[PrebookingQueueService] sync_draft failed for %s: %s", draft_id, exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return False

    async def fetch_queue_rows(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        status: str = "all",
        limit: int = 50,
        property_external_id: str = "",
        unbound_only: bool = False,
        assignee_id: str = "",
        team_key: str = "",
        portfolio_key: str = "",
        assigned_to_me: bool = False,
    ) -> list[dict]:
        try:
            rows = await self._compute_live_rows(
                session=session,
                tenant_id=tenant_id,
                status=status,
                limit=limit,
                property_external_id=property_external_id,
                unbound_only=unbound_only,
            )
            await self._persist_rows(session, tenant_id, rows)
            rows = self._filter_rows(
                rows,
                assignee_id=assignee_id,
                team_key=team_key,
                portfolio_key=portfolio_key,
                assigned_to_me=assigned_to_me,
            )
            return rows[:limit] if limit else rows
        except Exception as exc:
            logger.warning("[PrebookingQueueService] live queue fetch failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return await self._load_cached_rows(
                session=session,
                tenant_id=tenant_id,
                status=status,
                limit=limit,
                property_external_id=property_external_id,
                unbound_only=unbound_only,
                assignee_id=assignee_id,
                team_key=team_key,
                portfolio_key=portfolio_key,
                assigned_to_me=assigned_to_me,
            )

    async def count_unbound_rows(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        status: str = "pending_review",
    ) -> int:
        status_clause = "" if status in ("", "all") else "AND pbi.status = :status"
        try:
            count = await session.scalar(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM pre_booking_inquiries pbi
                    WHERE pbi.company_id = CAST(:tid AS uuid)
                      AND pbi.archived_at IS NULL
                      {status_clause}
                      AND (pbi.property_external_id IS NULL OR pbi.property_external_id = '')
                    """
                ),
                {"tid": tenant_id, "status": status},
            )
            return int(count or 0)
        except Exception as exc:
            logger.warning("[PrebookingQueueService] unbound count failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return 0

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

    async def _column_names(self, session: AsyncSession, table_name: str) -> set[str]:
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = :table_name
                        """
                    ),
                    {"table_name": table_name},
                )
            ).fetchall()
            return {str(row[0]) for row in rows}
        except Exception:
            return set()

    async def _property_query_meta(self, session: AsyncSession, alias: str = "") -> Optional[dict]:
        columns = await self._column_names(session, "properties")
        if not columns:
            return None

        prefix = f"{alias}." if alias else ""
        tenant_col = "tenant_id" if "tenant_id" in columns else ("company_id" if "company_id" in columns else None)
        code_candidates = [
            col for col in ("property_code", "external_id", "property_external_id", "code")
            if col in columns
        ]
        name_candidates = [
            col for col in ("property_name", "name", "address_street", "address_line1", "property_code", "external_id")
            if col in columns
        ]

        predicates = []
        if tenant_col:
            predicates.append(f"{prefix}{tenant_col} = CAST(:tid AS uuid)")
        if "deleted_at" in columns:
            predicates.append(f"{prefix}deleted_at IS NULL")
        if "is_deleted" in columns:
            predicates.append(f"COALESCE({prefix}is_deleted, FALSE) = FALSE")

        return {
            "name_expr": (
                "COALESCE(" + ", ".join(f"{prefix}{col}" for col in name_candidates) + ", 'Unknown property')"
                if name_candidates else
                "'Unknown property'"
            ),
            "join_code_exprs": [f"{prefix}{col}" for col in code_candidates],
            "where_sql": " AND ".join(predicates) if predicates else "TRUE",
        }

    async def _compute_live_rows(
        self,
        *,
        session: AsyncSession,
        tenant_id: str,
        status: str,
        limit: int,
        property_external_id: str,
        unbound_only: bool,
        draft_id: str = "",
    ) -> list[dict]:
        status_clause = "" if status in ("", "all") else "AND pbi.status = :status"
        draft_clause = "" if not draft_id else "AND pbi.draft_id = :draft_id"
        property_meta = await self._property_query_meta(session, "p")
        live_binding_code_sql = "COALESCE(NULLIF(pbi.property_external_id, ''), NULLIF(mn.selected_property_code, ''))"
        fallback_binding_code_sql = "NULLIF(pbi.property_external_id, '')"
        if unbound_only:
            property_clause = f"AND ({live_binding_code_sql} IS NULL OR {live_binding_code_sql} = '')"
        else:
            property_clause = "" if not property_external_id else f"AND {live_binding_code_sql} = :prop"
        live_property_join = ""
        live_property_name_select = "NULL::text AS property_name"
        fallback_property_join = ""
        fallback_property_name_select = "NULL::text AS property_name"
        if property_meta and property_meta["join_code_exprs"]:
            live_join_match = " OR ".join(f"{expr} = {live_binding_code_sql}" for expr in property_meta["join_code_exprs"])
            fallback_join_match = " OR ".join(f"{expr} = {fallback_binding_code_sql}" for expr in property_meta["join_code_exprs"])
            live_property_join = f"""
            LEFT JOIN properties p
                ON ({live_join_match})
               AND {property_meta["where_sql"]}
            """
            fallback_property_join = f"""
            LEFT JOIN properties p
                ON ({fallback_join_match})
               AND {property_meta["where_sql"]}
            """
            live_property_name_select = f"{property_meta['name_expr']} AS property_name"
            fallback_property_name_select = f"{property_meta['name_expr']} AS property_name"

        params = {
            "tid": tenant_id,
            "status": status,
            "prop": property_external_id,
            "draft_id": draft_id,
            "limit": limit,
        }

        primary_sql = text(f"""
            SELECT
                pbi.draft_id,
                CAST(pbi.guest_thread_id AS text) AS guest_thread_id,
                pbi.thread_id,
                pbi.message_id,
                pbi.platform,
                pbi.guest_name,
                pbi.guest_email,
                pbi.message_text,
                pbi.draft_text,
                pbi.intent,
                pbi.confidence,
                pbi.intent_confidence,
                pbi.draft_confidence,
                CAST(pbi.confidence_source AS text) AS confidence_source,
                CAST(pbi.review_verdict AS text) AS review_verdict,
                CAST(pbi.autonomy_decision AS text) AS autonomy_decision,
                pbi.status,
                {live_binding_code_sql} AS property_external_id,
                pbi.requested_check_in,
                pbi.requested_check_out,
                pbi.requested_guests,
                pbi.policy_flags,
                pbi.policy_warnings,
                COALESCE(to_jsonb(pbi.blocked_by_gap_topics), '[]'::jsonb) AS blocked_by_gap_topics,
                pbi.triggered_by,
                pbi.received_at,
                pbi.replied_at,
                pbi.final_reply,
                pbi.gmail_message_id,
                pbi.gmail_thread_id,
                pbi.parser_source,
                pbi.extracted_asks,
                pbi.platform_listing_id,
                pbi.platform_unit_id,
                mn.source_provider,
                mn.latest_guest_turn,
                mn.prior_thread_context,
                mn.structured_asks AS normalized_asks,
                mn.prior_operator_commitments,
                mn.property_binding_candidates,
                mn.selected_property_code,
                mn.selected_property_match_type,
                mn.route_outcome,
                mn.draft_source AS normalization_draft_source,
                mn.fallback_reason,
                mn.latest_turn_confidence,
                mn.latest_turn_extracted,
                {live_property_name_select}
            FROM pre_booking_inquiries pbi
            LEFT JOIN message_normalizations mn
                ON mn.tenant_id = CAST(:tid AS uuid)
               AND mn.source_channel = 'email'
               AND mn.source_message_id = pbi.gmail_message_id
            {live_property_join}
            WHERE pbi.company_id = CAST(:tid AS uuid)
              AND pbi.archived_at IS NULL
            {status_clause}
            {property_clause}
            {draft_clause}
            ORDER BY pbi.received_at DESC
            LIMIT :limit
        """)

        fallback_sql = text(f"""
            SELECT
                pbi.draft_id,
                CAST(pbi.guest_thread_id AS text) AS guest_thread_id,
                pbi.thread_id,
                pbi.message_id,
                pbi.platform,
                pbi.guest_name,
                NULL::text AS guest_email,
                pbi.message_text,
                pbi.draft_text,
                pbi.intent,
                pbi.confidence,
                NULL::numeric AS intent_confidence,
                NULL::numeric AS draft_confidence,
                NULL::text AS confidence_source,
                NULL::text AS review_verdict,
                CAST(pbi.autonomy_decision AS text) AS autonomy_decision,
                pbi.status,
                {fallback_binding_code_sql} AS property_external_id,
                pbi.requested_check_in,
                pbi.requested_check_out,
                pbi.requested_guests,
                pbi.policy_flags,
                pbi.policy_warnings,
                '[]'::jsonb AS blocked_by_gap_topics,
                NULL::text AS triggered_by,
                pbi.received_at,
                pbi.replied_at,
                pbi.final_reply,
                NULL::text AS gmail_message_id,
                NULL::text AS gmail_thread_id,
                NULL::text AS parser_source,
                '[]'::jsonb AS extracted_asks,
                NULL::text AS platform_listing_id,
                NULL::text AS platform_unit_id,
                NULL::text AS source_provider,
                NULL::text AS latest_guest_turn,
                NULL::text AS prior_thread_context,
                '[]'::jsonb AS normalized_asks,
                '[]'::jsonb AS prior_operator_commitments,
                '[]'::jsonb AS property_binding_candidates,
                NULL::text AS selected_property_code,
                NULL::text AS selected_property_match_type,
                NULL::text AS route_outcome,
                NULL::text AS normalization_draft_source,
                NULL::text AS fallback_reason,
                NULL::float AS latest_turn_confidence,
                NULL::boolean AS latest_turn_extracted,
                {fallback_property_name_select}
            FROM pre_booking_inquiries pbi
            {fallback_property_join}
            WHERE pbi.company_id = CAST(:tid AS uuid)
              AND pbi.archived_at IS NULL
            {status_clause}
            {property_clause}
            {draft_clause}
            ORDER BY pbi.received_at DESC
            LIMIT :limit
        """)

        try:
            rows = (await session.execute(primary_sql, params)).mappings().all()
        except Exception:
            await session.rollback()
            rows = (await session.execute(fallback_sql, params)).mappings().all()
        live_rows = [dict(row) for row in rows]
        assignment_map = await self._load_assignment_map(session, tenant_id)
        for row in live_rows:
            assignment = assignment_map.get(str(row.get("draft_id") or ""), {})
            row["assigned_operator_id"] = assignment.get("assigned_operator_id") or ""
            row["assigned_team_key"] = assignment.get("assigned_team_key") or ""
            row["portfolio_key"] = assignment.get("portfolio_key") or ""
            row["assignment_status"] = assignment.get("assignment_status") or "unassigned"
        return live_rows

    async def _load_assignment_map(self, session: AsyncSession, tenant_id: str) -> dict[str, dict]:
        if not await self._table_exists(session, "operator_prebooking_queue_read_models"):
            return {}
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT
                            draft_id,
                            assigned_operator_id,
                            assigned_team_key,
                            portfolio_key,
                            assignment_status
                        FROM operator_prebooking_queue_read_models
                        WHERE tenant_id = CAST(:tid AS uuid)
                        """
                    ),
                    {"tid": tenant_id},
                )
            ).mappings().all()
            return {
                str(row["draft_id"]): {
                    "assigned_operator_id": str(row["assigned_operator_id"]) if row["assigned_operator_id"] else "",
                    "assigned_team_key": row["assigned_team_key"] or "",
                    "portfolio_key": row["portfolio_key"] or "",
                    "assignment_status": row["assignment_status"] or "unassigned",
                }
                for row in rows
            }
        except Exception as exc:
            logger.warning("[PrebookingQueueService] assignment load failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return {}

    async def _persist_rows(self, session: AsyncSession, tenant_id: str, rows: list[dict]) -> None:
        if not rows or not await self._table_exists(session, "operator_prebooking_queue_read_models"):
            return
        try:
            for row in rows:
                asks = _safe_json_list(row.get("extracted_asks")) or _safe_json_list(row.get("normalized_asks"))
                await session.execute(
                    text(
                        """
                        INSERT INTO operator_prebooking_queue_read_models (
                            tenant_id, guest_thread_id, draft_id, thread_id, source_message_id, platform,
                            source_provider, guest_name, guest_email, message_text,
                            latest_guest_turn, prior_thread_context, draft_text, final_reply,
                            intent, asks_json, policy_flags, policy_warnings, blocked_by_gap_topics, triggered_by,
                            property_external_id, property_name, property_binding_candidates,
                            selected_property_code, property_match_type, route_outcome,
                            draft_source, autonomy_decision, fallback_reason, prior_operator_commitments,
                            confidence, intent_confidence, draft_confidence,
                            confidence_source, review_verdict,
                            latest_turn_confidence, latest_turn_extracted,
                            queue_status, review_status, assigned_operator_id,
                            assigned_team_key, portfolio_key, received_at, replied_at,
                            refreshed_at
                        )
                        VALUES (
                            CAST(:tenant_id AS uuid), CAST(:guest_thread_id AS uuid), :draft_id, :thread_id, :source_message_id, :platform,
                            :source_provider, :guest_name, :guest_email, :message_text,
                            :latest_guest_turn, :prior_thread_context, :draft_text, :final_reply,
                            :intent, CAST(:asks_json AS jsonb), CAST(:policy_flags AS jsonb), CAST(:policy_warnings AS jsonb), CAST(:blocked_by_gap_topics AS jsonb), :triggered_by,
                            :property_external_id, :property_name, CAST(:property_binding_candidates AS jsonb),
                            :selected_property_code, :property_match_type, :route_outcome,
                            :draft_source, :autonomy_decision, :fallback_reason, CAST(:prior_operator_commitments AS jsonb),
                            :confidence, :intent_confidence, :draft_confidence,
                            CAST(NULLIF(:confidence_source, '') AS confidence_source),
                            CAST(NULLIF(:review_verdict, '') AS review_verdict),
                            :latest_turn_confidence, :latest_turn_extracted,
                            :queue_status, :review_status, NULL, NULL, NULL, :received_at, :replied_at,
                            NOW()
                        )
                        ON CONFLICT (tenant_id, draft_id) DO UPDATE SET
                            guest_thread_id = COALESCE(EXCLUDED.guest_thread_id, operator_prebooking_queue_read_models.guest_thread_id),
                            thread_id = EXCLUDED.thread_id,
                            source_message_id = EXCLUDED.source_message_id,
                            platform = EXCLUDED.platform,
                            source_provider = EXCLUDED.source_provider,
                            guest_name = EXCLUDED.guest_name,
                            guest_email = EXCLUDED.guest_email,
                            message_text = EXCLUDED.message_text,
                            latest_guest_turn = EXCLUDED.latest_guest_turn,
                            prior_thread_context = EXCLUDED.prior_thread_context,
                            draft_text = EXCLUDED.draft_text,
                            final_reply = EXCLUDED.final_reply,
                            intent = EXCLUDED.intent,
                            asks_json = EXCLUDED.asks_json,
                            policy_flags = EXCLUDED.policy_flags,
                            policy_warnings = EXCLUDED.policy_warnings,
                            blocked_by_gap_topics = EXCLUDED.blocked_by_gap_topics,
                            triggered_by = EXCLUDED.triggered_by,
                            property_external_id = EXCLUDED.property_external_id,
                            property_name = EXCLUDED.property_name,
                            property_binding_candidates = EXCLUDED.property_binding_candidates,
                            selected_property_code = EXCLUDED.selected_property_code,
                            property_match_type = EXCLUDED.property_match_type,
                            route_outcome = EXCLUDED.route_outcome,
                            draft_source = EXCLUDED.draft_source,
                            autonomy_decision = EXCLUDED.autonomy_decision,
                            fallback_reason = EXCLUDED.fallback_reason,
                            prior_operator_commitments = EXCLUDED.prior_operator_commitments,
                            confidence = EXCLUDED.confidence,
                            intent_confidence = EXCLUDED.intent_confidence,
                            draft_confidence = EXCLUDED.draft_confidence,
                            confidence_source = EXCLUDED.confidence_source,
                            review_verdict = EXCLUDED.review_verdict,
                            latest_turn_confidence = EXCLUDED.latest_turn_confidence,
                            latest_turn_extracted = EXCLUDED.latest_turn_extracted,
                            queue_status = EXCLUDED.queue_status,
                            review_status = EXCLUDED.review_status,
                            received_at = EXCLUDED.received_at,
                            replied_at = EXCLUDED.replied_at,
                            refreshed_at = EXCLUDED.refreshed_at
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "guest_thread_id": row.get("guest_thread_id") or None,
                        "draft_id": row.get("draft_id"),
                        "thread_id": row.get("thread_id"),
                        "source_message_id": row.get("gmail_message_id") or row.get("message_id") or "",
                        "platform": row.get("platform") or "email",
                        "source_provider": row.get("source_provider") or "",
                        "guest_name": row.get("guest_name") or "Guest",
                        "guest_email": row.get("guest_email") or "",
                        "message_text": row.get("message_text") or "",
                        "latest_guest_turn": row.get("latest_guest_turn") or row.get("message_text") or "",
                        "prior_thread_context": row.get("prior_thread_context") or "",
                        "draft_text": row.get("draft_text") or "",
                        "final_reply": row.get("final_reply") or "",
                        "intent": row.get("intent") or "general",
                        "asks_json": json.dumps(asks),
                        "policy_flags": json.dumps(_safe_json_list(row.get("policy_flags"))),
                        "policy_warnings": json.dumps(_safe_json_list(row.get("policy_warnings"))),
                        "blocked_by_gap_topics": json.dumps(_safe_json_list(row.get("blocked_by_gap_topics"))),
                        "triggered_by": row.get("triggered_by") or None,
                        "property_external_id": row.get("property_external_id") or "",
                        "property_name": row.get("property_name") or row.get("property_external_id") or "Unknown property",
                        "property_binding_candidates": json.dumps(_safe_json_list(row.get("property_binding_candidates"))),
                        "selected_property_code": row.get("selected_property_code") or "",
                        "property_match_type": row.get("selected_property_match_type") or "",
                        "route_outcome": row.get("route_outcome") or "",
                        "draft_source": row.get("normalization_draft_source") or "",
                        "autonomy_decision": row.get("autonomy_decision") or "",
                        "fallback_reason": row.get("fallback_reason") or "",
                        "prior_operator_commitments": json.dumps(_safe_json_list(row.get("prior_operator_commitments"))),
                        "confidence": row.get("confidence") or 0,
                        # Phase 1 confidence split mirror columns. Empty
                        # string maps to NULL via NULLIF in the SQL so the
                        # CAST to enum doesn't fail on legacy rows.
                        "intent_confidence": row.get("intent_confidence"),
                        "draft_confidence": row.get("draft_confidence"),
                        "confidence_source": row.get("confidence_source") or "",
                        "review_verdict": row.get("review_verdict") or "",
                        "latest_turn_confidence": row.get("latest_turn_confidence"),
                        "latest_turn_extracted": bool(row.get("latest_turn_extracted")),
                        "queue_status": row.get("status") or "pending_review",
                        "review_status": row.get("status") or "pending_review",
                        "received_at": row.get("received_at"),
                        "replied_at": row.get("replied_at"),
                    },
                )
            await session.commit()
        except Exception as exc:
            logger.warning("[PrebookingQueueService] persist skipped: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass

    async def _load_cached_rows(
        self,
        *,
        session: AsyncSession,
        tenant_id: str,
        status: str,
        limit: int,
        property_external_id: str,
        unbound_only: bool = False,
        assignee_id: str = "",
        team_key: str = "",
        portfolio_key: str = "",
        assigned_to_me: bool = False,
    ) -> list[dict]:
        if not await self._table_exists(session, "operator_prebooking_queue_read_models"):
            return []
        status_clause = "" if status in ("", "all") else "AND review_status = :status"
        binding_code_sql = "COALESCE(NULLIF(property_external_id, ''), NULLIF(selected_property_code, ''))"
        if unbound_only:
            property_clause = f"AND ({binding_code_sql} IS NULL OR {binding_code_sql} = '')"
        else:
            property_clause = "" if not property_external_id else f"AND {binding_code_sql} = :prop"
        try:
            rows = (
                await session.execute(
                    text(
                        f"""
                        SELECT
                            CAST(guest_thread_id AS text) AS guest_thread_id,
                            draft_id,
                            platform,
                            source_provider,
                            guest_name,
                            guest_email,
                            message_text,
                            latest_guest_turn,
                            prior_thread_context,
                            draft_text,
                            intent,
                            asks_json AS extracted_asks,
                            '[]'::jsonb AS normalized_asks,
                            property_binding_candidates,
                            prior_operator_commitments,
                            property_match_type AS selected_property_match_type,
                            route_outcome,
                            fallback_reason,
                            latest_turn_confidence,
                            latest_turn_extracted,
                            confidence,
                            intent_confidence,
                            draft_confidence,
                            CAST(confidence_source AS text) AS confidence_source,
                            CAST(review_verdict AS text) AS review_verdict,
                            review_status AS status,
                            {binding_code_sql} AS property_external_id,
                            property_name,
                            selected_property_code,
                            NULL::date AS requested_check_in,
                            NULL::date AS requested_check_out,
                            NULL::int AS requested_guests,
                            policy_flags,
                            policy_warnings,
                            blocked_by_gap_topics,
                            triggered_by,
                            received_at,
                            replied_at,
                            final_reply,
                            source_message_id AS gmail_message_id,
                            thread_id AS gmail_thread_id,
                            assigned_operator_id,
                            assigned_team_key,
                            portfolio_key,
                            assignment_status,
                            ''::text AS parser_source,
                            ''::text AS platform_listing_id,
                            ''::text AS platform_unit_id,
                            draft_source AS normalization_draft_source,
                            COALESCE(autonomy_decision, ''::text) AS autonomy_decision
                        FROM operator_prebooking_queue_read_models
                        WHERE tenant_id = CAST(:tid AS uuid)
                        {status_clause}
                        {property_clause}
                        ORDER BY received_at DESC NULLS LAST, refreshed_at DESC
                        LIMIT :limit
                        """
                    ),
                    {"tid": tenant_id, "status": status, "prop": property_external_id, "limit": limit},
                )
            ).mappings().all()
            cached_rows = self._filter_rows(
                [dict(row) for row in rows],
                assignee_id=assignee_id,
                team_key=team_key,
                portfolio_key=portfolio_key,
                assigned_to_me=assigned_to_me,
            )
            return cached_rows[:limit] if limit else cached_rows
        except Exception as exc:
            logger.warning("[PrebookingQueueService] cached load failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return []

    def _filter_rows(
        self,
        rows: list[dict],
        *,
        assignee_id: str = "",
        team_key: str = "",
        portfolio_key: str = "",
        assigned_to_me: bool = False,
    ) -> list[dict]:
        filtered = rows
        if assigned_to_me and assignee_id:
            filtered = [row for row in filtered if str(row.get("assigned_operator_id") or "") == assignee_id]
        elif assignee_id:
            filtered = [row for row in filtered if str(row.get("assigned_operator_id") or "") == assignee_id]
        if team_key:
            filtered = [row for row in filtered if str(row.get("assigned_team_key") or "") == team_key]
        if portfolio_key:
            filtered = [row for row in filtered if str(row.get("portfolio_key") or "") == portfolio_key]
        return filtered

    async def assign_draft(
        self,
        session: AsyncSession,
        tenant_id: str,
        draft_id: str,
        *,
        assigned_operator_id: str = "",
        assigned_team_key: str = "",
        portfolio_key: str = "",
    ) -> bool:
        if not await self._table_exists(session, "operator_prebooking_queue_read_models"):
            return False
        assignment_status = "assigned" if (assigned_operator_id or assigned_team_key or portfolio_key) else "unassigned"
        try:
            await session.execute(
                text(
                    """
                    UPDATE operator_prebooking_queue_read_models
                    SET assigned_operator_id = CAST(NULLIF(:assigned_operator_id, '') AS uuid),
                        assigned_team_key = NULLIF(:assigned_team_key, ''),
                        portfolio_key = NULLIF(:portfolio_key, ''),
                        assignment_status = :assignment_status,
                        refreshed_at = NOW()
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND draft_id = :draft_id
                    """
                ),
                {
                    "tid": tenant_id,
                    "draft_id": draft_id,
                    "assigned_operator_id": assigned_operator_id or "",
                    "assigned_team_key": assigned_team_key or "",
                    "portfolio_key": portfolio_key or "",
                    "assignment_status": assignment_status,
                },
            )
            await session.commit()
            return True
        except Exception as exc:
            logger.warning("[PrebookingQueueService] assign_draft failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return False


_SERVICE = PrebookingQueueService()


def get_prebooking_queue_service() -> PrebookingQueueService:
    return _SERVICE
