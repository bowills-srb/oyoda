"""
API v1 Endpoints Package.

Business verb-oriented API endpoints:
- pricing: Rate calculations and recommendations
- market: Market intelligence and comps
- bd: Business development (rent projections, lead scoring)
- properties: Property CRUD
- normalize: Data normalization
- concierge: Guest interactions and decisions
- opportunity: BD lead scoring and ranking
- voice: Voice-based concierge (STT → Decision → TTS)
- pitch: Investment synopsis + PDF (with operator overrides)
- documents: Document upload + extraction → Evidence
- gateway: Integration credential gateway (Breezeway, Escapia, Wheelhouse)
"""

# Don't import here to avoid circular imports
# Each module is imported directly in the router

__all__ = [
    "pricing",
    "market", 
    "bd",
    "properties",
    "normalize",
    "concierge",
    "opportunity",
    "voice",
    "pitch",
    "documents",
    "gateway",
]
