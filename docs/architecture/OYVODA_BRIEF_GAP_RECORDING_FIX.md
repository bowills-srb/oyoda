# Brief — Gap Recording Fix: property attribution + poller retirement

For Claude Code. Build-ready. Read docs/architecture/OYVODA_BRIEF_GAP_INTEGRITY_AUDIT.md
(the audit that found this) and OYVODA_MASTER_ROADMAP.md first. This FIXES a confirmed,
live, ongoing data-integrity bug. It is NOT the autonomy formula and NOT the computation
layer — those resume after the gap input is trustworthy.

## The confirmed bug (verified in code + live data)

Live data: all 573 unresolved gaps for the live tenant have property_id = NULL, including
gaps written TODAY, from BOTH sources (gmail_poll AND messaging_brain_orchestrator). Only
100/573 even have property_external_id; 473 have neither. So this is a CURRENT bug in the
SHARED recording path, not legacy residue and not poller-specific.

Two distinct defects, both confirmed in code:

**Defect 1 — recorder never resolves property_id at write time (THE CORE BUG).**
`gmail_inbox_poller._record_kb_gap` (line ~2639) calls `record_gap_async(..., property_code=
parsed.property_code or "")`. `record_gap_async` (messaging_brain/knowledge/gap_recorder.py)
forwards property_code as `property_external_id` and calls `record_gap`, which inserts the row
WITHOUT ever resolving external_id -> property_id. Resolution only happens in `resolve_gap`
(via `_resolve_property_id_from_external`), which runs only when a gap is RESOLVED. Net: every
gap is written property_id = NULL by construction. This affects EVERY caller of the recorder,
which is why messaging_brain_orchestrator gaps are ALSO NULL. Fix in the shared recorder =
fixes all sources.

**Defect 2 — property_code is often empty at record time (473/573 had no external_id).**
`parsed.property_code` is frequently "" when `_record_kb_gap` fires. The routing path DOES
resolve property (`_resolve_property_code` at ~1844 + thread-inheritance fallback ~1847), but
gaps are evidently recorded on a path/timing where that resolution hasn't populated
property_code, OR resolution failed (the old deterministic parser problem). Hunter has moved
property extraction to an LLM that can resolve from property NAME, ADDRESS, or EXTERNAL ID —
but that improvement only helps gaps if (a) it runs BEFORE the gap is recorded and (b) its
result reaches the recorder.

## The fix

### Fix 1 — resolve property_id at WRITE time in the shared recorder (highest leverage)
In `gap_recorder.record_gap` (and the async wrapper), when `property_id` is not provided but
`property_external_id` is, resolve it BEFORE insert using the existing
`_resolve_property_id_from_external` helper (already in the file — currently only called from
resolve_gap). So a gap recorded with a property_code/external_id lands with property_id
populated immediately. This single change fixes attribution for ALL future gaps from ALL
sources where an external_id is present. Keep it fail-soft: if resolution returns nothing,
record with property_id NULL but log it (so we can see the miss rate).

### Fix 2 — ensure property resolution runs before the gap is recorded, using the LLM path
Trace where `_record_kb_gap` / `_maybe_record_pre_booking_gap` fire relative to
`_resolve_property_code` (~1844) and thread inheritance (~1847). The gap record must happen
AFTER property resolution so `parsed.property_code` is populated. If the LLM-based extraction
(name/address/external-id) now produces a property reference, confirm that value flows into
`parsed.property_code` (or property_external_id) BEFORE `_record_kb_gap` is called. The goal:
gaps inherit the same resolved property the routing path already computed, including the LLM's
name/address/external-id resolution. Do NOT record a gap with empty property when the message
was successfully attributed to a property elsewhere in the same parse.

### Fix 3 — stop gmail_poll from writing gaps (poller retirement)
gmail_poll is STILL writing gaps (9 on 2026-06-01) despite the webhook cutover ~5 days ago.
FIRST determine WHY it's still running — is the poller still scheduled, or is it the gap-write
call specifically that wasn't removed when polling was retired? Then:
- Confirm the WEBHOOK path (gmail_push.py) records gaps AT ALL, and with what source. CRITICAL:
  if you stop gmail_poll gap writes and the webhook doesn't record gaps, you swing from
  over-recording to silent UNDER-recording. Verify the webhook path records gaps (with Fix 1's
  attribution) before suppressing the poller's writes.
- If the webhook fully covers gap recording, retire the poller's `_record_kb_gap` call (and
  ideally the poller itself if it's wholly superseded). If the poller is still needed for other
  reasons, stop only its gap writes.
- Set the source on the surviving path to something accurate (not "gmail_poll" if it's the
  webhook). So future provenance queries are honest.

## Historical cleanup (the existing 573) — SEPARATE from the forward fix
After the forward fix is in (so cleaned rows don't immediately re-pollute):
- **Backfill the 100** rows that have property_external_id: resolve external_id -> property_id
  via the same helper, UPDATE those rows. Recoverable.
- **Quarantine the 473** with neither property_id nor external_id: they are permanently
  unattributable. Do NOT delete — flag them (e.g. a metadata flag like
  `attribution_status="unattributable"` or a resolved/archived state agreed with Hunter) and
  EXCLUDE them from scoring inputs. Purge is the trap — they'd re-accumulate if the forward fix
  weren't in, and they're real records of something even if unattributable.
- This cleanup can be a follow-up commit after the forward fix is verified.

## Verification (REQUIRED before calling done)
- After Fix 1+2: record a NEW test gap for the live tenant from a message that names/addresses a
  known property; confirm the row lands with property_id POPULATED. Re-run the daily query
  (date_trunc, source, count, count(property_id)) and confirm recent gaps now have
  with_property_id > 0.
- After Fix 3: confirm gmail_poll stops writing new gaps and the webhook path records them
  (attributed) instead. No silent gap in recording.
- Report the new miss rate (gaps still NULL because property genuinely couldn't be resolved) —
  that's the real "unattributable" floor, and it should be far below today's 100%.

## Scope guards
- This is the gap RECORDING path + historical cleanup. NOT the autonomy formula, NOT weights,
  NOT the computation layer. Those resume once the gap input is trustworthy.
- Fail-soft everywhere: gap recording must never throw into the message pipeline.
- This bug affects Property Readiness, Knowledge Health, and KB-gap queues too — not just
  autonomy. Note in the commit that the fix is system-wide, not autonomy-specific.

## Done when
- record_gap resolves property_id from external_id at write time (shared path; all sources benefit).
- Gap recording happens after property resolution; LLM-resolved property (name/address/external-id)
  reaches the recorder.
- New gaps land with property_id populated (verified by re-running the daily query).
- gmail_poll no longer writes gaps; webhook path records them attributed; no silent under-recording.
- The 100 recoverable rows backfilled; the 473 quarantined (not deleted), excluded from scoring.
- Commit SHA(s) recorded. Roadmap updated: gap-integrity bug FIXED, autonomy formula validation UNBLOCKED.
