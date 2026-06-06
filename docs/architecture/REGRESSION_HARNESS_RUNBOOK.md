# Regression Harness Runbook

Use [scripts/synthetic_inbound_pipeline_report.py](/Users/dhuntermckenzie/Downloads/oyvoda/scripts/synthetic_inbound_pipeline_report.py) as synthetic verification for current Brain-era messaging paths.

## What it is good for

- Pre-flip rehearsal against the current flag surface
- Post-deploy synthetic verification across representative channels and lifecycles
- Fast detection of parser, routing, lifecycle, proactive, or Ship I substrate drift

## What it is not good for

- It is not a substitute for a live production smoke when a ship changes operator-facing UI
- It is not acceptable rollout evidence if the harness itself is stale relative to runtime contracts
- It is not a complete production fixture corpus; it is a representative synthetic matrix

## Usage

Run the default Brain-era profile:

```bash
python3 scripts/synthetic_inbound_pipeline_report.py
```

Run all supported profiles side by side:

```bash
python3 scripts/synthetic_inbound_pipeline_report.py --flag-matrix
```

Emit JSON for tooling:

```bash
python3 scripts/synthetic_inbound_pipeline_report.py --flag-matrix --json
```

## Interpretation rules

- A case only counts as success if its stage-level assertions pass
- A fallback is not normal success; it must appear explicitly in notes or failures
- A KB-gap case is a failure if `blocked_by_gap_topics` is empty or disagrees with `missing_property_knowledge:*`
- If the harness begins failing on infrastructure seams like flag lookup or fake DB methods, stop using it as rollout evidence until the seam is repaired

## Harness maintenance discipline

The harness has two layers. The infrastructure layer (runner, CI integration, case schema, runbook, flag-matrix capability) is durable. The migration-specific layer (profiles, flag references, canary cases) is temporary and has explicit end-of-life conditions tied to other ships.

Update the harness in the same commit as the work that affects it:

- When a flag is removed from the code, remove it from `_flag_values()` and any profile definitions.
- When legacy code is deleted during the Ship O arc, remove `legacy_runtime_off`.
- When `SHIP_I_KB_RETRY_PRIMARY` is removed after Ship I proves stable, collapse `ship_i_canary` into `brain_primary`.
- When the real fixture corpus supersedes a synthetic case, migrate or remove the synthetic case.

If the harness begins failing on infrastructure seams like flag lookup, fake DB methods, or contract drift, stop using it as rollout evidence until the seam is repaired. Do not paper over the drift with looser assertions.
