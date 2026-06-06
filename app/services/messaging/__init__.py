"""
Messaging — layer-agnostic primitives for guest message handling.

Tier 2 of the messaging architecture (stable middle).

Responsibility: Normalize transport-layer inputs into stable contracts.
Resolve identity. Route outbound through the right channel. Persist
canonical messages. Provide platform primitives that any feature can call.

Key modules:
  identity_resolver.py     — GuestIdentityResolution dataclass and resolver
  inbound_normalizer.py    — CanonicalInboundMessage contract
  inbound_transport.py     — transport-layer normalization primitives
  inbox_adapters.py        — outbound reply adapter (Gmail, Microsoft 365)
  channel_router.py        — outbound channel selection
  message_event_store.py   — canonical message persistence
  autonomy_gate.py         — autonomy threshold primitives
  operator_alerts.py       — ALERT ROUTING PLATFORM (generic dispatcher
                             with contact resolution, escalation, OOO,
                             coverage-gap fallback). Feature-specific
                             alert consumers live in messaging_brain/
                             notifications/ (see prebooking_review_alerts.py).

What lives in OTHER tiers (do not duplicate here):
  - Inbound transport, parsers, LLM extractor:  app/services/integrations/
  - Decision logic (classify, route, compose):  app/services/messaging_brain/
  - Healers and cross-cutting workers:          app/services/agents/

Dependency rule: messaging/ may import from shared infrastructure (db,
models, config) only. It must NOT import from integrations/ (Tier 1) or
messaging_brain/ (Tier 3). This package is the stable middle — it survives
both directions of change.

Defining test: would this module still need to exist if you swapped out
the transport layer above? If you swapped out the brain below? If both
answers are yes, it belongs here.

See docs/architecture/MESSAGING_TIER_MAP.md for the full tier map and the
decision tree for where new code belongs.
"""
