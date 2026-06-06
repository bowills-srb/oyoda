# Ship O — Target A audit (`ConciergeRunner`)

**Status:** Audit written May 20, 2026. This is a prerequisite audit for Ship O, not a deletion commit.

## Purpose

Target A in [SHIP_O_DELETION_ARC.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/architecture/SHIP_O_DELETION_ARC.md) is not one deletion task. It is three separate questions:

1. should `/concierge/message` flag-off compatibility remain?
2. is `/concierge/decision` still used by anything real?
3. can the non-prod `/voice/concierge` endpoint be retired now?

They are separated here so each can be decided and committed independently.

---

## A1. `/concierge/message` flag-off compatibility

### Current state

`app/api/v1/endpoints/concierge.py::_handle_via_existing(...)` still exists and still calls `get_concierge_runner()`.

That means `ConciergeRunner` is still the explicit fallback path when `MESSAGING_BRAIN_RUNTIME` is off.

### Why this is not a simple delete

This is not just dead code. It is rollback safety architecture.

Deleting it means making a policy decision:

- either Brain runtime is now mandatory everywhere
- or the rollback path must be preserved for longer

### Recommendation

**Do not delete this path today.**

Treat it as a separate rollback-safety decision after the Brain runtime has survived a longer verification window than the just-landed K/L/M/N ships currently have.

### Result

- **Keep for now**
- revisit only after the broader runtime verification window elapses

---

## A2. `/concierge/decision`

### Current state

`app/api/v1/endpoints/concierge.py::evaluate_decision(...)` still calls `get_concierge_runner()`.

Repo search found:

- the endpoint definition
- schema types in the same file
- historical docs references

Repo search did **not** find:

- dashboard/frontend callers
- API client callers
- tests exercising this endpoint directly

### Interpretation

This looks like a legacy surface that may already be unused.

But repo silence is not the same as production silence. A manual caller, third-party script, or unpublished client could still exist.

### Recommendation

Treat this as a candidate for the **first real Ship O deletion once usage is proven zero**, because:

- it appears isolated
- it has no visible first-party callers
- it is smaller blast radius than flag-off compatibility or pre-booking scaffolding

### Required next proof

Before deletion:

1. confirm no production caller in logs/observability
2. confirm no external dashboard dependency
3. then delete endpoint + schema types + related `ConciergeRunner` decision path in one focused commit

### Result

- **Promising first delete candidate**
- but not deletable on repo search alone

---

## A3. `/voice/concierge` non-prod legacy endpoint

### Current state

`app/api/v1/endpoints/voice.py::voice_concierge(...)`:

- is explicitly marked `[NON-PROD]`
- returns `503` in production and staging
- still calls `get_concierge_runner()` in development-mode paths

### Interpretation

This is not a production guest runtime path.

That makes it much lower risk than the other Target A sub-questions. But it still needs an explicit call:

- do we want to preserve a development-only legacy voice harness?
- or do we want to retire it and force all future testing through the Brain/session path?

### Recommendation

This is the best **early retirement candidate** within Target A, provided the team no longer relies on it for local experimentation.

If retired, the replacement stance should be explicit:

- local testing uses Brain-backed channel/session seams, not legacy voice

### Required next proof

Before deletion:

1. confirm no dev workflow still depends on this endpoint
2. if not, delete the endpoint in a focused non-prod cleanup commit

### Result

- **Likely deletable before the rest of Target A**
- but requires one final dev-workflow confirmation

---

## Bottom line

Target A should not be executed as one bundled cleanup.

Recommended order:

1. `/voice/concierge` dev-only retirement decision
2. `/concierge/decision` usage confirmation
3. flag-off compatibility decision last

That order keeps the highest-risk architectural rollback question until last and lets the smallest, most isolated legacy surfaces move first if the evidence supports it.
