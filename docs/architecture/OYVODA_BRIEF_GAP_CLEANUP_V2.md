# Brief — Gap Cleanup v2: format-aware resolution + clean readiness input

For Claude Code. Build-ready. Read OYVODA_BRIEF_GAP_RECORDING_FIX.md (the forward fix,
e951793, already landed) and OYVODA_MASTER_ROADMAP.md first. This amends the historical
cleanup so we don't quarantine RECOVERABLE rows, and fixes the readiness INPUT so the
re-run snapshot is validatable. We get ONE first-clean-data-point — make it genuinely clean.

## GATE 0 — confirm the database target (do this FIRST, only proceed if production)

Before ANY --no-dry-run write: confirm the backfill/quarantine and the snapshot are running
against the PRODUCTION database, not a disk/fixture DB. Print/inspect the actual DATABASE_URL
(or connection target) the script connects to and confirm it's the live Supabase instance for
tenant e07980b2-a990-4b24-91d1-c8cb71ab70e1. This session has had disk-vs-tree confusion; a
write against the wrong DB is hard to undo. Do not write until the target is confirmed production.

## Where the dry-run landed (live tenant)
- 100 rows have a non-empty external identifier; resolver matched 59, MISSED 41.
- 473 rows have no identifier at all.
The 41 misses are the problem: they have identifiers that don't EXACT-match property_code or
external_id. Hunter's domain knowledge says why — see Fix A.

## Fix A — format-aware resolver for Beach Habitats' ID scheme (recovers most of the 41)
Beach Habitats external IDs are `2403-xxxxxx`: `2403` = company identifier, suffix = property
identifier. CRITICAL: "sometimes listed together, sometimes broken out." So a gap may carry
`2403-118432`, or `118432`, or `2403 118432`, while the properties table stores the canonical
form in ONE shape. A literal `external_id = :val OR property_code = :val` match misses every
format variant — that's almost certainly most of the 41: REAL properties failing string match,
not unattributable rows.

Improve the resolver (gap_backfill.py + ideally the shared _resolve_property_id_from_external
so the FORWARD path benefits too) to normalize before matching:
- Strip a leading company prefix (`2403-`, `2403 `, `2403`) and try the suffix alone.
- Try with and without separators (`-`, space, none).
- Match against BOTH external_id AND property_code columns, normalized the same way on both sides.
- If properties stores external IDs in a structured/JSON column (external_ids), check there too
  (the poller's _property_table_meta referenced a json_external_ids_col — reuse that knowledge).
Re-run the DRY RUN after this. Expectation: the 59 climbs substantially, the 41 shrinks. Report
the new resolved/missed split. ONLY rows that still miss after normalization are candidate
unattributable.

## Fix B — thread inheritance is ALREADY wired forward; use it for historical recovery if cheap
VERIFIED: _prepare_parsed_message (poller line 1833) runs thread inheritance
(inherit_property_from_thread_context, line 1851) BEFORE any gap is recorded. So FUTURE follow-up
gaps already inherit property from earlier in the thread — no forward fix needed there.
For HISTORICAL rows still missing after Fix A: if a missing gap row has a thread_id/message
linkage, attempt the same inherit_property_from_thread_context against its thread to recover the
property a sibling message carried. This is OPTIONAL — only do it if the gap rows retain enough
thread linkage to make it worthwhile; if not, those rows fall to quarantine. Report how many the
thread pass recovers.

## Fix C — quarantine ONLY the genuinely unattributable (after A + B)
After format-aware resolution and the optional thread pass:
- BACKFILL everything recovered (the improved count): UPDATE property_id on those rows.
- QUARANTINE only rows that STILL have no resolvable property after A+B: flag
  attribution_status='unattributable' (the 473 no-identifier rows + whatever truly won't resolve).
  Do NOT delete. Exclude from scoring inputs.
- Report final tallies: backfilled N, quarantined M, and confirm N+M = 573.

## Fix D — readiness input must count DISTINCT, GENUINE, ATTRIBUTED gaps (not raw rows)
autonomy_score_service.py (line ~129) currently counts RAW unresolved concierge_knowledge_gaps.
Even on a clean table this is wrong: 573 rows were only 322 distinct questions (~44% dup), and
quarantined rows must be excluded. Change the readiness input to count:
- unresolved gaps WHERE attribution_status is not 'unattributable' (exclude quarantine), AND
- DISTINCT by normalized question-key (+ property), not raw rows, AND
- optionally weight toward genuine-signal rows (low confidence / not deflected) if cheap.
This makes the readiness denominator a real coverage signal. Keep the change in the scoring
service with the existing named-constants style so it's tunable.

## SEQUENCE (strict)
1. GATE 0: confirm production DB target.
2. Fix A (format-aware resolver) → re-run DRY RUN → report new split.
3. Fix B (optional thread recovery for historical) → report recovery.
4. Fix C: write — backfill recoverable, quarantine only the truly unattributable. Confirm N+M=573.
5. Fix D: patch readiness input to distinct/genuine/attributed (exclude quarantine).
6. THEN re-run the autonomy snapshot. NOW the readiness number is trustworthy.
7. Read the result: did portfolio_score move OFF 0.5?
   - Moved → input was the problem; formula works (Theory C). Proceed to computation layer.
   - Still exactly 0.5 across components on CLEAN input → formula is inert (Theory A); the next
     brick is the formula-validation diagnostic (hand-derive each component), not the computation layer.

## Scope guards
- GATE 0 is mandatory before any write.
- Backfill/quarantine = UPDATEs only, never DELETE.
- Fix A's normalization should ideally also land in the shared forward resolver so future gaps
  with broken-out IDs attribute too — note if you do this (it's a forward improvement, good).
- Still NOT the computation layer, still NOT formula weight-tuning. This brick ends at "re-run
  snapshot, read whether it moved off 0.5."
- This bug/cleanup affects Property Readiness + Knowledge Health too — note system-wide impact.

## Done when
- DB target confirmed production.
- Format-aware resolver recovers most of the 41; new dry-run split reported.
- Recoverable rows backfilled with property_id; only truly-unattributable quarantined; N+M=573 confirmed.
- Readiness input counts distinct/genuine/attributed unresolved gaps (quarantine excluded).
- Autonomy snapshot re-run; new portfolio_score + components reported; Theory C vs A called.
- Commit SHA(s). Roadmap updated: gap cleanup done, readiness input fixed, formula-validation status
  (Theory C proceed-to-computation, or Theory A diagnostic-next) recorded.
