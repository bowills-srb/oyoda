# Brief — Gap-Integrity Audit (PREREQUISITE to autonomy formula validation)

For Claude Code. Build-ready. Read docs/architecture/OYVODA_MASTER_ROADMAP.md
(DOMAIN-AUTONOMY section) first. This is a MEASURE-THEN-DECIDE diagnostic, NOT a fix and
NOT the computation layer. Do not tune the autonomy formula, do not change weights, do not
delete data, until this audit's findings are in.

## Why this exists

The first real autonomy snapshot (Beach Habitats) scored portfolio=0.5 with readiness=0.5,
escalation=0.5, behavior=neutral. The readiness component consumes "573 unresolved knowledge
gaps." Before validating/tuning the autonomy formula, we must know whether 573 is a
TRUSTWORTHY number, because: good formula + bad input = bad score, and we have only ONE live
tenant (Beach Habitats, tenant e07980b2-a990-4b24-91d1-c8cb71ab70e1) — no population to
triangulate against, so the input itself must be validated directly.

Context that raised the question: a brain-flow rework moved deterministic filters out of the
decision state into transit. Hypothesis: in-transit gap assessments (KnowledgeGapAgent emits
gap_severity="hold") may now be persisting to concierge_knowledge_gaps as durable rows when
previously a deterministic filter resolved them first — inflating the count with artifacts.

## CRITICAL framing — measure, do not confirm

There are THREE live theories and the audit must be capable of confirming ANY of them:
- **Inert formula**: components default to 0.5 regardless of input.
- **Real score**: 573 are genuine, distinct, unresolved gaps; Beach Habitats really is middling
  and the score is correct.
- **Corrupted input**: some/many of the 573 are transit-artifacts or duplicates inflating the count.

"The gaps are garbage" is a COMFORTING NARRATIVE. Do NOT write queries that assume it. The
queries below MEASURE; "the 573 are real and distinct" is a fully acceptable outcome that sends
us straight to formula validation with confidence. Report what the data shows, not what's tidy.

## Code grounding (verified)
- Gaps table: `concierge_knowledge_gaps`, owned by
  app/services/messaging_brain/knowledge/gap_recorder.py (the concierge/ recorder is a shim).
- Each row carries: source, stage, detected_intent, confidence_score, resolved, created_at,
  property_id/property_external_id, metadata_json (incl. used_kb_chunks, was_deflected,
  answer_attempt), question_text.
- record_gap dedupes only within a 72h window on (tenant + property + normalized-question-key);
  normalized key is a sorted bag-of-words hash (stopwords removed). So the SAME question asked
  >72h apart logs as separate rows, and near-duplicates with different tokens log separately.
- KnowledgeGapAgent.analyze (messaging_brain/agents/knowledge_gap_agent.py) is an ANALYZER, not
  a writer — it emits gap_topics with gap_severity="hold". It resolves many topics
  deterministically (closed-world rules: pool heat, pet policy, check-in, occupancy, etc.), so a
  gap that DOES get recorded genuinely means missing structured data/knowledge for that topic.
- A `knowledge_gap_hold_agent` existed and was removed during the rework (only .pyc remains) —
  corroborates that the rework touched the gap path.

## The audit — run these queries against the LIVE tenant, report raw results

All queries scope to tenant_id = e07980b2-a990-4b24-91d1-c8cb71ab70e1, unresolved gaps
(resolved = false), since that's what the readiness component counts. Confirm the count first
(should be ~573).

**Q0 — fast first look (provenance by source):**
`SELECT source, COUNT(*) FROM concierge_knowledge_gaps WHERE tenant_id=... AND resolved=false
 GROUP BY source ORDER BY 2 DESC;`
If one source value dominates (e.g. a legacy "concierge" bucket vs a brain bucket), that may tell
the story in one query.

**Q1 — provenance by source + stage + time:** group the unresolved gaps by (source, stage), and
bucket created_at by month (or around the brain-flow rework date if known — ASK Hunter for the
rework date if it's needed to set the cutoff). Looking for: a cluster of rows from a particular
source/stage that spikes after the rework = the transit-artifact signal.

**Q2 — failure-signal breakdown:** of the unresolved gaps, how many have GENUINE
AI-couldn't-answer signals vs not:
- low/empty confidence_score, metadata_json->>'used_kb_chunks' = false,
  metadata_json->>'was_deflected' = true → genuine gap signal
- rows lacking those signals → suspected pass-through/transit artifacts
Report the split.

**Q3 — uniqueness:** how many DISTINCT normalized question-keys do the 573 rows represent? (Apply
the same normalization the recorder uses — sorted non-stopword tokens — or approximate with
lower+trim on question_text grouped.) If 573 rows collapse to far fewer distinct keys, DUPLICATION
(not pollution) is a big part of the inflation. Also report distinct (question-key × property)
pairs, since a gap is property-scoped.

**Q4 — distribution sanity:** gaps per property (how many of the 50 properties have gaps, and the
shape — is it concentrated in a few under-documented properties or spread evenly?), and
resolved-vs-unresolved ratio overall.

## The decision (AFTER the queries — do not pre-decide)

Map findings to ONE of three fixes:
- **Pollution found** (transit-source/stage cluster, low genuine-failure-signal): the readiness
  input should EXCLUDE artifact rows (filter by source/stage/signal). Data may need a flag, not
  deletion. This is a gap_recorder/readiness-input fix.
- **Duplication dominant** (573 collapses to few distinct keys): the readiness formula should
  count DISTINCT unresolved question-keys (or key×property), not raw rows. This is a scoring-input
  fix, not a data fix. Do NOT delete the rows — de-dupe in the count.
- **Gaps are real and distinct**: the input is trustworthy; 573 genuinely reflects coverage. Go
  straight to formula validation; Beach Habitats is legitimately middling on readiness.

It may be a MIX (some pollution + some duplication + a real core). Report the breakdown so the
readiness input can be defined as "distinct, genuine, unresolved gaps" — which is likely a
different (smaller) number than 573, and may move readiness off 0.5 in EITHER direction.

## Scope guards
- This is READ-ONLY diagnostics + a written findings report. NO data deletion, NO formula change,
  NO weight tuning, NO computation layer in this brick.
- If a fix is warranted, it's a SEPARATE follow-up brick scoped from these findings.
- Note: this audit's finding affects more than autonomy — Property Readiness, Knowledge Health,
  and the KB-gap queues all read this table. A pollution finding is a wider data-integrity issue,
  not just an autonomy input. Flag accordingly.

## Done when
- Q0–Q4 run against the live tenant; raw results reported (counts, breakdowns, distributions).
- A written finding: which theory the data supports (inert / real / corrupted / mixed) and the
  estimated count of DISTINCT, GENUINE, unresolved gaps vs the raw 573.
- A recommendation mapping the finding to one of the three fixes (or "input is trustworthy,
  proceed to formula validation"), as a proposal — NOT executed in this brick.
- No code/data changed. Findings written to the roadmap or a short audit note in docs/architecture/.
