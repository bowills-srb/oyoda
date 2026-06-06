"""
Compatibility bridge for legacy dashboard KB imports.

The operator dashboard moved to the scoped-knowledge-backed
DashboardKnowledgeService, but some older runtime paths and tests still
import app.services.concierge.knowledge_service.ConciergeKnowledgeService.
Keep that import path alive while delegating all dashboard KB work to the
current implementation, so we never fall back to the retired
concierge_knowledge table.
"""

from __future__ import annotations

from app.services.messaging_brain.knowledge.dashboard_kb_service import (
    DashboardKnowledgeService,
    get_dashboard_kb_service,
)


class ConciergeKnowledgeService(DashboardKnowledgeService):
    """Backward-compatible alias to the scoped-knowledge dashboard service."""


def get_concierge_knowledge_service() -> DashboardKnowledgeService:
    return get_dashboard_kb_service()


__all__ = ["ConciergeKnowledgeService", "get_concierge_knowledge_service"]
