"""
Domain: Documents - Pure Models.

Document-extracted property evidence and profiles.
No FastAPI. No DB sessions. No external API calls.

This layer represents:
- Document types and classification
- Extracted facts from documents
- Property evidence with confidence
- PropertyProfile (aggregated, actionable)
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4


# =============================================================================
# DOCUMENT TYPES
# =============================================================================

class DocumentType(str, Enum):
    """Types of property-related documents."""
    LEASE = "lease"
    APPRAISAL = "appraisal"
    HOA_RULES = "hoa_rules"
    HOA_FINANCIALS = "hoa_financials"
    INSURANCE_POLICY = "insurance_policy"
    RENT_ROLL = "rent_roll"
    PURCHASE_AGREEMENT = "purchase_agreement"
    CLOSING_STATEMENT = "closing_statement"
    TAX_ASSESSMENT = "tax_assessment"
    PERMIT = "permit"
    UTILITY_BILL = "utility_bill"
    MANAGEMENT_AGREEMENT = "management_agreement"
    PRO_FORMA = "pro_forma"
    LISTING_DESCRIPTION = "listing_description"
    OWNER_NOTES = "owner_notes"
    PHOTO = "photo"
    OTHER = "other"


class ExtractionStatus(str, Enum):
    """Status of document extraction."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


# =============================================================================
# EVIDENCE TYPE (Master Spec Requirement)
# =============================================================================

class EvidenceType(str, Enum):
    """
    Category of evidence per master spec.
    
    Evidence is never wrong — it's just uncertain.
    """
    PHYSICAL = "physical"        # beds, baths, sqft, year_built
    USAGE = "usage"              # current use, rental history, STR activity
    OWNERSHIP = "ownership"      # owner type, tenure, portfolio
    MARKET = "market"            # comps, ADR proxy, occupancy signals
    REGULATORY = "regulatory"    # zoning, STR permits, HOA rules
    FINANCIAL = "financial"      # rent rolls, pro forma, assessed value
    DOCUMENT = "document"        # parsed from uploaded documents


# =============================================================================
# EXTRACTED FIELDS
# =============================================================================

class ExtractedFieldType(str, Enum):
    """Types of fields that can be extracted."""
    # Physical
    BEDS = "beds"
    BATHS = "baths"
    SQFT = "sqft"
    YEAR_BUILT = "year_built"
    LOT_SIZE = "lot_size"
    PROPERTY_TYPE = "property_type"
    
    # Financial
    RENT_AMOUNT = "rent_amount"
    SECURITY_DEPOSIT = "security_deposit"
    PURCHASE_PRICE = "purchase_price"
    ASSESSED_VALUE = "assessed_value"
    HOA_FEES = "hoa_fees"
    INSURANCE_PREMIUM = "insurance_premium"
    MANAGEMENT_FEE = "management_fee"
    ADR_PROXY = "adr_proxy"
    
    # Lease terms
    LEASE_START = "lease_start"
    LEASE_END = "lease_end"
    LEASE_TERM_MONTHS = "lease_term_months"
    TENANT_NAME = "tenant_name"
    
    # Usage
    CURRENT_USE = "current_use"
    RENTAL_HISTORY = "rental_history"
    STR_ACTIVITY = "str_activity"
    
    # Ownership
    OWNER_TYPE = "owner_type"
    OWNER_NAME = "owner_name"
    ACQUISITION_DATE = "acquisition_date"
    
    # Regulatory
    ZONING = "zoning"
    STR_ALLOWED = "str_allowed"
    MIN_RENTAL_PERIOD = "min_rental_period"
    OCCUPANCY_LIMIT = "occupancy_limit"
    
    # Quality
    FURNISHING_LEVEL = "furnishing_level"
    FINISH_QUALITY = "finish_quality"
    
    # Amenities
    POOL = "pool"
    HOT_TUB = "hot_tub"
    WATERFRONT = "waterfront"
    
    # Other
    PET_POLICY = "pet_policy"
    NOTES = "notes"
    CUSTOM = "custom"


@dataclass
class ExtractedField:
    """A single field extracted from a document."""
    field_type: ExtractedFieldType
    value: Any
    confidence: float
    extraction_method: str  # ocr, nlp, regex, manual
    page_number: Optional[int] = None
    bounding_box: Optional[Dict[str, float]] = None
    surrounding_text: Optional[str] = None
    
    @property
    def is_high_confidence(self) -> bool:
        return self.confidence >= 0.85


# =============================================================================
# DOCUMENT MODEL
# =============================================================================

@dataclass
class PropertyDocument:
    """A document associated with a property."""
    document_id: UUID
    property_id: UUID
    document_type: DocumentType
    document_type_confidence: float
    filename: str
    mime_type: str
    file_size_bytes: int
    status: ExtractionStatus
    extracted_fields: List[ExtractedField] = field(default_factory=list)
    uploaded_by: Optional[UUID] = None
    uploaded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: Optional[datetime] = None
    ocr_quality: Optional[float] = None
    
    def get_field(self, field_type: ExtractedFieldType) -> Optional[ExtractedField]:
        for f in self.extracted_fields:
            if f.field_type == field_type:
                return f
        return None
    
    def get_field_value(self, field_type: ExtractedFieldType, default: Any = None) -> Any:
        f = self.get_field(field_type)
        return f.value if f else default


# =============================================================================
# PROPERTY EVIDENCE (Atomic, Append-Only per Master Spec)
# =============================================================================

@dataclass
class PropertyEvidence:
    """
    Atomic evidence about a property.
    
    Per master spec:
    - Evidence is never deleted
    - Conflicts are allowed
    - Confidence decays over time
    - No inference logic lives here
    """
    evidence_id: UUID = field(default_factory=uuid4)
    property_id: UUID = None
    
    # Category (per spec)
    evidence_type: EvidenceType = EvidenceType.PHYSICAL
    
    # The actual field and value
    field_name: ExtractedFieldType = None  # Renamed from 'field' to avoid collision
    value: Any = None
    
    # Source attribution
    source: str = ""  # county_records, mls, scrape_airbnb, operator_upload, document_parse
    confidence: float = 0.0
    
    # Temporal
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    
    # Optional
    notes: Optional[str] = None
    source_document_id: Optional[UUID] = None
    
    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc) > self.expires_at
    
    @property
    def age_days(self) -> int:
        return (datetime.now(timezone.utc) - self.observed_at).days


# =============================================================================
# PROPERTY PROFILE (Aggregated, Actionable per Master Spec)
# =============================================================================

@dataclass
class CanonicalAttributes:
    """Known physical attributes."""
    beds: Optional[int] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    year_built: Optional[int] = None
    zoning: Optional[str] = None
    property_type: Optional[str] = None


class FurnishingQuality(str, Enum):
    """Inferred furnishing quality."""
    LOW = "low"
    MID = "mid"
    HIGH = "high"
    UNKNOWN = "unknown"


class OperatorReadiness(str, Enum):
    """How ready is this property for STR?"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LikelyUse(str, Enum):
    """Inferred current use."""
    PRIMARY = "primary"
    LTR = "ltr"
    STR = "str"
    MIXED = "mixed"
    VACANT = "vacant"
    UNKNOWN = "unknown"


@dataclass
class InferredTraits:
    """Traits inferred from evidence."""
    furnishing_quality: FurnishingQuality = FurnishingQuality.UNKNOWN
    operator_readiness: OperatorReadiness = OperatorReadiness.MEDIUM
    likely_use: LikelyUse = LikelyUse.UNKNOWN


@dataclass
class EvidenceSummary:
    """Summary of evidence quality."""
    strong_signals: List[str] = field(default_factory=list)
    weak_signals: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    total_evidence_count: int = 0


# =============================================================================
# PROPERTY PROFILE COMPONENTS (for Concierge)
# =============================================================================

@dataclass
class PropertyAmenities:
    """
    Property amenities.
    
    Used by concierge for guest questions.
    """
    # Outdoor
    pool: bool = False
    heated_pool: bool = False
    hot_tub: bool = False
    outdoor_shower: bool = False
    grill: bool = False
    fire_pit: bool = False
    
    # Indoor
    wifi: bool = True
    smart_tv: bool = False
    game_room: bool = False
    home_theater: bool = False
    
    # Family
    kids_friendly: bool = False
    highchair: bool = False
    crib: bool = False
    pack_n_play: bool = False
    
    # Beach/Water
    beach_access: bool = False
    kayaks: bool = False
    paddleboards: bool = False
    fishing_gear: bool = False
    
    # Transportation
    golf_cart: bool = False
    bikes: bool = False
    
    # Work
    workspace: bool = False
    
    # Other
    ev_charger: bool = False
    elevator: bool = False
    
    def to_list(self) -> List[str]:
        """Get list of available amenities."""
        amenities = []
        for key, value in self.__dict__.items():
            if value is True:
                amenities.append(key.replace("_", " ").title())
        return amenities


@dataclass
class PropertyRules:
    """
    Property rules and policies.
    
    Used by concierge for guest questions.
    """
    # Pets
    pets_allowed: bool = False
    pet_fee: float = 0.0
    pet_restrictions: Optional[str] = None
    
    # Smoking
    smoking_allowed: bool = False
    
    # Noise
    quiet_hours_start: Optional[str] = "10:00 PM"
    quiet_hours_end: Optional[str] = "7:00 AM"
    
    # Occupancy
    max_occupancy: Optional[int] = None
    
    # Events
    events_allowed: bool = False
    parties_allowed: bool = False
    
    # Age
    minimum_age: int = 25
    
    # Other
    additional_rules: List[str] = field(default_factory=list)
    
    @property
    def quiet_hours_str(self) -> str:
        if self.quiet_hours_start and self.quiet_hours_end:
            return f"{self.quiet_hours_start} - {self.quiet_hours_end}"
        return "Not specified"


@dataclass
class PropertyAccess:
    """
    Property access information.
    
    Used by concierge for guest questions.
    """
    # Lock
    lock_type: str = "smart_lock"  # smart_lock, keypad, lockbox, key
    code_policy: str = "time_bound"  # time_bound, static, unique_per_guest
    
    # WiFi
    wifi_network: Optional[str] = None
    wifi_password: Optional[str] = None
    
    # Parking
    parking_type: str = "driveway"  # driveway, garage, street, lot
    parking_spaces: int = 2
    parking_instructions: Optional[str] = None
    
    # Entry
    entry_instructions: Optional[str] = None
    
    # Contacts
    emergency_contact: Optional[str] = None
    maintenance_contact: Optional[str] = None


@dataclass 
class PropertyLocation:
    """
    Property location details.
    
    Used by concierge for local recommendations.
    """
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    
    # Distances (in miles)
    beach_distance: Optional[float] = None
    downtown_distance: Optional[float] = None
    airport_distance: Optional[float] = None
    grocery_distance: Optional[float] = None
    
    # Nearby
    nearby_attractions: List[str] = field(default_factory=list)
    nearby_restaurants: List[str] = field(default_factory=list)
    
    # Area description
    neighborhood_description: Optional[str] = None


@dataclass
class OperationalConstraints:
    """
    Operational constraints for the property.
    
    Used by decision engine for late checkout, early checkin.
    """
    # Standard times
    check_in_time: str = "4:00 PM"
    check_out_time: str = "11:00 AM"
    
    # Flexibility
    early_checkin_available: bool = False
    early_checkin_earliest: Optional[str] = None
    early_checkin_fee: float = 0.0
    
    late_checkout_available: bool = True
    late_checkout_latest: Optional[str] = "2:00 PM"
    late_checkout_fee: float = 0.0
    late_checkout_policy: str = "conditional"  # always, conditional, never
    
    # Turnover
    minimum_turnover_hours: float = 4.0
    preferred_turnover_hours: float = 5.0


@dataclass
class PropertyProfile:
    """
    Aggregated, actionable property profile.
    
    Per master spec:
    - This is the first operator-facing object
    - Answers: "What do we think we know, and how sure are we?"
    - Generated automatically, updated continuously
    - Never requires operator babysitting
    
    UNIFIED for BD + Concierge + Analytics:
    - physical: beds, baths, sqft (for projections)
    - amenities: pool, wifi, etc (for concierge)
    - rules: pets, quiet hours, etc (for concierge)
    - access: lock codes, wifi password (for concierge)
    - location: nearby attractions (for concierge)
    - operational_constraints: check-in/out times (for decision engine)
    
    Profiles are hypotheses, not facts.
    """
    property_id: UUID
    
    # === PHYSICAL ATTRIBUTES (for Analytics/BD) ===
    canonical_attributes: CanonicalAttributes = field(default_factory=CanonicalAttributes)
    
    # === INFERRED TRAITS (for Analytics/BD) ===
    inferred_traits: InferredTraits = field(default_factory=InferredTraits)
    
    # === AMENITIES (for Concierge) ===
    amenities: PropertyAmenities = field(default_factory=PropertyAmenities)
    
    # === RULES (for Concierge) ===
    rules: PropertyRules = field(default_factory=PropertyRules)
    
    # === ACCESS (for Concierge) ===
    access: PropertyAccess = field(default_factory=PropertyAccess)
    
    # === LOCATION (for Concierge) ===
    location: PropertyLocation = field(default_factory=PropertyLocation)
    
    # === OPERATIONAL CONSTRAINTS (for Decision Engine) ===
    operational_constraints: OperationalConstraints = field(default_factory=OperationalConstraints)
    
    # === EVIDENCE QUALITY ===
    evidence_summary: EvidenceSummary = field(default_factory=EvidenceSummary)
    
    # === CONFIDENCE ===
    confidence_score: float = 0.0
    
    # === MISSING DATA ===
    missing_data_flags: List[str] = field(default_factory=list)
    
    # === METADATA ===
    generated_at: datetime = field(default_factory=datetime.utcnow)
    last_updated: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def is_projection_ready(self) -> bool:
        """Check if we have enough data to project."""
        attrs = self.canonical_attributes
        return (
            attrs.beds is not None and
            attrs.baths is not None and
            self.confidence_score >= 0.4
        )
    
    @property
    def is_concierge_ready(self) -> bool:
        """Check if we have enough data for concierge."""
        return (
            self.access.wifi_network is not None and
            self.operational_constraints.check_in_time is not None
        )
    
    def get_amenity_list(self) -> List[str]:
        """Get list of available amenities."""
        return self.amenities.to_list()


# =============================================================================
# EVIDENCE BUNDLE
# =============================================================================

@dataclass
class PropertyEvidenceBundle:
    """Collection of evidence for a property."""
    property_id: UUID
    evidence: List[PropertyEvidence] = field(default_factory=list)
    overall_confidence: float = 0.0
    evidence_types_present: Set[EvidenceType] = field(default_factory=set)
    
    def get_evidence_for_field(self, field_name: ExtractedFieldType) -> List[PropertyEvidence]:
        return [e for e in self.evidence if e.field_name == field_name]
    
    def get_best_evidence(self, field_name: ExtractedFieldType) -> Optional[PropertyEvidence]:
        matches = self.get_evidence_for_field(field_name)
        if not matches:
            return None
        # Prefer non-expired, highest confidence
        valid = [e for e in matches if not e.is_expired]
        if not valid:
            valid = matches
        return max(valid, key=lambda e: e.confidence)
    
    def get_value(self, field_name: ExtractedFieldType, default: Any = None) -> Any:
        evidence = self.get_best_evidence(field_name)
        return evidence.value if evidence else default


# =============================================================================
# PROFILE GENERATION (Pure Functions)
# =============================================================================

def generate_property_profile(
    property_id: UUID,
    evidence_bundle: PropertyEvidenceBundle,
) -> PropertyProfile:
    """
    Generate a PropertyProfile from evidence.
    
    Pure function - no IO.
    """
    # Extract canonical attributes
    canonical = CanonicalAttributes(
        beds=evidence_bundle.get_value(ExtractedFieldType.BEDS),
        baths=evidence_bundle.get_value(ExtractedFieldType.BATHS),
        sqft=evidence_bundle.get_value(ExtractedFieldType.SQFT),
        year_built=evidence_bundle.get_value(ExtractedFieldType.YEAR_BUILT),
        zoning=evidence_bundle.get_value(ExtractedFieldType.ZONING),
        property_type=evidence_bundle.get_value(ExtractedFieldType.PROPERTY_TYPE),
    )
    
    # Infer traits
    furnishing = evidence_bundle.get_value(ExtractedFieldType.FURNISHING_LEVEL)
    inferred = InferredTraits(
        furnishing_quality=FurnishingQuality(furnishing) if furnishing else FurnishingQuality.UNKNOWN,
        operator_readiness=OperatorReadiness.MEDIUM,
        likely_use=LikelyUse.UNKNOWN,
    )
    
    # Analyze evidence quality
    strong = []
    weak = []
    conflicts = []
    
    for e in evidence_bundle.evidence:
        if e.confidence >= 0.8:
            strong.append(f"{e.field_name.value}: {e.source}")
        elif e.confidence >= 0.5:
            weak.append(f"{e.field_name.value}: {e.source}")
    
    evidence_summary = EvidenceSummary(
        strong_signals=strong[:5],
        weak_signals=weak[:5],
        conflicts=conflicts,
        total_evidence_count=len(evidence_bundle.evidence),
    )
    
    # Identify missing data
    missing = []
    if canonical.beds is None:
        missing.append("beds_unknown")
    if canonical.sqft is None:
        missing.append("sqft_unknown")
    if inferred.furnishing_quality == FurnishingQuality.UNKNOWN:
        missing.append("interior_quality_unknown")
    
    # Calculate overall confidence
    confidence = evidence_bundle.overall_confidence
    if not evidence_bundle.evidence:
        confidence = 0.0
    
    return PropertyProfile(
        property_id=property_id,
        canonical_attributes=canonical,
        inferred_traits=inferred,
        evidence_summary=evidence_summary,
        confidence_score=confidence,
        missing_data_flags=missing,
    )


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Document types
    "DocumentType",
    "ExtractionStatus",
    "EvidenceType",
    "ExtractedFieldType",
    "ExtractedField",
    "PropertyDocument",
    
    # Evidence
    "PropertyEvidence",
    "PropertyEvidenceBundle",
    
    # Profile - Core
    "CanonicalAttributes",
    "FurnishingQuality",
    "OperatorReadiness",
    "LikelyUse",
    "InferredTraits",
    "EvidenceSummary",
    
    # Profile - Concierge components
    "PropertyAmenities",
    "PropertyRules",
    "PropertyAccess",
    "PropertyLocation",
    "OperationalConstraints",
    
    # Profile - Master
    "PropertyProfile",
    "generate_property_profile",
]
