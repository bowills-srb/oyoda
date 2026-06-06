"""Knowledge helpers owned by the messaging brain.

Canonical tables and their owners:
  concierge_scoped_knowledge       → app/services/concierge/scoped_knowledge_service.py
                                     (relocates here in Phase 4)
  concierge_knowledge_gaps         → gap_recorder.py
  concierge_global_faq             → global_faq.py
  concierge_maintenance_events     → app/services/concierge/maintenance_service.py
                                     (relocates here in Phase 6)
"""

from .faq_answering import best_faq_answer, score_faq_match
from .gap_recorder import (
    list_gaps,
    normalize_question_key,
    record_gap,
    record_gap_async,
    resolve_property_id_from_external,
    resolve_gap,
    schedule_gap_record,
)
from .global_faq import list_global_faq, upsert_global_faq
from .historical_import import import_historical_questions

__all__ = [
    "best_faq_answer",
    "score_faq_match",
    "record_gap",
    "list_gaps",
    "resolve_gap",
    "record_gap_async",
    "schedule_gap_record",
    "normalize_question_key",
    "resolve_property_id_from_external",
    "upsert_global_faq",
    "list_global_faq",
    "import_historical_questions",
]
