"""
Company model - represents a property management company (tenant).
"""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, BaseModel, SoftDeleteMixin

if TYPE_CHECKING:
    from app.models.property import Property
    from app.models.market import Market


class SubscriptionTier(str, Enum):
    """Subscription tiers for companies."""
    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class CompanyStatus(str, Enum):
    """Company account status."""
    ACTIVE = "active"
    TRIAL = "trial"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class Company(BaseModel, SoftDeleteMixin, AuditMixin):
    """
    Property management company - the tenant in our multi-tenant system.
    
    Each company has their own:
    - Properties and pro formas
    - Market definitions and rate tables
    - Users and permissions
    - Integration configurations
    """
    
    __tablename__ = "companies"
    
    # Basic Information
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    legal_name: Mapped[Optional[str]] = mapped_column(String(255))
    
    # Contact Information
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    website: Mapped[Optional[str]] = mapped_column(String(255))
    
    # Address
    address_line1: Mapped[Optional[str]] = mapped_column(String(255))
    address_line2: Mapped[Optional[str]] = mapped_column(String(255))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    state: Mapped[Optional[str]] = mapped_column(String(50))
    postal_code: Mapped[Optional[str]] = mapped_column(String(20))
    country: Mapped[str] = mapped_column(String(2), default="US")  # ISO 3166-1 alpha-2
    
    # Business Details
    tax_id: Mapped[Optional[str]] = mapped_column(String(50))  # EIN for US companies
    license_number: Mapped[Optional[str]] = mapped_column(String(100))
    
    # Subscription & Billing
    subscription_tier: Mapped[SubscriptionTier] = mapped_column(
        String(50),
        default=SubscriptionTier.FREE
    )
    status: Mapped[CompanyStatus] = mapped_column(
        String(50),
        default=CompanyStatus.TRIAL
    )
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column()
    subscription_started_at: Mapped[Optional[datetime]] = mapped_column()
    subscription_ends_at: Mapped[Optional[datetime]] = mapped_column()
    
    # Quotas (based on subscription tier)
    max_properties: Mapped[int] = mapped_column(Integer, default=10)
    max_users: Mapped[int] = mapped_column(Integer, default=3)
    max_proformas_per_month: Mapped[int] = mapped_column(Integer, default=50)
    max_ai_requests_per_month: Mapped[int] = mapped_column(Integer, default=100)
    
    # Usage Tracking
    current_property_count: Mapped[int] = mapped_column(Integer, default=0)
    current_user_count: Mapped[int] = mapped_column(Integer, default=0)
    proformas_this_month: Mapped[int] = mapped_column(Integer, default=0)
    ai_requests_this_month: Mapped[int] = mapped_column(Integer, default=0)
    usage_reset_at: Mapped[Optional[datetime]] = mapped_column()
    
    # Default Settings
    default_commission_rate: Mapped[float] = mapped_column(
        Numeric(5, 4),
        default=0.20  # 20%
    )
    default_currency: Mapped[str] = mapped_column(String(3), default="USD")
    timezone: Mapped[str] = mapped_column(String(50), default="America/New_York")
    
    # Branding
    logo_url: Mapped[Optional[str]] = mapped_column(String(500))
    primary_color: Mapped[Optional[str]] = mapped_column(String(7))  # Hex color
    secondary_color: Mapped[Optional[str]] = mapped_column(String(7))
    
    # Feature Flags (company-specific)
    features_enabled: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default='{}'
    )
    
    # Integration Settings
    integration_settings: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default='{}'
    )
    
    # Metadata
    extra_data: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default='{}'
    )
    
    # Relationships
    properties: Mapped[List["Property"]] = relationship(
        "Property",
        back_populates="company"
    )
    
    markets: Mapped[List["Market"]] = relationship(
        "Market",
        back_populates="company"
    )
    
    users: Mapped[List["User"]] = relationship(
        "User",
        back_populates="company"
    )
    
    def __repr__(self) -> str:
        return f"<Company(id={self.id}, name='{self.name}', tier={self.subscription_tier})>"
    
    @property
    def is_active(self) -> bool:
        """Check if the company account is active."""
        return self.status == CompanyStatus.ACTIVE and not self.is_deleted
    
    @property
    def is_trial(self) -> bool:
        """Check if the company is in trial period."""
        if self.status != CompanyStatus.TRIAL:
            return False
        if self.trial_ends_at and self.trial_ends_at < datetime.utcnow():
            return False
        return True
    
    def can_add_property(self) -> bool:
        """Check if the company can add more properties."""
        return self.current_property_count < self.max_properties
    
    def can_add_user(self) -> bool:
        """Check if the company can add more users."""
        return self.current_user_count < self.max_users
    
    def can_generate_proforma(self) -> bool:
        """Check if the company can generate more pro formas this month."""
        return self.proformas_this_month < self.max_proformas_per_month
    
    def can_use_ai(self) -> bool:
        """Check if the company can make more AI requests this month."""
        return self.ai_requests_this_month < self.max_ai_requests_per_month
    
    def has_feature(self, feature_name: str) -> bool:
        """Check if a specific feature is enabled for this company."""
        return self.features_enabled.get(feature_name, False)


class User(BaseModel, SoftDeleteMixin):
    """
    User belonging to a company.
    """
    
    __tablename__ = "users"
    
    # Company relationship
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Basic Information
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    
    # Account Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Role & Permissions
    roles: Mapped[list] = mapped_column(
        ARRAY(String(50)),
        default=list,
        server_default='{}'
    )
    permissions: Mapped[list] = mapped_column(
        ARRAY(String(100)),
        default=list,
        server_default='{}'
    )
    
    # Authentication
    last_login_at: Mapped[Optional[datetime]] = mapped_column()
    password_changed_at: Mapped[Optional[datetime]] = mapped_column()
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column()
    
    # Preferences
    preferences: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default='{}'
    )
    
    # Relationships
    company: Mapped["Company"] = relationship("Company", back_populates="users")
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}')>"
    
    @property
    def full_name(self) -> str:
        """Get the user's full name."""
        return f"{self.first_name} {self.last_name}"
    
    @property
    def is_locked(self) -> bool:
        """Check if the user account is locked."""
        if self.locked_until is None:
            return False
        return self.locked_until > datetime.utcnow()
