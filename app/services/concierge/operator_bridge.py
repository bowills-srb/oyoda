"""
Thin bridge from concierge services into operator services.

This consolidates the shared seams while the platform transitions toward a
more event-driven module contract.
"""

from app.services.operator.prebooking_queue_service import get_prebooking_queue_service

__all__ = ["get_prebooking_queue_service"]
