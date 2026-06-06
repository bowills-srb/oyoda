# Brief — Autonomy Snapshot Job (autonomy backend, brick 1 of N)

For Claude Code. Build-ready. Read docs/architecture/OYVODA_MASTER_ROADMAP.md
(DOMAIN-AUTONOMY v1 section) first. This is the FIRST autonomy brick and it is
EXECUTION, not a judgment call — the one piece with a real calendar cost: history
cannot be backfilled, so the capture must start now even though the trend is empty.

## Scope clarification (important — read before building)

"Snapshot job" means: capture the PORTFOLIO-LEVEL directional autonomy posture, once per
tenant per day, append-only, from tenant-aggregate inputs THAT ALREADY EXIST. It does NOT
mean the per-property/per-domain score matrix — that needs a computation layer that does
not exist yet and is a SEPARATE later brick. Conflating them is the trap. This brick:
- captures a portfolio score + per-domain bands daily, so the trend starts accumulating;
- uses only aggregate inputs already queryable today;
- is decoupled from learning (behavior weight = neutral).

The per-property/per-domain computation layer is the NEXT brick. Do not build it here.

## The v1 score (directional, NOT scientific — honesty discipline applies)

Per the roadmap: a directional posture score, communicated as posture not precision.
Portfolio-level v1 weighting (tunable later against real Beach Habitats numbers — do NOT
agonize over exact weights now, use these as the starting default and make them named
constants so they're easy to tune):
- **Readiness component** (knowledge coverage / gaps): from existing aggregate KB-entry and
  unresolved-gap counts vs property count.
- **Escalation-pressure component**: from open vs resolved escalation counts (derivable today
  via concierge_escalations + concierge_guest_sessions).
- **Behavior component**: NEUTRAL. Deliberately decoupled from the learning redesign (which is
  on hold). Set to a neutral constant; light it up later when learning lands. This is what lets
  autonomy ship WITHOUT the learning decision.

Per-domain bands (Inquiry / Guest Ops / Maintenance / Turnover): for v1, store all four but
only Inquiry is "computed"; Guest Ops = Developing; Maintenance / Turnover = Emerging
(BAND WORDS, never fabricated numbers — same discipline as the Home hero placeholder and the
Property Readiness coverage labels). Store the band word, not a fake percentage.

Keep the score honest: it's a blend of real aggregate signals, communicated as a directional
posture. Do not present false precision.

## Storage — mirror the read-model pattern, but APPEND-ONLY by date

The existing pattern (operator_dashboard_read_models) is `(tenant_id, summary_json jsonb,
refreshed_at)` with `ON CONFLICT (tenant_id) DO UPDATE` — ONE current row per tenant. The
snapshot table is the OPPOSITE: append-only history, one row per tenant per snapshot_date.

New Alembic migration (follow the existing migration conventions — check the latest revision
number; 090 was the last learning one, find current head). Create:
```
operator_autonomy_snapshots (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null,
  snapshot_date   date not null,
  portfolio_score numeric,          -- the directional v1 score (0..1 or 0..100, pick one, document)
  domain_bands    jsonb not null,   -- { inquiry: {...}, guest_ops: "Developing", maintenance: "Emerging", ... }
  components       jsonb not null,   -- { readiness: x, escalation: y, behavior: "neutral" } for transparency/tuning
  created_at      timestamptz not null default now(),
  UNIQUE (tenant_id, snapshot_date) -- idempotent per-day reruns
)
```
ON CONFLICT (tenant_id, snapshot_date) DO UPDATE (so a re-run same day overwrites that day,
but days accumulate). Index (tenant_id, snapshot_date) for the trend query.
COMMENT ON COLUMN tenant_id: note it stores operator_accounts.tenant_id (the canonical UUID).

## Tenant-key invariant (do NOT get this wrong — silent zero-rows otherwise)
Per-table, verified in dashboard_summary_service:
- `pre_booking_inquiries` keys on **company_id = CAST(:tid AS uuid)** (company_id holds the
  TENANT_ID value — misleading name).
- `concierge_*` tables (sessions, escalations, knowledge_gaps) key on **tenant_id**.
Use the right column per table or queries silently return zero.

## The job — follow the Celery beat pattern (precedent exists)
Add a task in app/workers/tasks.py and a beat entry in app/workers/celery_app.py, modeled on
the existing `rebuild-platform-intelligence` nightly job (crontab(hour=3, minute=0)) — same
shape: nightly, aggregate, store. Suggested: `snapshot_autonomy_all_operators` nightly (pick an
hour not already congested — 3am has platform-intelligence; try hour=2 or hour=6). Route to the
`operations` or `concierge` queue consistent with siblings.
- Iterate active tenants, compute the portfolio score + bands per tenant, upsert one row per
  tenant for today's date.
- Use the same defensive conventions as dashboard_summary_service: table-exists guards,
  fail-soft per-tenant (one tenant's failure must not abort the batch), rollback on error.
- Put the SCORING logic in a dedicated service (e.g. app/services/operator/autonomy_score_service.py)
  with the weights as named constants, so the later per-property/per-domain brick and the tuning
  pass reuse it. The Celery task just orchestrates; the service computes.

## ABSOLUTE scope guards
- PORTFOLIO-level only. NO per-property, NO per-domain computation (Inquiry's "computed" band can
  be a simple portfolio-level inquiry signal for v1; the real per-property matrix is the next brick).
- Behavior component = neutral constant. Do NOT wire in operator_draft_events / learning signals
  (that's gated on the learning redesign).
- NO frontend changes. The Home hero swap and Property Readiness A-swap are LATER bricks that
  consume this data — not part of this one.
- NO fabricated numbers for immature domains — band words only.
- Migration must be reversible (downgrade drops the table). Match existing Alembic style.
- asyncpg can't reach Postgres in sandboxed test envs — integration tests skip or run outside
  sandbox (per established discipline).

## Done when
- Migration creates operator_autonomy_snapshots (append-only by date, unique per tenant+date,
  reversible). Applied to head.
- autonomy_score_service computes a directional portfolio score + domain bands from real aggregate
  inputs, weights as named constants, behavior=neutral.
- A nightly Celery task snapshots all active tenants, fail-soft per tenant, idempotent per day.
- Verify: run the task once against Beach Habitats; confirm a row lands with a sane score and
  bands (Inquiry computed, others Emerging/Developing). The trend is a single point — that's
  expected; the value is that capture has STARTED.
- tsc N/A (backend). No frontend change. Commit SHA recorded.
- Roadmap DOMAIN-AUTONOMY section updated: snapshot job DONE, computation layer NEXT.
