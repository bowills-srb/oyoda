## Phase 2 Deprecations

Date: 2026-05-14
Status: Documentation-only output for Phase 2 `R5`

This note records schema artifacts discovered during Phase 2 that should be
treated as deprecated, deferred, or superseded. The goal is to preserve
historical context without letting old table concepts continue to masquerade as
canonical platform architecture.

## Principles

- Do not rewrite history by deleting old migrations.
- Do not expand abandoned table families during foundation work.
- Prefer documenting superseded concepts now, then removing or replacing them
  intentionally in later phases.

## Deprecated Historical Artifacts

These tables exist in the migration tree but are not active product surfaces in
the current architecture.

### Deprecated

- `concierge_decision_logs`
- `evidence_records`
- `integration_connections`
- `integration_raw_records`
- `integration_sync_jobs`
- `pitch_books`

These should be treated as explored-but-inactive schema artifacts unless a
future product decision explicitly revives them.

## Superseded Legacy Implementations

### `operator_onboarding`

Superseded by:
- [operator_signup.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator_signup.py)
- [operator_auth_service.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/auth/operator_auth_service.py)
- [onboarding_agent.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/agents/onboarding/onboarding_agent.py)

Interpretation:
- the old table represented a previous onboarding tracking concept
- it is not the canonical onboarding persistence model now

### `operator_integrations`

Superseded by:
- [integration_gateway.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/connectors/integration_gateway.py)

Interpretation:
- the need for tenant-scoped integration configuration is real
- this specific table shape is not the canonical current implementation
- a future DB-backed integration configuration model belongs in the
  tenant-normalized architecture, not in the legacy table contract

## Deferred Scaffolding

These production tables are intentionally left alone for now because the
product surface is not active yet.

- `operator_billing`
- `operator_invoices`

Decision:
- do not adopt or remove them during Phase 2
- revisit when Stripe / billing activation becomes real roadmap work

## Keep But Defer

These are real concepts that may be activated later, but they are not Phase 2
adoption targets.

- `experiment_assignments`
- `experiment_variant_events`
- `market_evidence`

## Result of Phase 2

Phase 2 focused on:
- restoring migration authority
- reconciling real production operational tables into the migration tree
- adopting active missing tables that current code depends on

It did not attempt to make every historical artifact canonical.

That distinction is intentional and should be preserved as later phases build
the tenant-normalized, property-normalized foundation.
