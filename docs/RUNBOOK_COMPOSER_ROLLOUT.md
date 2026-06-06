# Composer Rollout Runbook

**Scope:** Turning on the LLM composer (Session 12 / Phase C2) for one
tenant at a time, starting with Beach Habitats. This runbook is the
canonical procedure for migration → compare mode → live mode for any
tenant.

**Audience:** Anyone with DB and Railway env-var access.

**Design provenance:** `docs/SESSION_12_COMPOSER_DESIGN.md`,
`docs/IMPLEMENTATION_QUEUE_2026_05_05.md` (Phase C2),
commit `5508c04`.

---

## Background

The LLM composer replaces the brain's string-concatenation fallback
with an Anthropic/Groq/Gemini-backed synthesis step. It is gated by
two independent feature flags:

- `MESSAGING_BRAIN_LLM_COMPOSER` — composer on/off.
- `MESSAGING_BRAIN_LLM_COMPOSER_SHADOW` — when on (and composer is
  also on), composer runs and metadata is persisted but the
  operator-facing draft stays as the concatenation fallback. This
  is **compare mode** — the load-bearing setting for shadow validation.

Both flags default OFF. Both fail-closed: any flag-lookup error
behaves as composer-off / shadow-on respectively, so today's
behavior wins on any flag-system glitch.

The composer is **inbound-only**. Proactive triggers continue to use
concatenation regardless of these flags.

The composer is wired into the brain orchestrator's pipeline. It
runs only when inbound messages route through that orchestrator,
which itself is gated by `MESSAGING_BRAIN_RUNTIME`. If the brain
runtime is off for a tenant, flipping the composer flags has no
runtime effect — the message takes the legacy concierge path and
never reaches the orchestrator's compose step. Step 2 below verifies
runtime before flipping composer flags.

---

## Prerequisites

- Commit `5508c04` or later deployed to the target environment.
- DB access to the Supabase pooler (or local equivalent).
- Railway env-var access for the target deployment.
- Beach Habitats tenant id: `e07980b2-a990-4b24-91d1-c8cb71ab70e1`.
- API keys for at least one composer provider (`ANTHROPIC_API_KEY`,
  `GROQ_API_KEY`, or `GEMINI_API_KEY`/`GOOGLE_API_KEY`) configured
  in the deployment env. Anthropic + Groq are already present in
  Beach Habitats env per the C2 build notes.
- `MESSAGING_BRAIN_RUNTIME = true` for the target tenant. If it is
  off, the composer cannot run regardless of its own flags. Step 2.0
  verifies this and enables it if needed.

---

## Step 1 — Run migration 054

The migration adds six columns to `message_normalizations`. All are
nullable or have defaults, so existing rows are not blocked. The
`composer_notes` column has a JSONB default of `'[]'`.

### Command (from repo root, against the target DB)

```bash
cd /Users/dhuntermckenzie/Downloads/oyvoda
DATABASE_URL=<target-db-url> alembic upgrade 054_message_normalizations_composer_metadata
```

For Beach Habitats production, `DATABASE_URL` points at the Supabase
pooler (`aws-1-us-east-1.pooler.supabase.com:6543`,
user `postgres.mskazxakxowcggxmkmrp`).

### Verification SQL (run against the same DB)

```sql
-- 1. Confirm all six columns exist with the right types.
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'message_normalizations'
  AND column_name LIKE 'composer_%'
ORDER BY column_name;

-- Expected result: six rows.
--   composer_input_tokens     | integer | YES | NULL
--   composer_latency_ms       | integer | YES | NULL
--   composer_notes            | jsonb   | NO  | '[]'::jsonb
--   composer_output_tokens    | integer | YES | NULL
--   composer_response_text    | text    | YES | NULL
--   composer_source           | text    | YES | NULL

-- 2. Confirm the alembic_version table now points at 054.
SELECT version_num FROM alembic_version;

-- Expected: 054_message_normalizations_composer_metadata
```

### Backfill check

Existing `message_normalizations` rows should now have NULL across the
five TEXT/INTEGER composer columns and `'[]'::jsonb` in
`composer_notes`. Confirm:

```sql
SELECT
  COUNT(*) AS total_rows,
  COUNT(*) FILTER (WHERE composer_source IS NULL) AS null_source,
  COUNT(*) FILTER (WHERE composer_notes = '[]'::jsonb) AS empty_notes
FROM message_normalizations;
```

`total_rows == null_source == empty_notes` is the all-clear. If the
table is large and the backfill of `composer_notes` defaults takes
longer than expected, this query is also where you'd see partial
state. Rerun until convergent before proceeding.

---

## Step 2 — Flip flags for Beach Habitats compare mode

Compare mode means: composer **runs** on every inbound message, its
output is **persisted** to the new columns, but the operator continues
to see the concatenation fallback in their inbox. This is how we
validate composer quality before it can affect operators.

### Step 2.0 — Verify brain runtime is on for the tenant

The composer only runs when an inbound message reaches the brain
orchestrator. The orchestrator is itself gated by
`MESSAGING_BRAIN_RUNTIME`. Before flipping composer flags, confirm
runtime is on for the tenant — otherwise compare mode silently does
nothing because the message takes the legacy path.

```sql
-- Read the runtime flag and both composer flags in one shot. The
-- absence of a row means "no per-tenant override, falls back to env
-- default" — which for runtime in production is OFF.
SELECT flag_name, enabled, enabled_at, enabled_by, notes
FROM operator_feature_flags
WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND flag_name IN (
    'messaging_brain_runtime',
    'messaging_brain_llm_composer',
    'messaging_brain_llm_composer_shadow'
  )
ORDER BY flag_name;
```

**What to do with the result:**

- If `messaging_brain_runtime` row shows `enabled = TRUE`: proceed to
  Option A or B below.
- If the row shows `enabled = FALSE` or no row exists at all: enable
  it before flipping composer flags. Use the same Option A / Option B
  shape as below, with `flag_name = 'messaging_brain_runtime'`.

**A note on enabling runtime for a tenant that hasn't used the brain
before:** the brain has its own validation history (the AC-slice
test, every regression run during composer build), and the brain
runtime has been live on Beach Habitats for prior sessions. For a
brand-new tenant, runtime-on is itself a non-trivial change that
deserves its own canary review independent of composer rollout.
Enabling runtime and composer flags simultaneously means a single
inbound message exercises both new code paths at once, which makes
debugging harder if something goes wrong. If a new tenant has never
had brain runtime on, prefer this ordering:

1. Enable `messaging_brain_runtime` only.
2. Watch `message_normalizations` rows accumulate with non-empty
   `route_outcome` values (intent topics like `house_rules`,
   `booking_inquiry`, etc., not `shadow_persisted`). That confirms
   the brain is actually handling messages.
3. Then return to Step 2 and flip the composer flags.

For tenants where runtime is already on (Beach Habitats), skip
straight past this and into Option A/B.

### Option A — Per-tenant via DB (preferred)

Per-tenant flags live in `operator_feature_flags`. Use the typed
helper from `feature_flags.py`:

```python
# Run from a Python REPL in the deployment env, or as a one-shot script.
from app.services.feature_flags import get_feature_flags, FeatureFlag
from app.db.session import get_async_session  # adjust import to match your stack

async def turn_on_compare_mode():
    async with get_async_session() as db:
        flags = get_feature_flags(db=db)
        await flags.set_flag(
            FeatureFlag.MESSAGING_BRAIN_LLM_COMPOSER, True,
            company_id="e07980b2-a990-4b24-91d1-c8cb71ab70e1",
            enabled_by="<your-name>",
            notes="Compare mode start — Beach Habitats canary",
        )
        await flags.set_flag(
            FeatureFlag.MESSAGING_BRAIN_LLM_COMPOSER_SHADOW, True,
            company_id="e07980b2-a990-4b24-91d1-c8cb71ab70e1",
            enabled_by="<your-name>",
            notes="Compare mode start — Beach Habitats canary",
        )
```

### Option B — Direct SQL upsert (when REPL access is awkward)

```sql
-- Composer flag on for Beach Habitats (operator level — covers all properties).
INSERT INTO operator_feature_flags
  (id, company_id, property_code, flag_name, enabled,
   enabled_at, enabled_by, notes, created_at)
VALUES
  (gen_random_uuid(),
   'e07980b2-a990-4b24-91d1-c8cb71ab70e1',
   NULL,
   'messaging_brain_llm_composer',
   TRUE,
   NOW(),
   '<your-name>',
   'Compare mode start — Beach Habitats canary',
   NOW())
ON CONFLICT (company_id, property_code, flag_name)
DO UPDATE SET
  enabled = EXCLUDED.enabled,
  enabled_at = EXCLUDED.enabled_at,
  enabled_by = EXCLUDED.enabled_by,
  notes = EXCLUDED.notes;

-- Shadow flag on for Beach Habitats.
INSERT INTO operator_feature_flags
  (id, company_id, property_code, flag_name, enabled,
   enabled_at, enabled_by, notes, created_at)
VALUES
  (gen_random_uuid(),
   'e07980b2-a990-4b24-91d1-c8cb71ab70e1',
   NULL,
   'messaging_brain_llm_composer_shadow',
   TRUE,
   NOW(),
   '<your-name>',
   'Compare mode start — Beach Habitats canary',
   NOW())
ON CONFLICT (company_id, property_code, flag_name)
DO UPDATE SET
  enabled = EXCLUDED.enabled,
  enabled_at = EXCLUDED.enabled_at,
  enabled_by = EXCLUDED.enabled_by,
  notes = EXCLUDED.notes;
```

### Cache TTL

The `FeatureFlagService` cache TTL is 5 minutes. Either wait it out
or restart the relevant Railway worker to force a re-read.

### Verification

After cache expiry / restart, the next inbound guest message to
Beach Habitats should produce a `message_normalizations` row with
populated composer columns. Wait for one real message, then:

```sql
SELECT source_message_id,
       draft_source,
       composer_source,
       composer_latency_ms,
       jsonb_array_length(composer_notes) AS notes_count,
       updated_at
FROM message_normalizations
WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND composer_source IS NOT NULL
ORDER BY updated_at DESC
LIMIT 5;
```

If you see `composer_source = 'llm_anthropic'` (or `llm_groq`,
`llm_gemini`, `fallback_concatenation`, `fallback_empty`) — compare
mode is live. If `composer_source` is still NULL on new rows after
cache expiry, the flag isn't being read; check
`operator_feature_flags` for the rows you just inserted, verify the
cache TTL has elapsed, and confirm Step 2.0's runtime check still
holds. A `route_outcome = 'shadow_persisted'` on a new row with NULL
`composer_source` means the message didn't reach the orchestrator —
that's the runtime-off symptom.

---

## Step 3 — Compare-mode review queries

These are the queries you'll run repeatedly during canary review. The
goal of this step is to look at composer outputs side-by-side with
what the operator actually saw, across enough real messages that you
can decide whether to promote.

### 3.1 Side-by-side recent rows

```sql
SELECT
  source_message_id,
  LEFT(latest_guest_turn, 120) AS guest_message,
  composer_source,
  LEFT(composer_response_text, 240) AS composer_text,
  composer_latency_ms,
  composer_input_tokens,
  composer_output_tokens,
  composer_notes,
  fallback_reason,
  updated_at
FROM message_normalizations
WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND composer_source IS NOT NULL
ORDER BY updated_at DESC
LIMIT 50;
```

`fallback_reason` is the existing audit-notes column — it carries the
brain pipeline's `record.notes` joined into a string. Any
`composer_shadow_mode:` or `composer_live_mode:` markers will appear
here. `composer_notes` is the composer agent's own per-call notes
(grounding warnings, provider fallthroughs, invalid-output reasons).

### 3.2 Composer-source distribution

```sql
SELECT composer_source, COUNT(*) AS rows, AVG(composer_latency_ms)::int AS avg_ms
FROM message_normalizations
WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND composer_source IS NOT NULL
  AND updated_at > NOW() - INTERVAL '7 days'
GROUP BY composer_source
ORDER BY rows DESC;
```

What you want to see: most rows on the primary provider
(`llm_anthropic` if Anthropic key is up), small count on
`fallback_concatenation` (provider hiccups), zero or near-zero
`fallback_empty` (empty decisions list — usually means an upstream
classification problem, not a composer issue).

### 3.3 Grounding-warning surface area

```sql
SELECT
  source_message_id,
  composer_source,
  LEFT(composer_response_text, 200) AS composer_text,
  composer_notes,
  updated_at
FROM message_normalizations
WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND composer_notes::text LIKE '%composer_grounding_warning%'
ORDER BY updated_at DESC
LIMIT 25;
```

`composer_grounding_warning:dollar_amount:*`,
`composer_grounding_warning:percentage:*`,
`composer_grounding_warning:time_of_day:*`,
`composer_grounding_warning:phone_number:*`,
`composer_grounding_warning:email_address:*` — the heuristic surfaces
fabrication risk without invalidating output. Rows that surface here
deserve a closer look. They are not necessarily wrong; the heuristic
is intentionally narrow.

### 3.4 Provider failure rates

```sql
SELECT
  source_message_id,
  composer_source,
  composer_notes,
  updated_at
FROM message_normalizations
WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND (
    composer_notes::text LIKE '%composer_timeout%'
    OR composer_notes::text LIKE '%composer_exception%'
    OR composer_notes::text LIKE '%composer_invalid_output%'
    OR composer_notes::text LIKE '%composer_orchestrator_error%'
  )
ORDER BY updated_at DESC
LIMIT 25;
```

Any persistent `composer_timeout:anthropic` or
`composer_exception:groq:*` cluster is a provider-health signal — if
it correlates with vendor incidents, ignore; if not, investigate.
`composer_orchestrator_error:*` is structurally different — that's
the composer-orchestrator boundary failing, not the LLM call. Those
are bugs in our wiring and warrant a code change.

### 3.5 Latency percentiles

```sql
SELECT
  composer_source,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY composer_latency_ms) AS p50_ms,
  PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY composer_latency_ms) AS p90_ms,
  PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY composer_latency_ms) AS p99_ms,
  COUNT(*) AS rows
FROM message_normalizations
WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND composer_latency_ms IS NOT NULL
  AND updated_at > NOW() - INTERVAL '7 days'
GROUP BY composer_source
ORDER BY rows DESC;
```

Composer total budget is 6.0s per call. p99 should land well under
that. If p99 ≥ 5500ms, the budget is being approached and provider
fallthrough is starting to dominate latency.

---

## Step 4 — Promotion criteria (compare → live)

The boring, explicit criterion for flipping
`MESSAGING_BRAIN_LLM_COMPOSER_SHADOW` from `true` to `false`:

- **Sample size:** at least 30 inbound messages where
  `composer_source = 'llm_anthropic'` (or whichever provider is
  primary). Provider-fallback and empty rows don't count toward
  the 30 since they don't exercise the model.

- **Operator-policy honored:** in spot-check of the 30, every row
  whose `operator_guidance` had real content shows the composer
  output respecting that policy. The known failure mode is
  echoing a permissive specialist `draft_text` when operator
  policy says no — see `test_smoke_operator_guidance_precedence_anthropic`
  for the canonical example. Any single confirmed instance of this
  blocks promotion.

- **No fact fabrication:** `composer_response_text` does not
  contain any property fact (price, time, occupancy, amenity)
  that isn't either in the message_normalizations row's upstream
  context (property_facts / property_knowledge / etc. for that
  property) OR explicitly hedged ("let me confirm with the owner").

- **Grounding warnings reviewed:** every row from query 3.3 has
  been read. Each should either be a defensible reference to a
  real fact (e.g. composer surfaced "$150 cleaning fee" because
  that fee exists in `property_facts`) or a hedged statement
  ("approximately $150"). Numeric content with no upstream
  source is a blocker.

- **No `composer_orchestrator_error` notes** in the 30.
  Provider-side failures are acceptable (the fallback chain handles
  them); orchestrator-boundary failures mean our wiring is broken.

- **Latency p99 < 5500ms** on the 7-day window.

If all six hold for 30+ messages: flip shadow to false.

If any single criterion fails: do not promote. Capture the failing
row(s), iterate on the prompt or wiring as needed, recommit, redeploy,
restart the 30-message clock.

### Promotion command

Same shape as Step 2, just flipping the shadow flag off. Composer
flag stays on.

```sql
UPDATE operator_feature_flags
SET enabled = FALSE,
    enabled_at = NOW(),
    enabled_by = '<your-name>',
    notes = 'Promote to live composer — 30+ messages clean'
WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND property_code IS NULL
  AND flag_name = 'messaging_brain_llm_composer_shadow';
```

After cache expiry / restart, the operator starts seeing composer
output directly. The audit row continues to record everything as
before, so post-promotion review uses the same queries from Step 3.

---

## Step 5 — Rollback

The composer is reversible at every flag boundary. Three rollback
levels, each strictly safer than the next:

### 5.1 Promote-too-early — flip shadow back on

If composer output reaches operators and looks bad, flip shadow
back on. Operators immediately revert to seeing concatenation,
composer keeps running for compare-mode signal:

```sql
UPDATE operator_feature_flags
SET enabled = TRUE,
    enabled_at = NOW(),
    enabled_by = '<your-name>',
    notes = 'Rollback to compare mode — <reason>'
WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND property_code IS NULL
  AND flag_name = 'messaging_brain_llm_composer_shadow';
```

This is the "soft rollback" — operator sees concatenation again
within the cache TTL.

### 5.2 Composer-itself-broken — turn composer off entirely

If the composer is producing bad data even in compare mode (a
prompt regression, a deployment-config issue) or you just want
zero composer activity for any reason:

```sql
UPDATE operator_feature_flags
SET enabled = FALSE,
    enabled_at = NOW(),
    enabled_by = '<your-name>',
    notes = 'Composer off — <reason>'
WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND property_code IS NULL
  AND flag_name = 'messaging_brain_llm_composer';
```

After cache expiry, composer stops running. New rows have NULL
composer columns. Existing rows keep their data — useful for
post-mortem.

### 5.3 Schema rollback — last resort

Migration 054 has a downgrade that drops all six columns. Do **not**
run this lightly — every compare-mode and live-mode row's audit data
goes with it.

```bash
DATABASE_URL=<target-db-url> alembic downgrade 053_inbound_classifications
```

Only consider this if the schema itself causes a problem (e.g.
unexpected column-name collision with another migration) and the
data is genuinely worth losing. In every other case, leave the
columns and turn the composer off via Step 5.2.

---

## Per-tenant rollout notes

This runbook hard-codes Beach Habitats' tenant id because it's our
canary. For subsequent tenants, swap `e07980b2-a990-4b24-91d1-c8cb71ab70e1`
in every SQL block above. Steps 1, 4, 5.3 are global and run once.
Steps 2, 3, 4 (per-tenant), 5.1, 5.2 are per-tenant.

For new tenants, **Step 2.0's brain-runtime check is the gate that
matters most.** If runtime has never been on for the tenant, do not
combine the runtime-on flip with the composer flag flip — see Step
2.0 for the recommended ordering (runtime first, observe, then
composer flags).

Each tenant should go through compare mode independently. Do not
skip compare for "we already validated it on Beach Habitats" —
operator policy phrasing differs across tenants and that's exactly
where the composer can drift.
