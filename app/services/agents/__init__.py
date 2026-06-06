"""
Agents — cross-cutting autonomous workers operating on signals.

Cross-cutting role in the messaging architecture (not a tier).

Responsibility: Audit, learn, propose, sync. These workers operate on a
schedule (or on external triggers) rather than as part of per-message
handling. They cross tier boundaries by design to read signals from any
tier and propose durable improvements subject to human approval.

Key modules:
  healer_agent.py           — three proposal kinds (property aliases,
                              intent classifier keywords, prefilter drop
                              patterns). See docs/architecture/HEALER_AGENT.md.
  healer_runner.py          — daily scan entry (wired via Celery beat at
                              05:00 UTC; see app.workers.tasks
                              scan_healer_proposals)
  knowledge_curator_agent.py — knowledge-base curation
  pms_sync_agent.py         — PMS data synchronization
  router_agent.py           — routing-decision agent
  escalation_handoff_agent.py — human handoff coordinator
  experiment_registry.py, concierge_health.py, agent_framework.py
  emotional_intelligence/, market_intelligence/, onboarding/,
  task_execution/           — subpackages for cross-cutting concerns

What lives in OTHER tiers (do not duplicate here):
  - Inbound transport, parsers, LLM extractor:  app/services/integrations/
  - Identity, channel router, canonical contracts, alert routing platform:
        app/services/messaging/
  - Per-message decision logic:                 app/services/messaging_brain/

Dependency rule: agents/ MAY import from any tier (integrations/,
messaging/, messaging_brain/). This is the only directory that may
legitimately reach into all three tiers, because its job is cross-cutting.

Defining test: does this worker run on a schedule or external trigger
rather than as part of per-message handling? Does it cross tier
boundaries to read signals or propose changes? If both yes, it belongs
here.

See docs/architecture/MESSAGING_TIER_MAP.md for the full tier map and the
decision tree for where new code belongs.
"""
