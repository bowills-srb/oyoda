"""Phase 4.0-A structured properties backfill wrapper.

Preserved as the operator-facing one-off entrypoint for the Beach Habitats
structured projection job. The implementation lives in
app.services.backfill.structured_property_backfill so it remains testable.
"""

from app.services.backfill.structured_property_backfill import main


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
