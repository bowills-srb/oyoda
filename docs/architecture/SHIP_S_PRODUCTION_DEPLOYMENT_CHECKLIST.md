# Ship S Production Deployment Checklist

This checklist is for the first Ship S foundation deployment only:

- `084_ship_s_autonomy_decision`
- production provisioning of `dashboard_v2_primary` default OFF
- deploy of `/app/v2` and `/app/api/v2/*`

The order is load-bearing. Do not deploy Ship S code before the schema is in place.

---

## Pre-Deploy Verification

### 1. Confirm Railway production env is clean

Goal:
- `LOCAL_DATABASE_URL` is not present in production
- production still points at Supabase

Commands:

```bash
railway login
railway variables --service api
```

Verify:
- `LOCAL_DATABASE_URL` is absent
- `DATABASE_URL` points at Supabase / pooler
- production-like env markers are present (`ENVIRONMENT=production` and/or Railway runtime vars)

### 2. Confirm current production schema baseline

Goal:
- production Alembic is still at `083_ship_i_kb_retry_fields`

Command:

```bash
/bin/zsh -lc 'PGURL=$(grep "^ALEMBIC_DATABASE_URL=" .env | cut -d= -f2-); psql "$PGURL" -At -c "SELECT version_num FROM alembic_version;"'
```

Verify:
- output is `083_ship_i_kb_retry_fields`

### 3. Confirm Ship S routes are not yet live

Commands:

```bash
curl -i -s https://oyvoda.com/app/v2
curl -i -s https://oyvoda.com/app/api/v2/prebooking/bootstrap
curl -i -s https://oyvoda.com/app/api/v2/autonomy
```

Verify:
- current state is `404 Not Found`

---

## Phase A — Apply Migration 084

### 4. Review migration before apply

File:
- [084_ship_s_autonomy_decision.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/084_ship_s_autonomy_decision.py)

Review points:
- enum values match Ship S exactly
- temporary default is removed after backfill
- downgrade drops the column and enum cleanly
- no index is added intentionally

### 5. Apply migration to production

Command:

```bash
/bin/zsh -lc 'set -a; source .env; export ALEMBIC_USE_DIRECT_URL=true; .venv/bin/alembic -c alembic.ini upgrade head'
```

### 6. Verify new column exists

Command:

```bash
/bin/zsh -lc 'PGURL=$(grep "^ALEMBIC_DATABASE_URL=" .env | cut -d= -f2-); psql "$PGURL" -At -F $'\''\t'\'' -c "SELECT column_name, data_type, udt_name FROM information_schema.columns WHERE table_schema='\''public'\'' AND table_name='\''pre_booking_inquiries'\'' AND column_name IN ('\''confidence'\'','\''autonomy_decision'\'') ORDER BY column_name;"'
```

Verify:
- `confidence` exists
- `autonomy_decision` exists
- `udt_name` for `autonomy_decision` is `autonomy_decision`

### 7. Verify production Alembic advanced

Command:

```bash
/bin/zsh -lc 'PGURL=$(grep "^ALEMBIC_DATABASE_URL=" .env | cut -d= -f2-); psql "$PGURL" -At -c "SELECT version_num FROM alembic_version;"'
```

Verify:
- output is `084_ship_s_autonomy_decision`

---

## Phase B — Provision `dashboard_v2_primary` Default OFF

### 8. Apply tenant flag provisioning

Artifact:
- [ship_s_dashboard_v2_flag_provision.sql](/Users/dhuntermckenzie/Downloads/oyvoda/scripts/ship_s_dashboard_v2_flag_provision.sql)

Command:

```bash
/bin/zsh -lc 'PGURL=$(grep "^ALEMBIC_DATABASE_URL=" .env | cut -d= -f2-); psql "$PGURL" -f scripts/ship_s_dashboard_v2_flag_provision.sql'
```

### 9. Verify Beach Habitats flag row

Command:

```bash
/bin/zsh -lc 'PGURL=$(grep "^ALEMBIC_DATABASE_URL=" .env | cut -d= -f2-); psql "$PGURL" -At -F $'\''\t'\'' -c "SELECT company_id::text, COALESCE(property_code, '\'''\''), flag_name, enabled, COALESCE(enabled_at::text, '\'''\'' ) FROM operator_feature_flags WHERE company_id = '\''e07980b2-a990-4b24-91d1-c8cb71ab70e1'\''::uuid AND flag_name = '\''dashboard_v2_primary'\'' ORDER BY property_code NULLS FIRST;"'
```

Verify:
- one tenant-scoped row exists
- `enabled=false`

---

## Phase C — Deploy Ship S Code

### 10. Build the frontend bundle

Command:

```bash
npm run build:dashboard-v2
```

Verify:
- bundle exists under `app/static/dashboard-v2/dist`

### 11. Deploy to Railway

Use your normal production deployment path for the API service after the migration and flag provisioning are done.

### 12. Verify `/app/v2` and v2 APIs are live

Commands:

```bash
curl -i -s https://oyvoda.com/app/v2
curl -i -s https://oyvoda.com/app/api/v2/prebooking/bootstrap
curl -i -s https://oyvoda.com/app/api/v2/autonomy
curl -i -s -H "Accept: text/event-stream" https://oyvoda.com/app/api/v2/realtime
```

Verify:
- `/app/v2` returns `200`
- unauthenticated API calls should no longer `404`; they should return auth failures or open SSE behavior as appropriate

---

## Phase D — Production Smoke With Real Beach Habitats Session

### 13. Capture a valid session cookie

Use a real Beach Habitats operator login in the browser, then copy the auth cookie into curl.

### 14. Bootstrap endpoint smoke

Command:

```bash
curl -s https://oyvoda.com/app/api/v2/prebooking/bootstrap \
  -H "Cookie: <REAL_SESSION_COOKIE>" | jq
```

Verify:
- top-level keys exist: `operator`, `tenant`, `inquiries`, `properties`, `summary`, `autonomy`, `flags`
- `tenant.id` is the real Beach Habitats tenant UUID
- `autonomy.tenant.auto_enabled` and `confidence_threshold` are sane
- `flags.dashboard_v2_primary` is `false`

### 15. Autonomy GET smoke

Command:

```bash
curl -s https://oyvoda.com/app/api/v2/autonomy \
  -H "Cookie: <REAL_SESSION_COOKIE>" | jq
```

Verify:
- top-level keys: `tenant`, `per_property`, `lifecycle_overrides`
- `per_property` is `null`
- `lifecycle_overrides` is `null`

### 16. Autonomy PUT smoke

Command:

```bash
curl -s -X PUT https://oyvoda.com/app/api/v2/autonomy \
  -H "Content-Type: application/json" \
  -H "Cookie: <REAL_SESSION_COOKIE>" \
  --data '{"tenant":{"auto_enabled":false,"confidence_threshold":0.85}}' | jq
```

Then re-run:

```bash
curl -s https://oyvoda.com/app/api/v2/autonomy \
  -H "Cookie: <REAL_SESSION_COOKIE>" | jq
```

Verify:
- PUT succeeds
- GET reflects the persisted values
- this also proves missing `operator_settings` rows upsert correctly in production

### 17. SSE smoke

Command:

```bash
curl -N https://oyvoda.com/app/api/v2/realtime \
  -H "Accept: text/event-stream" \
  -H "Cookie: <REAL_SESSION_COOKIE>"
```

Verify:
- stream opens
- initial event arrives
- connection stays open

### 18. Mutation-driven SSE smoke

With the SSE stream open:

- approve an inquiry through the existing operator flow
- verify `inquiry.sent` and `summary.updated` events arrive

Suggested endpoint path to exercise:

```bash
curl -s -X POST https://oyvoda.com/app/api/inquiries/<INQUIRY_ID>/approve \
  -H "Content-Type: application/json" \
  -H "Cookie: <REAL_SESSION_COOKIE>" \
  --data '{}'
```

Verify:
- approval succeeds
- SSE stream emits `inquiry.sent`
- SSE stream emits `summary.updated`

### 19. KB retry SSE smoke

With the SSE stream still open:

- resolve a real KB gap that has blocked drafts waiting

Suggested endpoint path to exercise:

```bash
curl -s -X POST https://oyvoda.com/app/api/kb/gaps/resolve \
  -H "Content-Type: application/json" \
  -H "Cookie: <REAL_SESSION_COOKIE>" \
  --data '<REAL_GAP_RESOLUTION_PAYLOAD>' | jq
```

Verify:
- response includes `triggered_regenerations`
- SSE emits `kb.retry_progress`
- downstream queue state updates make sense

### 20. Browser smoke

Open:
- `https://oyvoda.com/app/v2`
- `https://oyvoda.com/app/v2/components`

Verify:
- shell loads without console errors
- theme toggle works
- dark mode persists across refresh
- `/components` shows styled primitives, not raw browser defaults

---

## Phase E — Flip `dashboard_v2_primary` ON

Only do this after Phase D passes.

### 21. Flip the tenant flag on

Command:

```bash
/bin/zsh -lc 'PGURL=$(grep "^ALEMBIC_DATABASE_URL=" .env | cut -d= -f2-); psql "$PGURL" -c "UPDATE operator_feature_flags SET enabled = TRUE, enabled_at = NOW(), enabled_by = '\''ship_s_flip'\'' WHERE company_id = '\''e07980b2-a990-4b24-91d1-c8cb71ab70e1'\''::uuid AND property_code IS NULL AND flag_name = '\''dashboard_v2_primary'\'';"'
```

### 22. Verify the flip

Command:

```bash
/bin/zsh -lc 'PGURL=$(grep "^ALEMBIC_DATABASE_URL=" .env | cut -d= -f2-); psql "$PGURL" -At -F $'\''\t'\'' -c "SELECT company_id::text, COALESCE(property_code, '\'''\''), flag_name, enabled, COALESCE(enabled_at::text, '\'''\'' ) FROM operator_feature_flags WHERE company_id = '\''e07980b2-a990-4b24-91d1-c8cb71ab70e1'\''::uuid AND flag_name = '\''dashboard_v2_primary'\'';"'
```

Verify:
- `enabled=true`

### 23. Final browser confirmation

Open:
- `https://oyvoda.com/app/v2`

Verify:
- Lanier can reach the v2 shell intentionally
- no redirect from `/app/dashboard`

---

## Notes

- The current Ship S deployment only provides the shell, primitives, bootstrap/autonomy/realtime backend, and route plumbing. It is not Pre-Booking parity yet.
- The in-process SSE hub is acceptable only while production is single-instance.
- Every verification record from this checklist should name the environment explicitly.
