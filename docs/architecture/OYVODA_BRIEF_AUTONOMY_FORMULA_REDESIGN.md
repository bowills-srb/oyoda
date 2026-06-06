# Brief — Autonomy Formula Redesign (Theory A fix: formula is inert on clean input)

For Claude Code. Build-ready. Read OYVODA_BRIEF_GAP_CLEANUP_V2.md and the DOMAIN-AUTONOMY
section of OYVODA_MASTER_ROADMAP.md first. This is the JUDGMENT brick — reshape the scoring
so it's a real function of inputs, validated across HYPOTHETICAL tenant profiles, NOT fitted
to Beach Habitats. Still NOT the per-property/per-domain computation layer.

## Confirmed diagnosis (from CLEAN input)

After the gap cleanup, Beach Habitats inputs are: 50 properties, 1810 KB entries, 34
distinct/genuine/attributed gaps, 0 escalations. The score is STILL pinned at:
portfolio 0.5, readiness 0.5, escalation 0.5, behavior neutral(0.5). Input is now clean, so
this is Theory A: the FORMULA is inert. Three saturation bugs in autonomy_score_service.py
cause it:

**Bug 1 — gap penalty is capped raw-count, not a ratio.**
`gap_penalty = min(0.5, kb_gaps * 0.05)`. At 34 gaps → min(0.5, 1.7) = 0.5 (capped). The cap
eats everything above ~10 gaps, so the penalty is a CONSTANT for any real portfolio. Also not
scale-aware: 34 gaps / 50 properties is treated like 34 gaps / 5 properties.

**Bug 2 — coverage saturates at 1.0.**
`raw_coverage = min(1.0, kb_entries / target)`. 1810/250 = 7.24 → capped to 1.0. So coverage
is ALSO a constant for any well-documented portfolio. Readiness = 1.0 − 0.5 = exactly 0.5 every
time — two saturations colliding.

**Bug 3 — escalation conflates no-data with neutral AND mis-handles zero-escalations.**
`escalation_score = resolved/(open+resolved) if total>0 else 0.5`. Beach Habitats has 0/0 →
total=0 → falls to 0.5. But "zero escalations with real traffic" (pristine, should be HIGH) and
"zero escalations because no history" (unknown, should be neutral/insufficient-signal) both
produce total=0 and both get 0.5. They are opposite signals and must be distinguished.

## The redesign (reshape, don't just tune constants)

### Readiness — make the gap penalty a RATIO so it scales and doesn't cap-flatline
Replace raw-count penalty with a ratio relative to portfolio size (and/or KB coverage). E.g.:
- gap_ratio = distinct_genuine_gaps / max(1, property_count)   # gaps per property
- or = distinct_genuine_gaps / max(1, kb_entries)              # gaps per KB entry
Penalty should be a smooth function of that ratio (not a hard cap that pins it). Beach Habitats:
34/50 = 0.68 gaps/property — a LIGHT ratio, should produce a SMALL penalty, leaving readiness
HIGH (saturated coverage, few gaps relative to size). A sparse operator with 30 gaps / 5
properties = 6.0 gaps/property should produce a LARGE penalty → low readiness. THAT is the
scale-invariance the raw count lacks.
Decision point (make it deliberately, document it): is coverage-saturated-at-1.0 acceptable as
"fully documented"? If yes, fixing the gap side alone moves the score off 0.5 (1.0 − small ratio
penalty). If you want coverage itself to keep discriminating above the target, make raw_coverage
a softer curve (e.g. diminishing returns) rather than a hard min(1.0). Prefer the simpler fix
(ratio gap penalty) unless coverage discrimination above target is genuinely wanted for v1.

### Escalation — distinguish three states honestly
- **Has escalation traffic, mostly resolved** → high score (resolving well).
- **Has traffic, many unresolved** → low score (escalation pressure).
- **Zero escalations with real message/session traffic** → this is GOOD (pristine) → should read
  HIGH, not 0.5. Use session/inquiry volume as the "is there traffic" signal: if the tenant has
  meaningful traffic but zero escalations, that's a positive, not a no-data neutral.
- **Zero escalations AND no/low traffic** → genuine no-data → neutral OR mark as
  insufficient-signal (band word), not a computed number masquerading as measurement.
Beach Habitats has real traffic (1810 KB entries imply active operation) and 0 escalations →
under the redesign this should read as a POSITIVE escalation signal, not 0.5. That alone moves
the portfolio score.

### Behavior — UNCHANGED, stays neutral
Behavior remains NEUTRAL_BEHAVIOR, decoupled from the learning redesign (on hold). Do not wire
in operator_draft_events. This is the deliberate decoupling. Keep WEIGHT_BEHAVIOR low (0.1) so
the neutral stub barely moves the score — which is correct while it's a stub.

## ANTI-OVERFITTING — the load-bearing discipline (n=1)
We have ONE live tenant. The goal is NOT "make Beach Habitats produce a nice number." The goal
is a formula that is a real function of inputs and behaves sensibly across HYPOTHETICAL profiles.
Validate the redesigned formula against these synthetic inputs (compute by hand / unit test) and
confirm each lands sensibly BEFORE accepting it:
- **Well-documented large** (50 prop, 2000 KB, 30 gaps, 0 esc w/ traffic) → HIGH (~0.7–0.85).
- **Sparse small** (5 prop, 20 KB, 30 gaps, 5 open esc) → LOW (~0.2–0.35).
- **New/no-data** (3 prop, 5 KB, 0 gaps, 0 esc, no traffic) → NEUTRAL or insufficient-signal,
  NOT a confident number.
- **Mid** (20 prop, 300 KB, 60 gaps, mixed esc) → MIDDLE.
If the formula reads sensibly across all four, it's principled. If it only makes Beach Habitats
look good, it's overfit — reject and reshape. The test is RESPONSIVENESS across profiles, not a
target value for the live tenant.

## CAUTION — "move off 0.5" is not the goal; "function of inputs" is
Do NOT reshape just to make Beach Habitats escape 0.5. 34 genuine gaps across 50 properties with
saturated coverage and zero escalations is plausibly a GENUINELY GOOD portfolio — the right score
might be ~0.75, and that's fine. The success criterion is: change an input, the score changes
sensibly. A formula that reads 0.75 for Beach Habitats and 0.3 for the sparse hypothetical is
WORKING. A particular number for Beach Habitats is not the target.

## Keep
- Named-constants style (tunable). New ratio params as named constants.
- Band words for immature domains (guest_ops/maintenance/turnover unchanged).
- The distinct/genuine/attributed gap counting (that's the cleaned input — keep it).
- Output shape (portfolio_score, domain_bands, components) unchanged — only the math inside changes.
- Inquiry band still derived from readiness as the v1 portfolio proxy (per-property is the next brick).

## Done when
- Gap penalty is a scale-invariant ratio (not capped raw count); coverage decision documented.
- Escalation distinguishes pristine-with-traffic (high) from no-data (neutral/insufficient).
- Behavior unchanged (neutral, weight 0.1).
- Unit tests covering the 4 hypothetical profiles, each asserting a sensible RANGE (not exact value).
- Re-run snapshot for Beach Habitats: report new portfolio_score + components. Confirm it MOVED
  and is a function of inputs (perturb one input in a test, confirm the score responds).
- Commit SHA. Roadmap updated: formula redesigned, responsive on clean input, computation layer NOW UNBLOCKED.
