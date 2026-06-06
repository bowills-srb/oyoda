"""
retire_concierge_knowledge.py

Final pre-drop gate for the legacy `concierge_knowledge` table.

This script is the data-side half of Phase 1 closeout in the Brain-Only
Unified Migration Plan. It runs AFTER:
  * the brain knowledge service is in place (commit 99b55ad, 984181d)
  * dashboard, MCP, admin-seed, message_history, gmail-poller, and legacy
    admin endpoints have all been rewired off ConciergeKnowledgeService
  * scoped_knowledge_service.py no longer reads from concierge_knowledge
  * the existing backfill_concierge_scoped_knowledge.py has been used to
    mirror data through normal operations

It does five things, in order, in a single transaction (unless --dry-run):

  1. Row-level parity check. For every row in `concierge_knowledge`,
     verify a matching row exists in `concierge_scoped_knowledge` under
     the same property scope with the same question_key, regardless of
     source. Three outcomes per row:
       * MIRRORED   — already present in scoped with matching answer
       * MIGRATED   — was missing from scoped, inserted now
       * CONFLICT   — present in scoped with different answer; the more
                      recent updated_at wins, the other is logged
       * SKIPPED    — null tenant, unresolvable property, empty content

  2. Provenance tagging. Every row inserted by this script (or updated
     to win a conflict) gets two metadata fields:
       * migration_provenance: "legacy_concierge_knowledge_2026_05_23"
       * legacy_property_external_id: <source code>
     These let a future cleanup pass (after PMS sync gives an
     authoritative active-property list) soft-retire entries for
     properties Beach Habitats no longer manages.

  3. Archive snapshot. The full `concierge_knowledge` table contents
     are copied to `concierge_knowledge_archive_2026_05_23` so the
     drop migration that follows is reversible at the row level.

  4. Migration report. A JSON report is written to
     `scripts/output/retire_concierge_knowledge_<timestamp>.json`
     listing row counts by outcome, conflict resolutions, samples,
     and unexpected errors. This report is the artifact that should
     be cited in the commit message for the Alembic drop migration.

  5. The script does NOT drop the legacy table. That's a separate
     Alembic migration (`088_drop_concierge_knowledge.py`) which can
     only run after this script's report has been reviewed.

Property mapping handles the live join paths we actually found in Beach
Habitats production:
  * `properties.property_code` -> `properties.id`
    (primary; production legacy KB rows are keyed by property code)
  * `properties.external_id` -> `properties.id`
    (secondary direct mapping for any non-code legacy rows)
  * `pms_listings.external_id` -> `properties.id` via
    `properties.tenant_id = pms_listings.company_id` and
    `properties.property_code = pms_listings.external_id`
    (defensive fallback for environments where PMS external ids are the
    only usable join key)
  * `pms_listings.property_name` / `properties.address_street`
    case-insensitive fuzzy fallback

No active-property filter is applied. Per Hunter (2026-05-23): Beach
Habitats has no schema-level way to distinguish currently-managed vs.
no-longer-managed properties yet; that comes with PMS sync. Until then
we tag everything and let a future cleanup pass retire abandoned-
property entries once we have an authoritative active list.

Usage:
    python scripts/retire_concierge_knowledge.py --dry-run
    python scripts/retire_concierge_knowledge.py --execute

Environment:
    ALEMBIC_DATABASE_URL or DATABASE_URL must be set.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psycopg2
from psycopg2.extras import Json, RealDictCursor


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# This identifier is stamped onto every row this script writes or updates.
# After PMS sync gives us an authoritative active-property list, a separate
# cleanup pass will soft-retire scoped entries with this tag whose
# scope_target_id is no longer in the active-property set.
MIGRATION_PROVENANCE = "legacy_concierge_knowledge_2026_05_23"

ARCHIVE_TABLE = "concierge_knowledge_archive_2026_05_23"

# Output directory for the migration report. Created if it doesn't exist.
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"


# ---------------------------------------------------------------------------
# question_key normalization
#
# Inlined rather than imported from app.services.concierge.knowledge_service
# because this script needs to run at the gate where that module is about to
# be deleted. The logic mirrors `_normalize_message` + `_normalize_question_key`
# in knowledge_service.py exactly. If those functions ever change, change them
# here too (they shouldn't change — they define a canonical hash).
# ---------------------------------------------------------------------------

_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "from", "your", "you", "are",
        "can", "could", "would", "should", "what", "when", "where", "which", "who",
        "how", "why", "does", "did", "have", "has", "had", "our", "about", "into",
        "them", "they", "will", "just", "need", "any", "all", "get", "let", "know",
    }
)


def _normalize_message_tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def normalize_question_key(text: str) -> str:
    """Canonical question_key. Identical to knowledge_service._normalize_question_key."""
    return " ".join(sorted(_normalize_message_tokens(text)))


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def compute_question_key(question_text: str) -> str:
    normalized = normalize_question_key(question_text)
    if normalized:
        return normalized
    return _normalize_text(question_text).lower()


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------


def _db_url() -> str:
    raw = (
        os.environ.get("ALEMBIC_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or ""
    ).strip()
    if not raw:
        raise SystemExit(
            "ALEMBIC_DATABASE_URL or DATABASE_URL must be set "
            "(use the Beach Habitats Supabase pooler URL)."
        )
    # psycopg2 needs the plain postgresql:// scheme, not postgresql+asyncpg://.
    return raw.replace("postgresql+asyncpg://", "postgresql://", 1)


# ---------------------------------------------------------------------------
# Property mapping
# ---------------------------------------------------------------------------


def load_property_map(cur) -> dict[tuple[str, str], str]:
    """
    Build a map from (tenant_id, property_external_id) -> property_id (UUID).

    Resolves through three join paths in priority order:
      1. properties.property_code (primary for Beach Habitats production)
      2. properties.external_id (secondary direct mapping)
      3. pms_listings.external_id via company/property join (defensive)
      4. pms_listings.property_name / properties.address_street
         (case-insensitive fuzzy fallback)

    Returned keys are (tenant_id_str, external_id_str). Both are
    normalized (whitespace-collapsed); external_id_str is also stored
    lowercased as a separate key for case-insensitive lookup.
    """
    mapping: dict[tuple[str, str], str] = {}

    # 1) properties.property_code is the primary join for Beach Habitats.
    #    The live legacy concierge_knowledge rows are keyed by property code.
    cur.execute(
        """
        SELECT id::text AS property_id,
               tenant_id::text AS tenant_id,
               property_code,
               external_id,
               address_street
        FROM properties
        WHERE tenant_id IS NOT NULL
        """
    )
    for row in cur.fetchall():
        tenant = _normalize_text(row.get("tenant_id"))
        property_id = row.get("property_id")
        if not tenant or not property_id:
            continue
        property_code = _normalize_text(row.get("property_code"))
        if property_code:
            mapping[(tenant, property_code)] = property_id
            mapping[(tenant, property_code.lower())] = property_id
        external = _normalize_text(row.get("external_id"))
        if external:
            mapping.setdefault((tenant, external), property_id)
            mapping.setdefault((tenant, external.lower()), property_id)
        address = _normalize_text(row.get("address_street"))
        if address:
            mapping.setdefault((tenant, address.lower()), property_id)

    # 2) Defensive PMS join path. In some environments the only stable
    #    join key may be pms_listings.external_id or property_name. Beach
    #    Habitats production does not currently use this as the primary
    #    path, but keeping it here makes the script portable.
    try:
        cur.execute(
            """
            SELECT pr.id::text AS property_id,
                   pr.tenant_id::text AS tenant_id,
                   pl.external_id,
                   pl.property_name
            FROM pms_listings pl
            JOIN properties pr
              ON pr.tenant_id = pl.company_id
             AND (
                    pr.property_code = pl.external_id
                 OR pr.external_id = pl.external_id
                 OR LOWER(COALESCE(pr.address_street, '')) = LOWER(COALESCE(pl.property_name, ''))
             )
            WHERE pl.external_id IS NOT NULL
              AND pl.external_id <> ''
            """
        )
        for row in cur.fetchall():
            tenant = _normalize_text(row.get("tenant_id"))
            external = _normalize_text(row.get("external_id"))
            property_id = row.get("property_id")
            if tenant and external and property_id:
                mapping.setdefault((tenant, external), property_id)
                mapping.setdefault((tenant, external.lower()), property_id)
            property_name = _normalize_text(row.get("property_name"))
            if tenant and property_name and property_id:
                mapping.setdefault((tenant, property_name.lower()), property_id)
    except psycopg2.Error:
        # pms_listings may not exist in some environments (test DBs). Continue
        # with the properties-table path only. The connection's transaction is
        # poisoned by the failed query, so reset it before the next read.
        cur.connection.rollback()

    return mapping


def resolve_property_id(
    property_map: dict[tuple[str, str], str],
    tenant_id: str,
    property_external_id: str,
) -> Optional[str]:
    """Return the UUID property_id for a (tenant_id, external_id) pair."""
    tenant = _normalize_text(tenant_id)
    external = _normalize_text(property_external_id)
    if not tenant or not external:
        return None
    if (tenant, external) in property_map:
        return property_map[(tenant, external)]
    return property_map.get((tenant, external.lower()))


# ---------------------------------------------------------------------------
# Legacy row loading
# ---------------------------------------------------------------------------


def load_legacy_rows(cur) -> list[dict[str, Any]]:
    """
    Load every row from `concierge_knowledge`. The production table is in
    legacy Q&A shape:
        knowledge_id (PK), tenant_id, property_external_id, category,
        question, answer, source, is_active, created_at, updated_at
    with optional columns: canonical_property_id, confidence, valid_from,
    valid_until.

    We SELECT defensively because not every environment has every column.
    """
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'concierge_knowledge'
        """
    )
    available = {str(r["column_name"]) for r in cur.fetchall()}
    if not available:
        return []

    select_parts: list[str] = []
    for col in (
        "knowledge_id", "tenant_id", "property_external_id",
        "category", "question", "answer", "source",
        "confidence", "is_active",
        "valid_from", "valid_until", "created_at", "updated_at",
    ):
        if col in available:
            select_parts.append(col)
        elif col == "is_active":
            select_parts.append("TRUE AS is_active")
        elif col in ("valid_from", "valid_until", "confidence"):
            select_parts.append(f"NULL AS {col}")
        else:
            select_parts.append(f"NULL AS {col}")

    cur.execute(
        f"""
        SELECT {", ".join(select_parts)}
        FROM concierge_knowledge
        ORDER BY created_at ASC NULLS LAST, knowledge_id ASC
        """
    )
    return list(cur.fetchall())


# ---------------------------------------------------------------------------
# Scoped table parity lookup
# ---------------------------------------------------------------------------


def load_existing_scoped_index(
    cur,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    """
    Build an index of every existing scoped row keyed by
    (tenant_id, scope_target_id, question_key). The value contains the
    fields needed to decide CONFLICT vs MIRRORED.

    We index regardless of `source` because the parity question is
    "does an equivalent entry exist," not "did we already migrate this
    legacy_id". A row mirrored via Codex's earlier work, the existing
    backfill_concierge_scoped_knowledge.py, or a guidebook ingest all
    count as parity.
    """
    cur.execute(
        """
        SELECT
            knowledge_entry_id::text AS knowledge_entry_id,
            tenant_id::text          AS tenant_id,
            scope_type,
            scope_target_id::text    AS scope_target_id,
            question_key,
            answer_text,
            source,
            metadata,
            updated_at
        FROM concierge_scoped_knowledge
        WHERE scope_type = 'property'
          AND COALESCE(is_active, TRUE) = TRUE
        """
    )
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in cur.fetchall():
        key = (
            str(row["tenant_id"]),
            str(row["scope_target_id"]),
            str(row["question_key"] or ""),
        )
        index[key] = row
    return index


# ---------------------------------------------------------------------------
# Outcome model
# ---------------------------------------------------------------------------


@dataclass
class RowOutcome:
    """One legacy row's fate in this run."""

    knowledge_id: str
    tenant_id: Optional[str]
    property_external_id: Optional[str]
    scope_target_id: Optional[str]
    question_key: Optional[str]
    question_text: Optional[str]
    outcome: str  # "mirrored" | "migrated" | "conflict_resolved" | "skipped"
    reason: Optional[str] = None  # populated for skipped
    conflict_winner: Optional[str] = None  # "legacy" | "scoped" — populated for conflicts
    conflict_existing_entry_id: Optional[str] = None


@dataclass
class RunReport:
    dry_run: bool
    migration_run_id: str
    started_at: str
    finished_at: str = ""
    db_url_host: str = ""
    total_legacy_rows: int = 0
    counts: dict[str, int] = field(
        default_factory=lambda: {
            "mirrored": 0,
            "migrated": 0,
            "conflict_resolved_legacy_wins": 0,
            "conflict_resolved_scoped_wins": 0,
            "skipped_null_tenant": 0,
            "skipped_unresolvable_property": 0,
            "skipped_empty_content": 0,
            "skipped_inactive_row": 0,
            "skipped_within_run_duplicate": 0,
        }
    )
    archive_table_created: bool = False
    archive_row_count: int = 0
    archive_table_already_existed: bool = False
    samples: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {
            "mirrored": [],
            "migrated": [],
            "conflicts": [],
            "skipped": [],
        }
    )
    unexpected_errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "migration_run_id": self.migration_run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "db_url_host": self.db_url_host,
            "total_legacy_rows": self.total_legacy_rows,
            "counts": self.counts,
            "archive": {
                "table_name": ARCHIVE_TABLE,
                "created_this_run": self.archive_table_created,
                "already_existed": self.archive_table_already_existed,
                "row_count": self.archive_row_count,
            },
            "samples": self.samples,
            "unexpected_errors": self.unexpected_errors,
        }


# ---------------------------------------------------------------------------
# Archive table
# ---------------------------------------------------------------------------


def ensure_archive_table(cur) -> tuple[bool, bool, int]:
    """
    Create `concierge_knowledge_archive_2026_05_23` if it doesn't exist,
    populated from `concierge_knowledge`. Returns (created, already_existed,
    row_count).

    The archive is the safety net for the DROP migration that follows. It
    holds the same column set as the legacy table plus an
    archived_at timestamp.
    """
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (ARCHIVE_TABLE,),
    )
    existed = cur.fetchone() is not None
    if existed:
        cur.execute(f"SELECT COUNT(*) AS n FROM {ARCHIVE_TABLE}")
        return False, True, int(cur.fetchone()["n"])

    cur.execute(
        f"""
        CREATE TABLE {ARCHIVE_TABLE} AS
        SELECT *, NOW() AS archived_at
        FROM concierge_knowledge
        """
    )
    cur.execute(f"SELECT COUNT(*) AS n FROM {ARCHIVE_TABLE}")
    return True, False, int(cur.fetchone()["n"])


# ---------------------------------------------------------------------------
# Insert helpers
# ---------------------------------------------------------------------------


def build_migration_metadata(
    *,
    legacy_row: dict[str, Any],
    migration_run_id: str,
    migrated_at_iso: str,
) -> dict[str, Any]:
    """The provenance + audit-trail fields stamped on every scoped row
    this script touches."""
    return {
        "migration_provenance": MIGRATION_PROVENANCE,
        "legacy_property_external_id": legacy_row.get("property_external_id"),
        "legacy_id": str(legacy_row.get("knowledge_id")),
        "legacy_category": legacy_row.get("category"),
        "legacy_source": legacy_row.get("source"),
        "legacy_confidence": (
            float(legacy_row["confidence"])
            if legacy_row.get("confidence") is not None
            else None
        ),
        "legacy_created_at": (
            legacy_row["created_at"].isoformat()
            if legacy_row.get("created_at") is not None
            else None
        ),
        "legacy_updated_at": (
            legacy_row["updated_at"].isoformat()
            if legacy_row.get("updated_at") is not None
            else None
        ),
        "legacy_valid_from": (
            legacy_row["valid_from"].isoformat()
            if legacy_row.get("valid_from") is not None
            else None
        ),
        "legacy_valid_until": (
            legacy_row["valid_until"].isoformat()
            if legacy_row.get("valid_until") is not None
            else None
        ),
        "migration_run_id": migration_run_id,
        "migrated_at": migrated_at_iso,
    }


def insert_new_scoped_row(
    cur,
    *,
    legacy_row: dict[str, Any],
    scope_target_id: str,
    question_text: str,
    question_key: str,
    answer_text: str,
    metadata: dict[str, Any],
) -> str:
    """Insert a brand-new row into `concierge_scoped_knowledge` and write
    the history bookkeeping row. Returns the new knowledge_entry_id."""
    cur.execute(
        """
        INSERT INTO concierge_scoped_knowledge (
            tenant_id, scope_type, scope_target_id, topic_id,
            question_text, question_key, answer_text,
            tags, source, metadata,
            created_by_user_id,
            created_at, updated_at,
            is_active, version
        ) VALUES (
            %s::uuid, 'property', %s::uuid, NULL,
            %s, %s, %s,
            '[]'::jsonb, %s, %s::jsonb,
            NULL,
            COALESCE(%s, NOW()), COALESCE(%s, NOW()),
            TRUE, 1
        )
        RETURNING knowledge_entry_id::text
        """,
        (
            str(legacy_row["tenant_id"]),
            scope_target_id,
            question_text,
            question_key,
            answer_text,
            MIGRATION_PROVENANCE,
            Json(metadata),
            legacy_row.get("created_at"),
            legacy_row.get("updated_at"),
        ),
    )
    knowledge_entry_id = cur.fetchone()["knowledge_entry_id"]
    cur.execute(
        """
        INSERT INTO concierge_scoped_knowledge_history (
            knowledge_entry_id, tenant_id, version,
            previous_question_text, previous_answer_text, previous_metadata,
            changed_by_user_id, change_type, changed_at
        ) VALUES (
            %s::uuid, %s::uuid, 1,
            NULL, NULL, NULL,
            NULL, 'created', NOW()
        )
        """,
        (knowledge_entry_id, str(legacy_row["tenant_id"])),
    )
    return knowledge_entry_id


def update_scoped_row_legacy_wins(
    cur,
    *,
    legacy_row: dict[str, Any],
    existing: dict[str, Any],
    new_question_text: str,
    new_answer_text: str,
    metadata: dict[str, Any],
) -> None:
    """A conflict was resolved in favor of the legacy row. Update the
    existing scoped row's answer and stamp the conflict resolution in
    metadata. The previous answer goes into history."""
    existing_metadata = existing.get("metadata") or {}
    if isinstance(existing_metadata, str):
        try:
            existing_metadata = json.loads(existing_metadata)
        except Exception:
            existing_metadata = {}
    if not isinstance(existing_metadata, dict):
        existing_metadata = {}
    previous_version = int(existing_metadata.get("version") or 1)

    # Compose new metadata: keep prior provenance, layer this script's
    # provenance on top, record the conflict resolution.
    merged_metadata = dict(existing_metadata)
    merged_metadata.update(metadata)
    merged_metadata["conflict_resolution"] = {
        "resolved_by": "retire_concierge_knowledge_script",
        "winner": "legacy",
        "resolved_at": metadata.get("migrated_at"),
        "previous_answer_text": existing.get("answer_text"),
        "previous_source": existing.get("source"),
    }
    merged_metadata["version"] = previous_version + 1

    cur.execute(
        """
        INSERT INTO concierge_scoped_knowledge_history (
            knowledge_entry_id, tenant_id, version,
            previous_question_text, previous_answer_text, previous_metadata,
            changed_by_user_id, change_type, changed_at
        ) VALUES (
            %s::uuid, %s::uuid, %s,
            NULL, %s, %s::jsonb,
            NULL, 'updated', NOW()
        )
        """,
        (
            existing["knowledge_entry_id"],
            existing["tenant_id"],
            previous_version,
            existing.get("answer_text"),
            Json(existing_metadata),
        ),
    )
    cur.execute(
        """
        UPDATE concierge_scoped_knowledge
        SET answer_text = %s,
            question_text = %s,
            source = %s,
            metadata = %s::jsonb,
            updated_at = NOW(),
            version = %s
        WHERE knowledge_entry_id = %s::uuid
        """,
        (
            new_answer_text,
            new_question_text,
            MIGRATION_PROVENANCE,
            Json(merged_metadata),
            previous_version + 1,
            existing["knowledge_entry_id"],
        ),
    )


def annotate_scoped_row_scoped_wins(
    cur,
    *,
    existing: dict[str, Any],
    legacy_row: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    """The scoped row's answer wins. Don't change the answer, but log the
    conflict and stamp legacy provenance so a future audit can find the
    legacy row that was overridden."""
    existing_metadata = existing.get("metadata") or {}
    if isinstance(existing_metadata, str):
        try:
            existing_metadata = json.loads(existing_metadata)
        except Exception:
            existing_metadata = {}
    if not isinstance(existing_metadata, dict):
        existing_metadata = {}

    merged_metadata = dict(existing_metadata)
    legacy_provenance_log = list(merged_metadata.get("legacy_overridden_rows") or [])
    legacy_provenance_log.append(
        {
            "legacy_id": str(legacy_row["knowledge_id"]),
            "legacy_property_external_id": legacy_row.get("property_external_id"),
            "legacy_answer_text": _normalize_text(legacy_row.get("answer")),
            "legacy_updated_at": (
                legacy_row["updated_at"].isoformat()
                if legacy_row.get("updated_at") is not None
                else None
            ),
            "resolution": "scoped_kept",
            "resolved_at": metadata.get("migrated_at"),
            "migration_run_id": metadata.get("migration_run_id"),
        }
    )
    merged_metadata["legacy_overridden_rows"] = legacy_provenance_log

    cur.execute(
        """
        UPDATE concierge_scoped_knowledge
        SET metadata = %s::jsonb
        WHERE knowledge_entry_id = %s::uuid
        """,
        (Json(merged_metadata), existing["knowledge_entry_id"]),
    )


# ---------------------------------------------------------------------------
# Conflict resolution policy
# ---------------------------------------------------------------------------


def pick_conflict_winner(
    legacy_row: dict[str, Any],
    existing_scoped_row: dict[str, Any],
) -> str:
    """
    Choose 'legacy' or 'scoped' for a row where both sides have a non-empty
    answer for the same question_key under the same property scope.

    Policy: the more recent updated_at wins. Ties go to scoped because
    scoped is the brain-owned source of truth.

    If either side is missing updated_at, scoped wins (the same default).
    """
    legacy_ts = legacy_row.get("updated_at")
    scoped_ts = existing_scoped_row.get("updated_at")
    if legacy_ts is None or scoped_ts is None:
        return "scoped"
    return "legacy" if legacy_ts > scoped_ts else "scoped"


# ---------------------------------------------------------------------------
# Main per-row processor
# ---------------------------------------------------------------------------


def process_row(
    cur,
    *,
    legacy_row: dict[str, Any],
    property_map: dict[tuple[str, str], str],
    scoped_index: dict[tuple[str, str, str], dict[str, Any]],
    within_run_keys: set[tuple[str, str, str]],
    migration_run_id: str,
    migrated_at_iso: str,
    dry_run: bool,
) -> RowOutcome:
    knowledge_id = str(legacy_row.get("knowledge_id"))
    tenant_id = legacy_row.get("tenant_id")
    if tenant_id is None:
        return RowOutcome(
            knowledge_id=knowledge_id,
            tenant_id=None,
            property_external_id=legacy_row.get("property_external_id"),
            scope_target_id=None,
            question_key=None,
            question_text=None,
            outcome="skipped",
            reason="null_tenant",
        )

    tenant_id_str = str(tenant_id)
    property_external_id = _normalize_text(legacy_row.get("property_external_id"))
    scope_target_id = resolve_property_id(property_map, tenant_id_str, property_external_id)

    if not scope_target_id:
        return RowOutcome(
            knowledge_id=knowledge_id,
            tenant_id=tenant_id_str,
            property_external_id=property_external_id or None,
            scope_target_id=None,
            question_key=None,
            question_text=None,
            outcome="skipped",
            reason="unresolvable_property",
        )

    is_active = legacy_row.get("is_active", True)
    if is_active is False:
        # Inactive legacy rows aren't migrated. They're preserved in the
        # archive table, but they shouldn't leak into the live brain KB.
        return RowOutcome(
            knowledge_id=knowledge_id,
            tenant_id=tenant_id_str,
            property_external_id=property_external_id or None,
            scope_target_id=scope_target_id,
            question_key=None,
            question_text=None,
            outcome="skipped",
            reason="inactive_row",
        )

    question_text = _normalize_text(legacy_row.get("question"))
    answer_text = _normalize_text(legacy_row.get("answer"))
    if not question_text or not answer_text:
        return RowOutcome(
            knowledge_id=knowledge_id,
            tenant_id=tenant_id_str,
            property_external_id=property_external_id or None,
            scope_target_id=scope_target_id,
            question_key=None,
            question_text=question_text or None,
            outcome="skipped",
            reason="empty_content",
        )

    question_key = compute_question_key(question_text)

    # Within-run dedupe: two legacy rows with the same key under the
    # same property would otherwise try to insert twice and trip the
    # uq_scoped_knowledge_tenant_scope_question_key constraint.
    run_key = (tenant_id_str, scope_target_id, question_key)
    if run_key in within_run_keys:
        return RowOutcome(
            knowledge_id=knowledge_id,
            tenant_id=tenant_id_str,
            property_external_id=property_external_id or None,
            scope_target_id=scope_target_id,
            question_key=question_key,
            question_text=question_text,
            outcome="skipped",
            reason="within_run_duplicate",
        )

    metadata = build_migration_metadata(
        legacy_row=legacy_row,
        migration_run_id=migration_run_id,
        migrated_at_iso=migrated_at_iso,
    )

    existing = scoped_index.get(run_key)
    if existing is None:
        # MIGRATE: no existing scoped row for this key under this scope.
        if not dry_run:
            new_id = insert_new_scoped_row(
                cur,
                legacy_row=legacy_row,
                scope_target_id=scope_target_id,
                question_text=question_text,
                question_key=question_key,
                answer_text=answer_text,
                metadata=metadata,
            )
            # Add to the in-memory index so subsequent rows in this run
            # see it as already-present rather than trying to insert again.
            scoped_index[run_key] = {
                "knowledge_entry_id": new_id,
                "tenant_id": tenant_id_str,
                "scope_type": "property",
                "scope_target_id": scope_target_id,
                "question_key": question_key,
                "answer_text": answer_text,
                "source": MIGRATION_PROVENANCE,
                "metadata": metadata,
                "updated_at": legacy_row.get("updated_at"),
            }
        within_run_keys.add(run_key)
        return RowOutcome(
            knowledge_id=knowledge_id,
            tenant_id=tenant_id_str,
            property_external_id=property_external_id or None,
            scope_target_id=scope_target_id,
            question_key=question_key,
            question_text=question_text,
            outcome="migrated",
        )

    existing_answer = _normalize_text(existing.get("answer_text"))
    if existing_answer == answer_text:
        # MIRRORED: answer text matches exactly. No write needed.
        within_run_keys.add(run_key)
        return RowOutcome(
            knowledge_id=knowledge_id,
            tenant_id=tenant_id_str,
            property_external_id=property_external_id or None,
            scope_target_id=scope_target_id,
            question_key=question_key,
            question_text=question_text,
            outcome="mirrored",
        )

    # CONFLICT: same key + scope, different answer. Pick a winner.
    winner = pick_conflict_winner(legacy_row, existing)
    if not dry_run:
        if winner == "legacy":
            update_scoped_row_legacy_wins(
                cur,
                legacy_row=legacy_row,
                existing=existing,
                new_question_text=question_text,
                new_answer_text=answer_text,
                metadata=metadata,
            )
            existing["answer_text"] = answer_text
            existing["source"] = MIGRATION_PROVENANCE
            existing["updated_at"] = legacy_row.get("updated_at")
        else:
            annotate_scoped_row_scoped_wins(
                cur,
                existing=existing,
                legacy_row=legacy_row,
                metadata=metadata,
            )
    within_run_keys.add(run_key)
    return RowOutcome(
        knowledge_id=knowledge_id,
        tenant_id=tenant_id_str,
        property_external_id=property_external_id or None,
        scope_target_id=scope_target_id,
        question_key=question_key,
        question_text=question_text,
        outcome="conflict_resolved",
        conflict_winner=winner,
        conflict_existing_entry_id=existing.get("knowledge_entry_id"),
    )


# ---------------------------------------------------------------------------
# Sampling helper for the report
# ---------------------------------------------------------------------------


def collect_sample(report: RunReport, outcome: RowOutcome) -> None:
    """Capture up to 10 of each outcome type in the report for spot-checking."""
    def _sample_dict() -> dict[str, Any]:
        return {
            "knowledge_id": outcome.knowledge_id,
            "tenant_id": outcome.tenant_id,
            "property_external_id": outcome.property_external_id,
            "scope_target_id": outcome.scope_target_id,
            "question_key": outcome.question_key,
            "question_text": outcome.question_text,
            "outcome": outcome.outcome,
            "reason": outcome.reason,
            "conflict_winner": outcome.conflict_winner,
            "conflict_existing_entry_id": outcome.conflict_existing_entry_id,
        }

    if outcome.outcome == "mirrored":
        if len(report.samples["mirrored"]) < 10:
            report.samples["mirrored"].append(_sample_dict())
    elif outcome.outcome == "migrated":
        if len(report.samples["migrated"]) < 10:
            report.samples["migrated"].append(_sample_dict())
    elif outcome.outcome == "conflict_resolved":
        # Keep conflicts comprehensive — they're the rows most likely to
        # need eyeballing. Cap at 50 to bound the report size.
        if len(report.samples["conflicts"]) < 50:
            report.samples["conflicts"].append(_sample_dict())
    elif outcome.outcome == "skipped":
        if len(report.samples["skipped"]) < 10:
            report.samples["skipped"].append(_sample_dict())


# ---------------------------------------------------------------------------
# Run orchestrator
# ---------------------------------------------------------------------------


def run(*, dry_run: bool, skip_archive: bool) -> RunReport:
    started_at = datetime.now(timezone.utc)
    migration_run_id = str(uuid.uuid4())
    migrated_at_iso = started_at.isoformat()

    db_url = _db_url()
    # Extract the host fragment for the report (without leaking the password).
    host_match = re.search(r"@([^/]+)/", db_url)
    db_host = host_match.group(1) if host_match else "unknown"

    report = RunReport(
        dry_run=dry_run,
        migration_run_id=migration_run_id,
        started_at=migrated_at_iso,
        db_url_host=db_host,
    )

    conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            # Archive first. If something explodes mid-migration, at least
            # the snapshot is in place.
            if skip_archive:
                report.archive_table_created = False
                report.archive_table_already_existed = False
                report.archive_row_count = 0
            else:
                if dry_run:
                    # In dry-run mode, report whether the archive table
                    # already exists, but don't create it.
                    cur.execute(
                        """
                        SELECT 1
                        FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = %s
                        """,
                        (ARCHIVE_TABLE,),
                    )
                    report.archive_table_already_existed = cur.fetchone() is not None
                    report.archive_table_created = False
                    if report.archive_table_already_existed:
                        cur.execute(f"SELECT COUNT(*) AS n FROM {ARCHIVE_TABLE}")
                        report.archive_row_count = int(cur.fetchone()["n"])
                else:
                    created, existed, count = ensure_archive_table(cur)
                    report.archive_table_created = created
                    report.archive_table_already_existed = existed
                    report.archive_row_count = count

            # Build property map (tenant, external_id) -> property_id.
            property_map = load_property_map(cur)

            # Build scoped parity index keyed by (tenant, scope_target_id,
            # question_key). This lets each per-row check be O(1).
            scoped_index = load_existing_scoped_index(cur)

            # Pull every legacy row.
            legacy_rows = load_legacy_rows(cur)
            report.total_legacy_rows = len(legacy_rows)

            within_run_keys: set[tuple[str, str, str]] = set()

            for legacy_row in legacy_rows:
                try:
                    outcome = process_row(
                        cur,
                        legacy_row=legacy_row,
                        property_map=property_map,
                        scoped_index=scoped_index,
                        within_run_keys=within_run_keys,
                        migration_run_id=migration_run_id,
                        migrated_at_iso=migrated_at_iso,
                        dry_run=dry_run,
                    )
                except Exception as exc:  # noqa: BLE001
                    report.unexpected_errors.append(
                        {
                            "knowledge_id": str(legacy_row.get("knowledge_id")),
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        }
                    )
                    continue

                if outcome.outcome == "mirrored":
                    report.counts["mirrored"] += 1
                elif outcome.outcome == "migrated":
                    report.counts["migrated"] += 1
                elif outcome.outcome == "conflict_resolved":
                    if outcome.conflict_winner == "legacy":
                        report.counts["conflict_resolved_legacy_wins"] += 1
                    else:
                        report.counts["conflict_resolved_scoped_wins"] += 1
                elif outcome.outcome == "skipped":
                    key = f"skipped_{outcome.reason or 'unknown'}"
                    report.counts[key] = report.counts.get(key, 0) + 1

                collect_sample(report, outcome)

            if dry_run:
                conn.rollback()
            else:
                conn.commit()
    finally:
        conn.close()

    report.finished_at = datetime.now(timezone.utc).isoformat()
    return report


# ---------------------------------------------------------------------------
# Report writing
# ---------------------------------------------------------------------------


def write_report(report: RunReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = report.started_at.replace(":", "").replace("-", "").replace(".", "")
    suffix = "_dryrun" if report.dry_run else ""
    filename = f"retire_concierge_knowledge_{timestamp}{suffix}.json"
    output_path = output_dir / filename
    output_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return output_path


# ---------------------------------------------------------------------------
# Sanity assertions (run after a non-dry-run to confirm the gate is clear)
# ---------------------------------------------------------------------------


def post_run_assertions(report: RunReport) -> list[str]:
    """
    Hard checks that must pass before the DROP migration runs. Returns
    a list of human-readable failure messages; empty list means clear.
    """
    failures: list[str] = []
    if report.dry_run:
        # Nothing to assert against a dry run; the script wasn't allowed
        # to write anything.
        return failures

    if report.unexpected_errors:
        failures.append(
            f"{len(report.unexpected_errors)} legacy row(s) raised unexpected errors. "
            "Review report.unexpected_errors before proceeding."
        )

    expected = report.total_legacy_rows
    accounted = sum(report.counts.values())
    if expected != accounted:
        failures.append(
            f"Row accounting mismatch: scanned={expected}, accounted={accounted}. "
            "Every legacy row should land in exactly one outcome bucket."
        )

    if not report.archive_table_created and not report.archive_table_already_existed:
        failures.append(
            f"Archive table {ARCHIVE_TABLE!r} was neither created nor verified to "
            "already exist. Refusing to clear the drop gate without a snapshot."
        )

    if report.archive_table_created and report.archive_row_count != report.total_legacy_rows:
        failures.append(
            f"Archive row count ({report.archive_row_count}) does not match scanned "
            f"legacy rows ({report.total_legacy_rows}). The snapshot is incomplete."
        )

    return failures


def post_run_warnings(report: RunReport) -> list[str]:
    """
    Loud-but-non-blocking findings to print after an execute run. These
    do not stop the drop gate from clearing because the archived legacy
    table remains the recovery path.
    """
    warnings: list[str] = []
    if report.dry_run:
        return warnings

    skipped_unresolvable = report.counts.get("skipped_unresolvable_property", 0)
    if skipped_unresolvable > 0:
        warnings.append(
            f"{skipped_unresolvable} legacy row(s) skipped as unresolvable_property. "
            "These rows were archived but not migrated to scoped. If any of those "
            "property codes should still be live, fix the mapping before relying "
            "on the archive as the only recovery path."
        )

    skipped_null_tenant = report.counts.get("skipped_null_tenant", 0)
    if skipped_null_tenant > 0:
        warnings.append(
            f"{skipped_null_tenant} legacy row(s) had NULL tenant_id and were archived "
            "without migration."
        )

    return warnings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Final pre-drop gate for the legacy concierge_knowledge table. "
            "Performs row-level parity, conflict resolution, provenance "
            "tagging, and archive snapshot. Does NOT drop the table."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and report without writing any rows or creating the archive.",
    )
    group.add_argument(
        "--execute",
        action="store_true",
        help="Apply changes: archive, migrate, resolve conflicts, tag provenance.",
    )
    parser.add_argument(
        "--skip-archive",
        action="store_true",
        help=(
            "Skip the archive table creation step. Only use this if the "
            "archive already exists from a previous run and you are sure "
            "its contents are still authoritative."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=(
            "Directory to write the JSON report into. "
            f"Defaults to {DEFAULT_OUTPUT_DIR}."
        ),
    )
    args = parser.parse_args()

    report = run(dry_run=args.dry_run, skip_archive=args.skip_archive)
    output_path = write_report(report, Path(args.output_dir))

    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    print(f"\nReport written to: {output_path}", file=sys.stderr)

    if args.execute:
        warnings = post_run_warnings(report)
        for warning in warnings:
            print(f"WARNING: {warning}", file=sys.stderr)

        failures = post_run_assertions(report)
        if failures:
            print(
                "\nPRE-DROP GATE NOT CLEAR. The following issues must be resolved "
                "before running the DROP migration:",
                file=sys.stderr,
            )
            for msg in failures:
                print(f"  - {msg}", file=sys.stderr)
            return 1
        print(
            "\nPRE-DROP GATE CLEAR. Safe to proceed with the Alembic drop "
            f"migration. Migration run id: {report.migration_run_id}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
