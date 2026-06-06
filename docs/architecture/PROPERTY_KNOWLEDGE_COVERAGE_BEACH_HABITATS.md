# Beach Habitats Property Knowledge Coverage

Captured on 2026-05-18 against production for tenant
`e07980b2-a990-4b24-91d1-c8cb71ab70e1`.

## Result

Beach Habitats has property knowledge coverage for all 45 active properties.

- Active properties audited: `45`
- Properties with `0` knowledge entries: `0`
- Minimum entries on an active property: `28`
- Maximum entries on an active property: `41`
- Typical range: low `30s`
- Distinct `doc_type` count per property: `2` across the whole active set
- Ingestion freshness: all rows sampled were created on `2026-05-16`

## Interpretation

This is strong enough to treat Beach Habitats property knowledge as present for
draft-quality evaluation.

Implications:

- Ship 3 prompt/composer work should assume property knowledge exists and focus
  on tone, clarification behavior, and grounding discipline rather than missing
  content.
- Sparse content is not the primary explanation for the Taylor/Carri/Matthew
  draft weaknesses we reviewed.
- Future property-level canaries can use property knowledge coverage as one
  confidence input, but Beach Habitats does not currently have a coverage gap
  blocking draft-quality work.

## Top Coverage Examples

- `113BW`: `41`
- `18CC`: `39`
- `134MC`: `38`
- `119VW`: `37`
- `42WK`: `37`

## Lowest Coverage Examples

- `100SL2C`: `28`
- `HMS`: `29`
- `32PARK`: `29`
- `1151SG`: `30`
- `23FL`: `30`

## Query Shape

Coverage was measured by joining active properties to per-property counts in
`knowledge_embeddings` grouped on `property_code`.
