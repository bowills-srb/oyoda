from __future__ import annotations

from db.models import GuestThreadModel
from db.models.concierge_sessions import ConciergeGuestSessionModel
from db.models.core import Base


def test_guest_thread_model_in_metadata_registry():
    """Verify GuestThreadModel is registered for FK metadata resolution."""
    assert "guest_threads" in Base.metadata.tables, (
        "GuestThreadModel must be registered in db/models/__init__.py "
        "for FK metadata resolution to succeed at runtime"
    )


def test_concierge_guest_session_fk_resolves_guest_threads_table():
    guest_threads = Base.metadata.tables["guest_threads"]
    guest_sessions = ConciergeGuestSessionModel.__table__
    fk = next(
        candidate
        for candidate in guest_sessions.foreign_keys
        if candidate.parent.name == "guest_thread_id"
    )

    assert fk.column.table is guest_threads
    assert GuestThreadModel.__table__ is guest_threads
