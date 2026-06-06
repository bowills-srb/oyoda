# Brief — Gap 2: Promote confidence / verified-date to queryable columns

For Claude Code. Build-ready. Read OYVODA_AUDIT_KNOWLEDGE_INGESTION_LAYER.md and
OYVODA_BRIEF_GAP1_GROUP_SCOPE_STAGING.md (9916f13, landed) first. This promotes provenance
signals from metadata JSONB to first-class columns so they're queryable and power the
"source / confidence / verified" provenance UI. The migration is trivial; the WRITE SEMANTICS
are the real content — get those right or the columns lie.

## Migration (anchored — head confirmed via alembic heads)
Current head: `091_operator_property_autonomy_snapshots`. New migration
`092_scoped_knowledge_provenance_columns`, down_revision = '091_operator_property_autonomy_snapshots'.
Add to concierge_scoped_knowledge:
- `confidence NUMERIC(4,3)` NULL (nullable — see semantics; not every entry has a confidence)
- `last_verified_at TIMESTAMPTZ` NULL
- `verified_by_user_id UUID` NULL
Reversible (downgrade drops the three columns). Backfill in the same migration:
- `UPDATE concierge_scoped_knowledge SET confidence = (metadata->>'confidence')::numeric
   WHERE metadata ? 'confidence' AND confidence IS NULL` (guard the cast; skip non-numeric).
- Do NOT backfill last_verified_at/verified_by from metadata unless a real human-verification
  signal exists there (it likely does not) — leave NULL. NULL honestly means "not human-verified."

## WRITE SEMANTICS (the real content — keep the honesty discipline)
The distinction that matters: **confidence != verified.** A fact the system extracted at
confidence 0.8 is PROPOSED, not VERIFIED. It becomes verified when a HUMAN approves it. Don't let
a column imply human verification that didn't happen.

### confidence
- Written on every promotion. In staging_service `_promote_candidate` (fact path), the candidate
  carries `confidence` — pass it into write_scoped_knowledge so it lands in the column (not just
  metadata). Extend write_scoped_knowledge to accept and persist `confidence`.
- Manual/operator-authored entries (dashboard create) with no extraction confidence: NULL or a
  convention (e.g. operator-entered facts are inherently trusted — decide: NULL, or 1.0 with
  verified set since a human wrote it). RECOMMENDATION: operator-authored = confidence NULL but
  verified_at/by SET (a human wrote it = verified, even without a numeric confidence). Document the choice.

### last_verified_at / verified_by_user_id  (HUMAN verification only)
- Set these ONLY when a human approves/edits a candidate or authors/confirms an entry:
  - staging_service `approve_candidate` (NOT `auto_promote_eligible`): the reviewer is the verifier.
    When a human approves, the promoted scoped-knowledge entry gets last_verified_at=NOW(),
    verified_by_user_id=reviewer.
  - AUTO-PROMOTED candidates (auto_promote_eligible, the high-confidence deterministic/pms path):
    do NOT set verified_at/by. They have high `confidence` but NO human verified them. They are
    "system-confident, unverified." This is the honest, useful distinction — it lets the operator
    later query "show me auto-promoted-but-never-human-checked facts."
  - operator dashboard create/update (dashboard_kb_service): a human authored it -> set verified_at=NOW(),
    verified_by=that user.
- write_scoped_knowledge gains optional verified_at/verified_by params; promotion passes them per
  the above (set on human approve, omit on auto-promote).

## Why this shape is useful (the queries it enables)
- "Facts to review": WHERE verified_at IS NULL (auto-promoted or extraction-staged, never human-checked).
- "Low-confidence facts": WHERE confidence < 0.7.
- Provenance UI per fact: source (exists) + confidence (now column) + verified_at/by (now column) +
  version/history (exists). The full "click to see where this came from and whether a human checked it."

## History table
concierge_scoped_knowledge_history already snapshots metadata. The new columns live on the main
table; history continues to capture metadata. OPTIONAL: if you want verification changes in history,
note it — but not required for this brick. Don't over-build.

## Scope guards
- Migration anchored on 091 (confirmed head). If alembic heads disagrees at apply time, STOP and reconcile.
- Backfill confidence only; leave verified_* NULL (no fake verification history).
- The confidence/verified columns are ADDITIVE — metadata can keep its copies; the columns are the
  queryable source of truth going forward. Don't remove metadata writes (other code may read them).
- Do NOT change read-side inheritance or the brain. This is write-path + schema only.
- asyncpg can't reach Postgres in sandbox; integration tests skip or run outside sandbox.

## Done when
- Migration 092 adds the three columns, reversible, applied to head; confidence backfilled from metadata.
- write_scoped_knowledge persists confidence; sets verified_at/by when a human approves/authors, leaves
  them NULL on auto-promotion.
- staging approve_candidate (human) sets verified_*; auto_promote_eligible does NOT.
- dashboard create/update sets verified_* (human-authored).
- Unit tests: human-approved entry has verified_at set; auto-promoted entry has confidence but NULL
  verified_at; low-confidence query works; backfill correctness.
- Commit SHA. Note: enables provenance UI + "unverified/low-confidence" review queries; prerequisite
  context for Gap 4 (proactive surfacing can flag low-confidence/unverified group facts too).
