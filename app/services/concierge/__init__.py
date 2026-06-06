"""
Concierge service exports.

These are resolved lazily so importing a narrow module like
`app.services.concierge.guest_session` does not also import unrelated
database-heavy services during test collection.
"""

from importlib import import_module


_EXPORTS = {
    "ConciergeRunner": ("app.services.concierge.concierge_runner", "ConciergeRunner"),
    "ConciergeRequest": ("app.services.concierge.concierge_runner", "ConciergeRequest"),
    "ConciergeReply": ("app.services.concierge.concierge_runner", "ConciergeReply"),
    "classify_intent": ("app.services.concierge.concierge_runner", "classify_intent"),
    "get_concierge_runner": ("app.services.concierge.concierge_runner", "get_concierge_runner"),
    "ConciergeMaintenanceService": ("app.services.concierge.maintenance_service", "ConciergeMaintenanceService"),
    "get_concierge_maintenance_service": ("app.services.concierge.maintenance_service", "get_concierge_maintenance_service"),
    "ConciergeBDInsightService": ("app.services.concierge.bd_insight_service", "ConciergeBDInsightService"),
    "get_concierge_bd_insight_service": ("app.services.concierge.bd_insight_service", "get_concierge_bd_insight_service"),
    "GuestSession": ("app.services.concierge.guest_session", "GuestSession"),
    "GuestSessionManager": ("app.services.concierge.guest_session", "GuestSessionManager"),
    "SessionPhase": ("app.services.concierge.guest_session", "SessionPhase"),
    "build_concierge_context": ("app.services.concierge.guest_session", "build_concierge_context"),
    "build_system_prompt": ("app.services.concierge.guest_session", "build_system_prompt"),
    "get_session_manager": ("app.services.concierge.guest_session", "get_session_manager"),
    "EscalationService": ("app.services.concierge.escalation_service", "EscalationService"),
    "EscalationTicket": ("app.services.concierge.escalation_service", "EscalationTicket"),
    "EscalationPriority": ("app.services.concierge.escalation_service", "EscalationPriority"),
    "EscalationReason": ("app.services.concierge.escalation_service", "EscalationReason"),
    "EscalationStatus": ("app.services.concierge.escalation_service", "EscalationStatus"),
    "EscalationDetector": ("app.services.concierge.escalation_service", "EscalationDetector"),
    "get_escalation_service": ("app.services.concierge.escalation_service", "get_escalation_service"),
    "GuestNotificationService": ("app.services.concierge.notification_service", "GuestNotificationService"),
    "NotificationType": ("app.services.concierge.notification_service", "NotificationType"),
    "get_notification_service": ("app.services.concierge.notification_service", "get_notification_service"),
    "DiningReservationService": ("app.services.concierge.dining_service", "DiningReservationService"),
    "DiningAvailability": ("app.services.concierge.dining_service", "DiningAvailability"),
    "DiningReservationResult": ("app.services.concierge.dining_service", "DiningReservationResult"),
    "get_dining_service": ("app.services.concierge.dining_service", "get_dining_service"),
    "EventPlanningService": ("app.services.concierge.event_planning_service", "EventPlanningService"),
    "get_event_planning_service": ("app.services.concierge.event_planning_service", "get_event_planning_service"),
    "is_event_planning_question": ("app.services.concierge.event_planning_service", "is_event_planning_question"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
