"""
BD (Business Development) Services Package.

This package provides all BD-facing document generation:
- Pro forma PDFs
- Investment synopses
- Pitch decks
- Property reports

NEW in v2.0:
- SignalBackedSynopsisGenerator for signal-attributed documents
- All projections now include confidence bands
- Full attribution trail for institutional partners
"""

# Signal-backed synopsis (v2.0)
from app.services.bd.signal_synopsis import (
    SignalBackedSynopsisGenerator,
    PropertyData,
    SignalBackedMetric,
    generate_signal_synopsis,
)

__all__ = [
    "SignalBackedSynopsisGenerator",
    "PropertyData", 
    "SignalBackedMetric",
    "generate_signal_synopsis",
]

