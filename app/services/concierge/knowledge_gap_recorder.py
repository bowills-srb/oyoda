"""Legacy import path for canonical knowledge-gap recording.

Kept as a thin compatibility shim that forwards to the brain-owned
implementation in
`app/services/messaging_brain/knowledge/gap_recorder.py`. Several callers
still import from this module; they will be rewired or deleted with the
legacy concierge runtime in Phase 4/7. This shim exists so the
`knowledge_service.py` deletion can land without those callers breaking.

Do NOT add new imports of this module. New code should import from
`app.services.messaging_brain.knowledge` directly.
"""

from app.services.messaging_brain.knowledge.gap_recorder import (
    record_gap_async,
    schedule_gap_record,
)

__all__ = ["record_gap_async", "schedule_gap_record"]
