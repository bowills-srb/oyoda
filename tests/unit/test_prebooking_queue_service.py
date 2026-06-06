from __future__ import annotations

import asyncio

from app.services.operator.prebooking_queue_service import PrebookingQueueService


class _FakeMappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeSession:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.executed = []
        self.rollbacks = 0
        self.commits = 0

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        action = self.scripted.pop(0)
        if isinstance(action, Exception):
            raise action
        kind, payload = action
        if kind == "mappings":
            class _Wrapper:
                def __init__(self, rows):
                    self._rows = rows

                def mappings(self):
                    return _FakeMappingsResult(self._rows)

            return _Wrapper(payload)
        if kind == "fetchall":
            return _FakeScalarResult(payload)
        if kind == "ok":
            class _Wrapper:
                rowcount = 1
            return _Wrapper()
        raise AssertionError(f"Unknown scripted action: {kind}")

    async def scalar(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        action = self.scripted.pop(0)
        if isinstance(action, Exception):
            raise action
        kind, payload = action
        assert kind == "scalar"
        return payload

    async def rollback(self):
        self.rollbacks += 1

    async def commit(self):
        self.commits += 1


def test_fetch_queue_rows_falls_back_to_cached_rows_when_live_query_fails():
    service = PrebookingQueueService()
    db = _FakeSession(
        [
            ("fetchall", [("property_code",), ("property_name",), ("tenant_id",)]),
            RuntimeError("live query failed"),
            RuntimeError("compat query failed"),
            ("scalar", True),
            ("mappings", [
                {
                    "draft_id": "INQ-1",
                    "guest_thread_id": "thread-uuid-1",
                    "platform": "email",
                    "source_provider": "gmail",
                    "guest_name": "Guest",
                    "guest_email": "guest@example.com",
                    "message_text": "Hi",
                    "latest_guest_turn": "Hi",
                    "prior_thread_context": "",
                    "draft_text": "Hello",
                    "intent": "general",
                    "extracted_asks": [],
                    "normalized_asks": [],
                    "property_binding_candidates": [],
                    "prior_operator_commitments": [],
                    "selected_property_match_type": "exact",
                    "route_outcome": "pre_booking",
                    "fallback_reason": "",
                    "latest_turn_confidence": 0.9,
                    "latest_turn_extracted": True,
                    "confidence": 0.8,
                    "status": "pending_review",
                    "property_external_id": "LANIER-1",
                    "property_name": "Lanier",
                    "requested_check_in": None,
                    "requested_check_out": None,
                    "requested_guests": None,
                    "policy_flags": [],
                    "policy_warnings": [],
                    "received_at": None,
                    "replied_at": None,
                    "final_reply": "",
                    "gmail_message_id": "msg-1",
                    "gmail_thread_id": "thread-1",
                    "parser_source": "",
                    "platform_listing_id": "",
                    "platform_unit_id": "",
                    "normalization_draft_source": "model",
                }
            ]),
        ]
    )

    rows = asyncio.run(
        service.fetch_queue_rows(
            session=db,
            tenant_id="e07980b2-a990-4b24-91d1-c8cb71ab70e1",
            status="pending_review",
            limit=25,
        )
    )

    assert len(rows) == 1
    assert rows[0]["draft_id"] == "INQ-1"
    assert db.rollbacks >= 1


def test_sync_draft_returns_true_when_live_row_is_available():
    service = PrebookingQueueService()
    db = _FakeSession(
        [
            ("fetchall", [("property_code",), ("property_name",), ("tenant_id",)]),
            ("mappings", [
                {
                    "draft_id": "INQ-2",
                    "guest_thread_id": "thread-uuid-2",
                    "thread_id": "thread-2",
                    "message_id": "msg-2",
                    "platform": "email",
                    "guest_name": "Guest",
                    "guest_email": "guest@example.com",
                    "message_text": "Hello",
                    "draft_text": "Draft",
                    "intent": "general",
                    "confidence": 0.8,
                    "status": "pending_review",
                    "property_external_id": "LANIER-2",
                    "requested_check_in": None,
                    "requested_check_out": None,
                    "requested_guests": None,
                    "policy_flags": [],
                    "policy_warnings": [],
                    "received_at": None,
                    "replied_at": None,
                    "final_reply": "",
                    "gmail_message_id": "msg-2",
                    "gmail_thread_id": "thread-2",
                    "parser_source": "",
                    "extracted_asks": [],
                    "platform_listing_id": "",
                    "platform_unit_id": "",
                    "source_provider": "gmail",
                    "latest_guest_turn": "Hello",
                    "prior_thread_context": "",
                    "normalized_asks": [],
                    "prior_operator_commitments": [],
                    "property_binding_candidates": [],
                    "selected_property_code": "LANIER-2",
                    "selected_property_match_type": "exact",
                    "route_outcome": "pre_booking",
                    "normalization_draft_source": "model",
                    "fallback_reason": "",
                    "latest_turn_confidence": 0.9,
                    "latest_turn_extracted": True,
                    "property_name": "Lanier",
                }
            ]),
            ("scalar", True),
            ("mappings", []),
            ("scalar", True),
            ("ok", None),
        ]
    )

    synced = asyncio.run(
        service.sync_draft(
            session=db,
            tenant_id="e07980b2-a990-4b24-91d1-c8cb71ab70e1",
            draft_id="INQ-2",
        )
    )

    assert synced is True
    assert db.commits == 1


def test_sync_draft_live_join_uses_canonical_email_channel():
    service = PrebookingQueueService()
    db = _FakeSession(
        [
            ("fetchall", [("property_code",), ("property_name",), ("tenant_id",)]),
            ("mappings", [
                {
                    "draft_id": "INQ-EMAIL",
                    "guest_thread_id": "thread-uuid-email",
                    "thread_id": "thread-email",
                    "message_id": "msg-email",
                    "platform": "email",
                    "guest_name": "Guest",
                    "guest_email": "guest@example.com",
                    "message_text": "Hello",
                    "draft_text": "Draft",
                    "intent": "general",
                    "confidence": 0.8,
                    "status": "pending_review",
                    "property_external_id": "LANIER-E",
                    "requested_check_in": None,
                    "requested_check_out": None,
                    "requested_guests": None,
                    "policy_flags": [],
                    "policy_warnings": [],
                    "received_at": None,
                    "replied_at": None,
                    "final_reply": "",
                    "gmail_message_id": "msg-email",
                    "gmail_thread_id": "thread-email",
                    "parser_source": "",
                    "extracted_asks": [],
                    "platform_listing_id": "",
                    "platform_unit_id": "",
                    "source_provider": "gmail",
                    "latest_guest_turn": "Hello",
                    "prior_thread_context": "",
                    "normalized_asks": [],
                    "prior_operator_commitments": [],
                    "property_binding_candidates": [],
                    "selected_property_code": "LANIER-E",
                    "selected_property_match_type": "exact",
                    "route_outcome": "pre_booking_new",
                    "normalization_draft_source": "messaging_brain",
                    "fallback_reason": "",
                    "latest_turn_confidence": 0.9,
                    "latest_turn_extracted": True,
                    "property_name": "Lanier",
                }
            ]),
            ("scalar", True),
            ("mappings", []),
            ("scalar", True),
            ("ok", None),
        ]
    )

    synced = asyncio.run(
        service.sync_draft(
            session=db,
            tenant_id="e07980b2-a990-4b24-91d1-c8cb71ab70e1",
            draft_id="INQ-EMAIL",
        )
    )

    assert synced is True
    live_sql, _ = db.executed[1]
    assert "mn.source_channel = 'email'" in live_sql
    assert "mn.source_channel = 'gmail'" not in live_sql


def test_load_cached_rows_preserves_guest_thread_id():
    service = PrebookingQueueService()
    db = _FakeSession(
        [
            ("scalar", True),
            ("mappings", [
                {
                    "guest_thread_id": "thread-uuid-3",
                    "draft_id": "INQ-3",
                    "platform": "email",
                    "source_provider": "gmail",
                    "guest_name": "Guest",
                    "guest_email": "guest@example.com",
                    "message_text": "Hi",
                    "latest_guest_turn": "Hi",
                    "prior_thread_context": "",
                    "draft_text": "Hello",
                    "intent": "general",
                    "extracted_asks": [],
                    "normalized_asks": [],
                    "property_binding_candidates": [],
                    "prior_operator_commitments": [],
                    "selected_property_match_type": "exact",
                    "route_outcome": "pre_booking",
                    "fallback_reason": "",
                    "latest_turn_confidence": 0.9,
                    "latest_turn_extracted": True,
                    "confidence": 0.8,
                    "status": "pending_review",
                    "property_external_id": "LANIER-3",
                    "property_name": "Lanier",
                    "requested_check_in": None,
                    "requested_check_out": None,
                    "requested_guests": None,
                    "policy_flags": [],
                    "policy_warnings": [],
                    "received_at": None,
                    "replied_at": None,
                    "final_reply": "",
                    "gmail_message_id": "msg-3",
                    "gmail_thread_id": "thread-3",
                    "assigned_operator_id": "",
                    "assigned_team_key": "",
                    "portfolio_key": "",
                    "assignment_status": "unassigned",
                    "parser_source": "",
                    "platform_listing_id": "",
                    "platform_unit_id": "",
                    "normalization_draft_source": "model",
                }
            ]),
        ]
    )

    rows = asyncio.run(
        service._load_cached_rows(
            session=db,
            tenant_id="e07980b2-a990-4b24-91d1-c8cb71ab70e1",
            status="pending_review",
            limit=25,
            property_external_id="",
        )
    )

    assert rows[0]["guest_thread_id"] == "thread-uuid-3"


def test_load_cached_rows_can_filter_to_unbound_only():
    service = PrebookingQueueService()
    db = _FakeSession(
        [
            ("scalar", True),
            ("mappings", [
                {
                    "guest_thread_id": "thread-uuid-4",
                    "draft_id": "INQ-4",
                    "platform": "email",
                    "source_provider": "gmail",
                    "guest_name": "Guest",
                    "guest_email": "guest@example.com",
                    "message_text": "Hi",
                    "latest_guest_turn": "Hi",
                    "prior_thread_context": "",
                    "draft_text": "Hello",
                    "intent": "general",
                    "extracted_asks": [],
                    "normalized_asks": [],
                    "property_binding_candidates": [],
                    "prior_operator_commitments": [],
                    "selected_property_match_type": "",
                    "route_outcome": "pre_booking",
                    "fallback_reason": "",
                    "latest_turn_confidence": 0.9,
                    "latest_turn_extracted": True,
                    "confidence": 0.8,
                    "status": "pending_review",
                    "property_external_id": "",
                    "property_name": "Unknown property",
                    "requested_check_in": None,
                    "requested_check_out": None,
                    "requested_guests": None,
                    "policy_flags": [],
                    "policy_warnings": [],
                    "received_at": None,
                    "replied_at": None,
                    "final_reply": "",
                    "gmail_message_id": "msg-4",
                    "gmail_thread_id": "thread-4",
                    "assigned_operator_id": "",
                    "assigned_team_key": "",
                    "portfolio_key": "",
                    "assignment_status": "unassigned",
                    "parser_source": "",
                    "platform_listing_id": "",
                    "platform_unit_id": "",
                    "normalization_draft_source": "model",
                }
            ]),
        ]
    )

    rows = asyncio.run(
        service._load_cached_rows(
            session=db,
            tenant_id="e07980b2-a990-4b24-91d1-c8cb71ab70e1",
            status="pending_review",
            limit=25,
            property_external_id="",
            unbound_only=True,
        )
    )

    assert rows[0]["draft_id"] == "INQ-4"
    statement, _ = db.executed[-1]
    assert "COALESCE(NULLIF(property_external_id, ''), NULLIF(selected_property_code, '')) IS NULL" in statement


def test_filter_rows_can_scope_to_assignee_team_and_portfolio():
    service = PrebookingQueueService()
    rows = [
        {
            "draft_id": "INQ-1",
            "assigned_operator_id": "op-1",
            "assigned_team_key": "manager",
            "portfolio_key": "lanier",
        },
        {
            "draft_id": "INQ-2",
            "assigned_operator_id": "op-2",
            "assigned_team_key": "staff",
            "portfolio_key": "beach",
        },
    ]

    filtered = service._filter_rows(
        rows,
        assignee_id="op-1",
        team_key="manager",
        portfolio_key="lanier",
    )

    assert [row["draft_id"] for row in filtered] == ["INQ-1"]


def test_assign_draft_returns_false_when_table_missing():
    service = PrebookingQueueService()
    db = _FakeSession([("scalar", False)])

    assigned = asyncio.run(
        service.assign_draft(
            session=db,
            tenant_id="e07980b2-a990-4b24-91d1-c8cb71ab70e1",
            draft_id="INQ-3",
            assigned_operator_id="11111111-1111-1111-1111-111111111111",
        )
    )

    assert assigned is False


def test_persist_rows_carries_confidence_split_columns():
    """Migration 087 added intent_confidence, draft_confidence,
    confidence_source, and review_verdict to the queue read model. The
    queue service must bind those values from the source row into the
    INSERT params, with empty strings normalized to NULL via NULLIF in
    the SQL so the enum CAST does not fail on legacy rows.

    This test exercises the param binding directly. The SQL itself is
    only asserted to mention the new columns; round-tripping through a
    real database is covered by integration tests.
    """
    service = PrebookingQueueService()
    db = _FakeSession(
        [
            ("scalar", True),   # _table_exists check inside _persist_rows
            ("ok", None),       # the INSERT itself
        ]
    )

    row_with_full_split = {
        "guest_thread_id": "thread-uuid-c",
        "draft_id": "INQ-C",
        "thread_id": "thread-c",
        "message_id": "msg-c",
        "gmail_message_id": "gmsg-c",
        "platform": "email",
        "source_provider": "gmail",
        "guest_name": "Casey",
        "guest_email": "casey@example.com",
        "message_text": "Hi",
        "latest_guest_turn": "Hi",
        "prior_thread_context": "",
        "draft_text": "Hello",
        "final_reply": "",
        "intent": "general",
        "extracted_asks": [],
        "normalized_asks": [],
        "policy_flags": [],
        "policy_warnings": [],
        "blocked_by_gap_topics": [],
        "triggered_by": None,
        "property_external_id": "LANIER-C",
        "property_name": "Lanier",
        "property_binding_candidates": [],
        "selected_property_code": "LANIER-C",
        "selected_property_match_type": "exact",
        "route_outcome": "pre_booking",
        "normalization_draft_source": "messaging_brain",
        "autonomy_decision": "draft_only",
        "fallback_reason": "",
        "prior_operator_commitments": [],
        "confidence": 0.83,
        "intent_confidence": 0.85,
        "draft_confidence": 0.83,
        "confidence_source": "model_composer",
        "review_verdict": "pass",
        "latest_turn_confidence": 0.9,
        "latest_turn_extracted": True,
        "status": "pending_review",
        "received_at": None,
        "replied_at": None,
    }

    asyncio.run(
        service._persist_rows(
            db,
            "e07980b2-a990-4b24-91d1-c8cb71ab70e1",
            [row_with_full_split],
        )
    )

    # The first executed statement is the table_exists scalar check; the
    # second is the INSERT itself.
    insert_sql, insert_params = db.executed[1]

    assert "intent_confidence" in insert_sql
    assert "draft_confidence" in insert_sql
    assert "confidence_source" in insert_sql
    assert "review_verdict" in insert_sql

    assert insert_params["intent_confidence"] == 0.85
    assert insert_params["draft_confidence"] == 0.83
    assert insert_params["confidence_source"] == "model_composer"
    assert insert_params["review_verdict"] == "pass"


def test_persist_rows_normalizes_missing_confidence_split_to_empty_for_nullif():
    """Rows from legacy code paths (or the dispatch exception-fallback
    path before the brain ran) won't carry confidence_source/review_verdict.
    The persist path should bind empty strings for the enum-typed columns,
    which the SQL converts to NULL via NULLIF before casting. Numeric
    columns bind None, which goes in as NULL directly.
    """
    service = PrebookingQueueService()
    db = _FakeSession(
        [
            ("scalar", True),
            ("ok", None),
        ]
    )

    row_without_split = {
        "guest_thread_id": "thread-uuid-d",
        "draft_id": "INQ-D",
        "thread_id": "thread-d",
        "message_id": "msg-d",
        "gmail_message_id": "gmsg-d",
        "platform": "email",
        "source_provider": "gmail",
        "guest_name": "Dana",
        "guest_email": "",
        "message_text": "Hi",
        "draft_text": "",
        "intent": "general",
        "confidence": 0.55,
        # intentionally NO intent_confidence / draft_confidence /
        # confidence_source / review_verdict keys here.
        "property_external_id": "",
        "property_name": "Unknown property",
        "status": "pending_review",
        "received_at": None,
        "replied_at": None,
        "final_reply": "",
        "autonomy_decision": "",
    }

    asyncio.run(
        service._persist_rows(
            db,
            "e07980b2-a990-4b24-91d1-c8cb71ab70e1",
            [row_without_split],
        )
    )

    _, insert_params = db.executed[1]
    assert insert_params["intent_confidence"] is None
    assert insert_params["draft_confidence"] is None
    assert insert_params["confidence_source"] == ""
    assert insert_params["review_verdict"] == ""
