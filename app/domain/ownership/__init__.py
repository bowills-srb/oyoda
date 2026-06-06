"""
Domain: Ownership - Pure Models.

Owner and property relationship models.
No FastAPI. No DB sessions. No external API calls.

This layer represents:
- Owner identity and portfolio
- Property ownership linkage
- Ownership confidence scoring
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional, Set
from uuid import UUID, uuid4


# =============================================================================
# OWNER MODELS
# =============================================================================

class OwnerType(str, Enum):
    """Type of property owner."""
    INDIVIDUAL = "individual"
    JOINT = "joint"  # Multiple individuals
    LLC = "llc"
    TRUST = "trust"
    CORPORATION = "corporation"
    PARTNERSHIP = "partnership"
    ESTATE = "estate"
    UNKNOWN = "unknown"


class OwnerIntent(str, Enum):
    """Inferred owner intent."""
    PRIMARY_RESIDENCE = "primary_residence"
    SECOND_HOME = "second_home"
    INVESTMENT_STR = "investment_str"
    INVESTMENT_LTR = "investment_ltr"
    VACANT = "vacant"
    UNKNOWN = "unknown"


@dataclass
class OwnerIdentity:
    """Core owner identity."""
    owner_id: UUID
    owner_type: OwnerType
    
    # For individuals
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    
    # For entities
    entity_name: Optional[str] = None
    
    # Mailing address (often different from property)
    mailing_address: Optional[str] = None
    mailing_city: Optional[str] = None
    mailing_state: Optional[str] = None
    mailing_zip: Optional[str] = None
    
    @property
    def display_name(self) -> str:
        """Get display name for owner."""
        if self.entity_name:
            return self.entity_name
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        if self.last_name:
            return self.last_name
        return "Unknown Owner"
    
    @property
    def is_entity(self) -> bool:
        """Check if owner is a business entity."""
        return self.owner_type in {
            OwnerType.LLC, 
            OwnerType.TRUST, 
            OwnerType.CORPORATION,
            OwnerType.PARTNERSHIP,
        }


@dataclass
class ContactMethod:
    """A single contact method for an owner."""
    contact_type: str  # email, phone, mail
    value: str
    source: str  # tax_records, enrichment, user_provided
    confidence: float  # 0-1
    verified: bool = False
    do_not_contact: bool = False
    last_verified: Optional[datetime] = None


@dataclass
class Owner:
    """Complete owner profile."""
    identity: OwnerIdentity
    contacts: List[ContactMethod] = field(default_factory=list)
    
    # Portfolio
    property_ids: Set[UUID] = field(default_factory=set)
    
    # Inferred attributes
    inferred_intent: OwnerIntent = OwnerIntent.UNKNOWN
    intent_confidence: float = 0.0
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def portfolio_size(self) -> int:
        """Number of properties owned."""
        return len(self.property_ids)
    
    @property
    def best_email(self) -> Optional[str]:
        """Get highest confidence email."""
        emails = [c for c in self.contacts if c.contact_type == "email" and not c.do_not_contact]
        if not emails:
            return None
        return max(emails, key=lambda c: c.confidence).value
    
    @property
    def best_phone(self) -> Optional[str]:
        """Get highest confidence phone."""
        phones = [c for c in self.contacts if c.contact_type == "phone" and not c.do_not_contact]
        if not phones:
            return None
        return max(phones, key=lambda c: c.confidence).value
    
    @property
    def is_contactable(self) -> bool:
        """Check if owner has valid contact methods."""
        return any(
            c for c in self.contacts 
            if not c.do_not_contact and c.confidence > 0.5
        )


# =============================================================================
# OWNERSHIP LINKAGE
# =============================================================================

class OwnershipSource(str, Enum):
    """Source of ownership information."""
    TAX_ASSESSOR = "tax_assessor"
    DEED_RECORDS = "deed_records"
    GIS_PARCEL = "gis_parcel"
    UTILITY_RECORDS = "utility_records"
    HOMESTEAD_EXEMPTION = "homestead_exemption"
    MORTGAGE_LIEN = "mortgage_lien"
    HOA_REGISTRY = "hoa_registry"
    USER_PROVIDED = "user_provided"
    INFERRED = "inferred"


@dataclass
class OwnerPropertyLink:
    """
    Link between an owner and a property.
    
    This is the core relationship that enables BD.
    """
    owner_id: UUID
    property_id: UUID
    
    # Confidence
    confidence: float  # 0-1
    source_types: List[OwnershipSource] = field(default_factory=list)
    
    # Ownership details
    ownership_pct: float = 1.0  # For partial ownership
    acquisition_date: Optional[date] = None
    acquisition_price: Optional[float] = None
    
    # Current status
    is_primary_residence: Optional[bool] = None
    is_rental: Optional[bool] = None
    is_vacant: Optional[bool] = None
    
    # Metadata
    first_seen: datetime = field(default_factory=datetime.utcnow)
    last_verified: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def is_high_confidence(self) -> bool:
        """Check if link is high confidence."""
        return self.confidence >= 0.8 and len(self.source_types) >= 2
    
    @property
    def years_owned(self) -> Optional[float]:
        """Calculate years of ownership."""
        if not self.acquisition_date:
            return None
        days = (date.today() - self.acquisition_date).days
        return days / 365.25


# =============================================================================
# OWNERSHIP SCORING
# =============================================================================

def compute_ownership_confidence(
    sources: List[OwnershipSource],
    name_match_score: float = 1.0,
    address_match_score: float = 1.0,
) -> float:
    """
    Compute confidence score for ownership linkage.
    
    Pure function - no IO.
    
    Args:
        sources: List of sources confirming ownership
        name_match_score: How well owner name matches across sources (0-1)
        address_match_score: How well address matches across sources (0-1)
        
    Returns:
        Confidence score 0-1
    """
    if not sources:
        return 0.0
    
    # Source weights
    source_weights = {
        OwnershipSource.TAX_ASSESSOR: 0.95,
        OwnershipSource.DEED_RECORDS: 0.95,
        OwnershipSource.GIS_PARCEL: 0.85,
        OwnershipSource.UTILITY_RECORDS: 0.70,
        OwnershipSource.HOMESTEAD_EXEMPTION: 0.90,
        OwnershipSource.MORTGAGE_LIEN: 0.85,
        OwnershipSource.HOA_REGISTRY: 0.75,
        OwnershipSource.USER_PROVIDED: 0.60,
        OwnershipSource.INFERRED: 0.40,
    }
    
    # Base confidence from best source
    best_source_confidence = max(source_weights.get(s, 0.5) for s in sources)
    
    # Bonus for multiple sources
    multi_source_bonus = min(0.15, (len(sources) - 1) * 0.05)
    
    # Apply match quality
    match_factor = (name_match_score + address_match_score) / 2
    
    confidence = (best_source_confidence + multi_source_bonus) * match_factor
    
    return min(1.0, max(0.0, confidence))


def infer_owner_intent(
    is_primary_residence: Optional[bool],
    is_rental: Optional[bool],
    mailing_matches_property: bool,
    has_homestead_exemption: bool,
    owner_portfolio_size: int,
) -> tuple[OwnerIntent, float]:
    """
    Infer owner intent from available signals.
    
    Pure function - no IO.
    
    Returns:
        Tuple of (inferred intent, confidence)
    """
    # Strong signals
    if has_homestead_exemption and mailing_matches_property:
        return OwnerIntent.PRIMARY_RESIDENCE, 0.95
    
    if is_rental is True:
        # Check if STR or LTR based on other signals
        # For now, assume STR if in vacation market (would need market context)
        return OwnerIntent.INVESTMENT_STR, 0.80
    
    if is_primary_residence is True:
        return OwnerIntent.PRIMARY_RESIDENCE, 0.85
    
    # Weaker signals
    if owner_portfolio_size > 3:
        return OwnerIntent.INVESTMENT_STR, 0.60
    
    if not mailing_matches_property:
        return OwnerIntent.SECOND_HOME, 0.50
    
    if mailing_matches_property:
        return OwnerIntent.PRIMARY_RESIDENCE, 0.60
    
    return OwnerIntent.UNKNOWN, 0.0


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Owner models
    "OwnerType",
    "OwnerIntent",
    "OwnerIdentity",
    "ContactMethod",
    "Owner",
    
    # Ownership linkage
    "OwnershipSource",
    "OwnerPropertyLink",
    
    # Computations
    "compute_ownership_confidence",
    "infer_owner_intent",
]
