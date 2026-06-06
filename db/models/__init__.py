"""
Database ORM Models.

These map directly to the Pydantic schemas in schemas/core.py.
"""

from db.models.core import (
    # Base
    Base,
    TenantMixin,
    TimestampMixin,
    SoftDeleteMixin,
    
    # Models
    TenantModel,
    OperatorModel,
    PropertyModel,
    ListingModel,
    BookingModel,
    GuestProfileModel,
    MessageThreadModel,
    MessageModel,
    GeoPolygonModel,
    MarketSnapshotModel,
    AnalyticsResultModel,
)
from db.models.integrations import (
    IntegrationConnectionModel,
    IntegrationSyncJobModel,
    IntegrationRawRecordModel,
)
from db.models.concierge_knowledge import (
    ConciergeKnowledgeGapModel,
    ConciergeGlobalFAQModel,
    ConciergeMaintenanceEventModel,
)
from db.models.healer import HealerProposalModel
from db.models.concierge_sessions import (
    ConciergeGuestSessionModel,
    ConciergeGuestJourneyModel,
    ConciergeJourneyActivityModel,
    ConciergeMessageModel,
    ConciergeNotificationModel,
)
from db.models.guest_thread import GuestThreadModel  # noqa: F401
from db.models.concierge_dining_reservations import (
    ConciergeDiningReservationModel,
)
from db.models.documents import (
    DocumentModel,
    ExtractedFieldModel,
)

__all__ = [
    # Base
    "Base",
    "TenantMixin",
    "TimestampMixin",
    "SoftDeleteMixin",
    
    # Core Models
    "TenantModel",
    "OperatorModel",
    "PropertyModel",
    "ListingModel",
    "BookingModel",
    "GuestProfileModel",
    "MessageThreadModel",
    "MessageModel",
    "GeoPolygonModel",
    "MarketSnapshotModel",
    "AnalyticsResultModel",
    
    # Integrations
    "IntegrationConnectionModel",
    "IntegrationSyncJobModel",
    "IntegrationRawRecordModel",
    
    # Concierge Knowledge
    "ConciergeKnowledgeGapModel",
    "ConciergeGlobalFAQModel",
    "ConciergeMaintenanceEventModel",
    "HealerProposalModel",
    
    # Concierge Sessions & Journeys
    "ConciergeGuestSessionModel",
    "ConciergeGuestJourneyModel",
    "ConciergeJourneyActivityModel",
    "ConciergeMessageModel",
    "ConciergeNotificationModel",
    "GuestThreadModel",
    # Concierge Dining
    "ConciergeDiningReservationModel",
    # Documents
    "DocumentModel",
    "ExtractedFieldModel",
]
