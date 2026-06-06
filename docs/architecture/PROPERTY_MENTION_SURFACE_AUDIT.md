## Property Mention Surface Audit

Phase 4.3 Gap B reframed the property-mention issue as a surface coverage and
observability problem, not an LLM prompt blindness problem.

### Current Surfaces

- `subject`
  - visible to the LLM extractor through the rendered header block
  - visible to the deterministic fallback through `extract_property_name(...)`
- `latest_body`
  - visible to the LLM extractor through `plain_text`
  - visible to the fallback through `_extract_body_property_mention(...)`
- `quoted_context`
  - visible to the LLM extractor because the full email body is in prompt scope
  - previously not rescanned by the deterministic fallback after
    `dissect_thread_content(...)` split older thread content off

### Gap B Outcome

- Added `app/services/integrations/property_mention_surfaces.py` as the shared
  pure string-analysis seam for these three surfaces.
- The deterministic fallback now records which surface supplied its selected
  property mention.
- The LLM path now records which surfaces contained the extracted mention and
  whether the best deterministic surface agreed with the LLM extraction.

### Christina Worked Example

Subject:
- `Re: Payment due notice for 100 S Spooky Lane Unit 2D`

Latest body:
- asks about baby gear and beach items, but may not restate the property

Quoted context:
- may carry the original reservation/property wording even when the latest turn
  does not

With the new audit payload, normalization rows can now show whether the subject
or quoted thread carried the winning property signal, instead of forcing that
to remain implicit in LLM behavior.
