## Healer Agent

The Healer Agent is the deterministic-logic sibling of `KnowledgeCuratorAgent`.
It scans recent audit signals, clusters repeated disagreement patterns, and
creates operator-reviewable proposals.

The loop is:
1. Read recent `message_normalizations.parser_notes`.
2. Filter `property_mention_surface_audit` rows with `parser_path=llm_primary`
   and `agreement=false`.
3. Cluster by normalized extracted mention plus resolved property code.
4. Require `cluster_size >= 2`.
5. Upsert a `pending` row into `healer_proposals`.
6. Append `healer_proposal_recorded` back onto the evidence rows.

Current proposal kinds:
- `property_alias_suggestion`
  Approval applies immediately through `CanonicalPropertyWriteService.link_property_identity`.
- `intent_classifier_keyword_suggestion`
  Approval writes merged keyword overrides into
  `operator_settings.extra.intent_classifier_keyword_overrides`.

This mirrors the curator discipline already used by `KnowledgeCuratorAgent`:
cluster before drafting, keep the output operator-reviewable, and preserve a
full audit chain from source signal to proposed change.

The property-alias queue is intentionally adjacent to the existing
`canonical_property_link_reviews` review path rather than replacing it. The
healer contributes a new signal source; the canonical property write service
remains the authoritative mutation path.
