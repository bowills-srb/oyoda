## Phase 4.3-O Production Error Audit

Date: 2026-05-18

### InFailedSQLTransactionError

- Recent Railway worker log sample did not surface fresh `InFailedSQLTransactionError` lines in the queried window.
- Historical context remains real:
  - `docs/INCIDENT_2026_05_05_DROPPED_DRAFTS.md` documented poisoned-session failures in the pre-booking pipeline.
  - The cleanup target for this phase is therefore preventive: make fail-soft DB handlers roll back before returning so future upstream DB faults do not leave shared sessions aborted.
- Handlers hardened in this phase:
  - `app/services/integrations/email_dispatch.py`
  - `app/services/integrations/reservation_aware_routing.py`
  - `app/services/agents/escalation_handoff_agent.py`
  - `app/services/agents/pms_sync_agent.py`
  - `app/services/agents/knowledge_curator_agent.py`
  - shared helper extracted to `app/db/session_safety.py`

### knowledge_gaps References

- Production schema check:
  - present: `concierge_knowledge_gaps`
  - absent: `knowledge_gaps`
  - absent: `kb_gaps`
  - absent: `operator_gap_settings`
  - absent: `knowledge_gap_drafts`
- Code paths found querying stale names:
  - `app/services/agents/knowledge_curator_agent.py`
  - `app/services/intelligence/insight_engine.py`
  - `app/services/concierge/kb_gap_manager.py` still references legacy `kb_gaps` / `operator_gap_settings`
- Resolution applied in this phase:
  - `knowledge_curator_agent` gap reads and resolve writes now target `concierge_knowledge_gaps`
  - `insight_engine` event-correlation query now targets `concierge_knowledge_gaps`
- Remaining note:
  - `kb_gap_manager.py` is still a legacy branch over absent tables and should be retired or remapped in a follow-up phase if that functionality is reactivated.

### asyncpg / PgBouncer Prepared Statements

- Live Railway worker errors observed:
  - `asyncpg.exceptions.DuplicatePreparedStatementError`
  - seen in:
    - inbox polling (`[InboxPoll] poll_all failed`)
    - escalation SLA checks (`[EscalationHandoff] _load_open_tickets error`)
    - PMS sync (`[PMSSync] Failed to load stale sessions`)
- Example statements in failure text:
  - `select pg_catalog.version()`
  - `select current_schema()`
- Root cause:
  - the app was already disabling statement caching for Supabase/PgBouncer, but the code only enabled unique prepared statement names when `asyncpg.connect(...)` exposed `prepared_statement_name_func`.
  - SQLAlchemy's asyncpg dialect supports `prepared_statement_name_func` independently, so the gate was too conservative and left the safe path disabled.
- Resolution applied in this phase:
  - `app/core/db_connect.py` now keys support detection off SQLAlchemy's asyncpg adapter, not raw `asyncpg.connect`.
  - PgBouncer URLs now consistently receive a unique `prepared_statement_name_func` when the installed SQLAlchemy dialect supports it.

### Handler Mapping Summary

| File | Scope | Problem | Fix |
|------|-------|---------|-----|
| `app/services/integrations/email_dispatch.py` | thread history resolution | fail-soft DB path rolled back inline ad hoc | switched to shared `safe_rollback` |
| `app/services/integrations/reservation_aware_routing.py` | cached booking + operator settings lookups | DB exceptions returned defaults without shared cleanup helper | added `safe_rollback` on DB exceptions |
| `app/services/agents/escalation_handoff_agent.py` | ticket loaders / breach stamping | DB exceptions returned defaults without rollback | added `safe_rollback` |
| `app/services/agents/pms_sync_agent.py` | stale session loaders | DB exceptions returned defaults without rollback | added `safe_rollback` |
| `app/services/agents/knowledge_curator_agent.py` | gap loads / draft reads | stale table names and swallowed DB errors | remapped to canonical table and added rollback cleanup |

### Verification

- Unit coverage added for rollback-on-error behavior and the PgBouncer config branch.
- Post-deploy verification still needed:
  - watch Railway worker logs for drop in `DuplicatePreparedStatementError`
  - verify stale `knowledge_gaps` error lines disappear
  - confirm no meaningful recurrence of poisoned-session fallout
