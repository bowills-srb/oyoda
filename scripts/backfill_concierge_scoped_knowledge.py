from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from app.services.concierge.knowledge_service import _normalize_question_key


@dataclass
class BackfillDecision:
    action: str
    reason: Optional[str] = None
    scope_target_id: Optional[str] = None
    topic_id: Optional[str] = None
    question_key: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


def _db_url() -> str:
    raw = (os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not raw:
        raise SystemExit("ALEMBIC_DATABASE_URL or DATABASE_URL must be set")
    return raw.replace("postgresql+asyncpg://", "postgresql://", 1)


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def compute_question_key(question_text: str) -> str:
    normalized = _normalize_question_key(question_text)
    if normalized:
        return normalized
    return _normalize_text(question_text).lower()


def build_metadata(
    *,
    row: dict[str, Any],
    migration_run_id: str,
    migrated_at: str,
) -> dict[str, Any]:
    return {
        "legacy_id": str(row["knowledge_id"]),
        "legacy_category": row.get("category"),
        "legacy_confidence": row.get("confidence"),
        "legacy_valid_from": row.get("valid_from").isoformat() if row.get("valid_from") else None,
        "legacy_valid_until": row.get("valid_until").isoformat() if row.get("valid_until") else None,
        "migration_run_id": migration_run_id,
        "migrated_at": migrated_at,
    }


def decide_row(
    row: dict[str, Any],
    property_map: dict[str, str],
    existing_legacy_ids: set[str],
    migration_run_id: str,
    migrated_at: str,
) -> BackfillDecision:
    tenant_id = row.get("tenant_id")
    if tenant_id is None:
        return BackfillDecision(action="skip", reason="null_tenant")

    property_external_id = _normalize_text(row.get("property_external_id"))
    scope_target_id = property_map.get(property_external_id)
    if not scope_target_id:
        return BackfillDecision(action="skip", reason="unresolvable_property")

    legacy_id = str(row["knowledge_id"])
    if legacy_id in existing_legacy_ids:
        return BackfillDecision(action="skip", reason="already_migrated")

    question_text = _normalize_text(row.get("question"))
    answer_text = _normalize_text(row.get("answer"))
    if not question_text or not answer_text:
        return BackfillDecision(action="skip", reason="empty_content")

    question_key = compute_question_key(question_text)
    metadata = build_metadata(
        row=row,
        migration_run_id=migration_run_id,
        migrated_at=migrated_at,
    )
    return BackfillDecision(
        action="migrate",
        scope_target_id=scope_target_id,
        topic_id=None,
        question_key=question_key,
        metadata=metadata,
    )


def load_property_map(cur, tenant_id: Optional[str] = None) -> dict[str, str]:
    where = ""
    params: list[Any] = []
    if tenant_id:
        where = "WHERE tenant_id = %s"
        params.append(tenant_id)
    cur.execute(
        f"""
        SELECT id::text, property_code, external_id
        FROM properties
        {where}
        """,
        params,
    )
    mapping: dict[str, str] = {}
    for row in cur.fetchall():
        property_id = str(row["id"])
        for key in (row.get("property_code"), row.get("external_id")):
            normalized = _normalize_text(key)
            if normalized:
                mapping[normalized] = property_id
    return mapping


def load_existing_legacy_ids(cur) -> set[str]:
    cur.execute(
        """
        SELECT metadata->>'legacy_id' AS legacy_id
        FROM concierge_scoped_knowledge
        WHERE source = 'legacy_concierge_knowledge'
          AND metadata ? 'legacy_id'
        """
    )
    return {str(row["legacy_id"]) for row in cur.fetchall() if row.get("legacy_id")}


def load_legacy_rows(cur) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT knowledge_id, tenant_id, property_external_id, category, question,
               answer, confidence, source, valid_from, valid_until, created_at, updated_at
        FROM concierge_knowledge
        ORDER BY created_at ASC, knowledge_id ASC
        """
    )
    return list(cur.fetchall())


def insert_migrated_row(
    cur,
    row: dict[str, Any],
    decision: BackfillDecision,
) -> None:
    cur.execute(
        """
        INSERT INTO concierge_scoped_knowledge (
            tenant_id,
            scope_type,
            scope_target_id,
            topic_id,
            question_text,
            question_key,
            answer_text,
            tags,
            source,
            metadata,
            created_by_user_id,
            created_at,
            updated_at,
            is_active,
            version
        ) VALUES (
            %s,
            'property',
            %s,
            %s,
            %s,
            %s,
            %s,
            %s::jsonb,
            'legacy_concierge_knowledge',
            %s::jsonb,
            NULL,
            COALESCE(%s, NOW()),
            COALESCE(%s, NOW()),
            TRUE,
            1
        )
        RETURNING knowledge_entry_id::text
        """,
        (
            str(row["tenant_id"]),
            decision.scope_target_id,
            decision.topic_id,
            _normalize_text(row["question"]),
            decision.question_key,
            _normalize_text(row["answer"]),
            Json([]),
            Json(decision.metadata or {}),
            row.get("created_at"),
            row.get("updated_at"),
        ),
    )
    knowledge_entry_id = cur.fetchone()["knowledge_entry_id"]
    cur.execute(
        """
        INSERT INTO concierge_scoped_knowledge_history (
            knowledge_entry_id,
            tenant_id,
            version,
            previous_question_text,
            previous_answer_text,
            previous_metadata,
            changed_by_user_id,
            change_type,
            changed_at
        ) VALUES (
            %s::uuid,
            %s::uuid,
            1,
            NULL,
            NULL,
            NULL,
            NULL,
            'created',
            NOW()
        )
        """,
        (knowledge_entry_id, str(row["tenant_id"])),
    )


def run_backfill(*, dry_run: bool) -> dict[str, Any]:
    migration_run_id = str(uuid.uuid4())
    migrated_at = datetime.now(timezone.utc).isoformat()

    conn = psycopg2.connect(_db_url(), cursor_factory=RealDictCursor)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            property_map = load_property_map(cur)
            existing_legacy_ids = load_existing_legacy_ids(cur)
            legacy_rows = load_legacy_rows(cur)

            report: dict[str, Any] = {
                "dry_run": dry_run,
                "migration_run_id": migration_run_id,
                "migrated_at": migrated_at,
                "total_scanned": len(legacy_rows),
                "migrated": 0,
                "migrated_with_topic": 0,
                "migrated_without_topic": 0,
                "skipped": {
                    "null_tenant": 0,
                    "unresolvable_property": 0,
                    "already_migrated": 0,
                    "empty_content": 0,
                    "duplicate_question_key": 0,
                },
                "samples": [],
                "unexpected_errors": [],
            }

            seen_question_keys: set[tuple[str, str, str]] = set()

            for row in legacy_rows:
                try:
                    decision = decide_row(
                        row=row,
                        property_map=property_map,
                        existing_legacy_ids=existing_legacy_ids,
                        migration_run_id=migration_run_id,
                        migrated_at=migrated_at,
                    )
                except Exception as exc:  # noqa: BLE001
                    report["unexpected_errors"].append(
                        {"knowledge_id": str(row.get("knowledge_id")), "error": f"{type(exc).__name__}: {exc}"}
                    )
                    continue

                if decision.action != "migrate":
                    report["skipped"][decision.reason or "unknown"] = report["skipped"].get(decision.reason or "unknown", 0) + 1
                    continue

                duplicate_key = (
                    str(row["tenant_id"]),
                    str(decision.scope_target_id),
                    str(decision.question_key),
                )
                if duplicate_key in seen_question_keys:
                    report["skipped"]["duplicate_question_key"] += 1
                    continue
                seen_question_keys.add(duplicate_key)

                report["migrated"] += 1
                report["migrated_without_topic"] += 1

                if len(report["samples"]) < 10:
                    report["samples"].append(
                        {
                            "knowledge_id": str(row["knowledge_id"]),
                            "property_external_id": row.get("property_external_id"),
                            "scope_target_id": decision.scope_target_id,
                            "topic_id": decision.topic_id,
                            "question_key": decision.question_key,
                            "question": _normalize_text(row.get("question")),
                        }
                    )

                if not dry_run:
                    insert_migrated_row(cur, row, decision)

            if dry_run:
                conn.rollback()
            else:
                conn.commit()
            return report
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill legacy concierge_knowledge rows into concierge_scoped_knowledge.")
    parser.add_argument("--dry-run", action="store_true", help="Scan and report without inserting rows.")
    args = parser.parse_args()

    report = run_backfill(dry_run=args.dry_run)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
