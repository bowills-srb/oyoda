"""
PMS Connectors Module

Provides unified interface to Property Management Systems:
- Escapia (Vrbo) - Popular in 30A, Gulf Coast
- Guesty - Professional property managers
- Track (TrackHS) - Popular in 30A, strong owner portal
- Hostaway - Growing mid-market PMS
- Streamline - Enterprise operators
- Lodgify - Small to mid-size operators
- OwnerRez - Independent hosts

Architecture:
    Operator → PMS Connector → Canonical Schema → Knowledge Base
"""

# Base classes and canonical models
from app.services.connectors.pms_connectors import (
    PMSProvider,
    PMSAuthScheme,
    PMSMessageTransport,
    PMSReadiness,
    PMSCredentialFieldSpec,
    PMSConnectorCapabilities,
    PMSConnectorContract,
    PMS_PROVIDER_CONTRACTS,
    PMSConnector,
    PMSConnectorFactory,
    CanonicalListing,
    CanonicalBooking,
    CanonicalCalendarDay,
    CanonicalOperations,
    OperatorFootprint,
    FootprintBuilder,
    PMSIngestionService,
)

# Full connector implementations
from app.services.connectors.escapia_connector import EscapiaConnectorV2
from app.services.connectors.guesty_connector import GuestyConnectorV2
from app.services.connectors.track_connector import TrackConnector

# Sync services
from app.services.connectors.escapia_sync import (
    EscapiaSyncService,
    EscapiaSyncResult,
    get_escapia_sync_service,
)

# Integration registry (DB persistence)
from app.services.connectors.integration_registry import (
    IntegrationRegistryService,
    get_integration_registry_service,
)

# Integration gateway / credential store
from app.services.connectors.integration_gateway import (
    IntegrationProvider,
    IntegrationCredentialStore,
    get_integration_credential_store,
)


# Register all connectors with the factory
def _register_connectors():
    """Register all connector implementations."""
    PMSConnectorFactory.register(PMSProvider.ESCAPIA, EscapiaConnectorV2, PMS_PROVIDER_CONTRACTS[PMSProvider.ESCAPIA])
    PMSConnectorFactory.register(PMSProvider.GUESTY, GuestyConnectorV2, PMS_PROVIDER_CONTRACTS[PMSProvider.GUESTY])
    PMSConnectorFactory.register(PMSProvider.TRACK, TrackConnector, PMS_PROVIDER_CONTRACTS[PMSProvider.TRACK])
    # Hostaway, Streamline, etc. use the base stubs for now


_register_connectors()


__all__ = [
    # Enums and base classes
    "PMSProvider",
    "PMSAuthScheme",
    "PMSMessageTransport",
    "PMSReadiness",
    "PMSCredentialFieldSpec",
    "PMSConnectorCapabilities",
    "PMSConnectorContract",
    "PMS_PROVIDER_CONTRACTS",
    "PMSConnector",
    "PMSConnectorFactory",
    
    # Canonical models
    "CanonicalListing",
    "CanonicalBooking",
    "CanonicalCalendarDay",
    "CanonicalOperations",
    "OperatorFootprint",
    
    # Utilities
    "FootprintBuilder",
    "PMSIngestionService",
    
    # Connector implementations
    "EscapiaConnectorV2",
    "GuestyConnectorV2",
    "TrackConnector",
    
    # Sync services
    "EscapiaSyncService",
    "EscapiaSyncResult",
    "get_escapia_sync_service",
    
    # Integration registry
    "IntegrationRegistryService",
    "get_integration_registry_service",
    
    # Gateway / credential store
    "IntegrationProvider",
    "IntegrationCredentialStore",
    "get_integration_credential_store",
]
