"""
Secure Integration Vault - Tenant-isolated sensitive data storage.

Provides encrypted, isolated storage for:
- Custom rate tables and proprietary pricing
- Owner contracts and sensitive documents
- API credentials for integrations
- Custom business workflows
- Historical performance data
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Type
from uuid import UUID, uuid4
import base64
import hashlib
import json
import logging
import secrets

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import Boolean, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditMixin, TenantBaseModel

logger = logging.getLogger(__name__)


class VaultItemType(str, Enum):
    """Types of items stored in the vault."""
    API_CREDENTIAL = "api_credential"
    RATE_TABLE = "rate_table"
    CONTRACT = "contract"
    WORKFLOW = "workflow"
    PERFORMANCE_DATA = "performance_data"
    CUSTOM_DATA = "custom_data"
    ENCRYPTION_KEY = "encryption_key"


class AccessLevel(str, Enum):
    """Access levels for vault items."""
    OWNER_ONLY = "owner_only"  # Only company owner
    ADMIN = "admin"  # Company admins
    MANAGER = "manager"  # Managers and above
    STAFF = "staff"  # All staff
    SYSTEM = "system"  # System processes only


class VaultItem(TenantBaseModel, AuditMixin):
    """
    Encrypted item in the secure vault.
    
    All sensitive data is encrypted at rest with tenant-specific keys.
    """
    
    __tablename__ = "vault_items"
    
    # Item identification
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    item_type: Mapped[VaultItemType] = mapped_column(String(50), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    
    # Encrypted content
    encrypted_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_key_id: Mapped[UUID] = mapped_column(nullable=False)  # Reference to key used
    
    # Access control
    access_level: Mapped[AccessLevel] = mapped_column(
        String(50),
        default=AccessLevel.ADMIN
    )
    allowed_user_ids: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        server_default='[]'
    )
    
    # Metadata (unencrypted)
    extra_data: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default='{}'
    )
    
    # Versioning
    version: Mapped[int] = mapped_column(Integer, default=1)
    previous_version_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("vault_items.id", ondelete="SET NULL"),
        nullable=True
    )
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column()
    
    # Audit
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column()
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    
    def __repr__(self) -> str:
        return f"<VaultItem(id={self.id}, name='{self.name}', type={self.item_type})>"


class VaultAccessLog(TenantBaseModel):
    """
    Audit log for vault access.
    
    Every access to vault items is logged for security and compliance.
    """
    
    __tablename__ = "vault_access_logs"
    
    # What was accessed
    vault_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("vault_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Who accessed
    user_id: Mapped[Optional[UUID]] = mapped_column(index=True)
    service_name: Mapped[Optional[str]] = mapped_column(String(100))  # For system access
    
    # Access details
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # read, write, delete
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))
    
    # Result
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(255))
    
    def __repr__(self) -> str:
        return f"<VaultAccessLog(item_id={self.vault_item_id}, action='{self.action}')>"


@dataclass
class EncryptionContext:
    """Context for encryption operations."""
    company_id: UUID
    key_id: UUID
    cipher: Any  # Fernet cipher instance
    created_at: datetime


class VaultEncryptionService:
    """
    Handles encryption/decryption for vault items.
    
    Uses per-tenant encryption keys derived from a master key
    and tenant-specific salt.
    """
    
    def __init__(self, master_key: bytes):
        """
        Initialize with master encryption key.
        
        In production, master_key should come from a KMS like AWS KMS.
        """
        self._master_key = master_key
        self._tenant_ciphers: Dict[UUID, EncryptionContext] = {}
    
    def _derive_tenant_key(self, company_id: UUID, salt: bytes = None) -> Tuple[bytes, bytes]:
        """Derive a tenant-specific key from the master key."""
        if salt is None:
            salt = secrets.token_bytes(16)
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        
        # Combine master key with company ID for tenant isolation
        key_material = self._master_key + str(company_id).encode()
        derived_key = base64.urlsafe_b64encode(kdf.derive(key_material))
        
        return derived_key, salt
    
    def get_cipher_for_tenant(self, company_id: UUID, salt: bytes = None) -> EncryptionContext:
        """Get or create a Fernet cipher for a tenant."""
        if company_id in self._tenant_ciphers:
            return self._tenant_ciphers[company_id]
        
        derived_key, used_salt = self._derive_tenant_key(company_id, salt)
        cipher = Fernet(derived_key)
        
        context = EncryptionContext(
            company_id=company_id,
            key_id=uuid4(),
            cipher=cipher,
            created_at=datetime.now(timezone.utc)
        )
        
        self._tenant_ciphers[company_id] = context
        return context
    
    def encrypt(self, data: bytes, company_id: UUID) -> Tuple[bytes, UUID]:
        """Encrypt data for a tenant."""
        context = self.get_cipher_for_tenant(company_id)
        encrypted = context.cipher.encrypt(data)
        return encrypted, context.key_id
    
    def decrypt(self, encrypted_data: bytes, company_id: UUID) -> bytes:
        """Decrypt data for a tenant."""
        context = self.get_cipher_for_tenant(company_id)
        return context.cipher.decrypt(encrypted_data)


class SecureVault:
    """
    Main interface for the secure vault.
    
    Provides high-level operations for storing and retrieving
    sensitive data with encryption and access control.
    """
    
    def __init__(
        self,
        encryption_service: VaultEncryptionService,
        db_session=None
    ):
        self.encryption = encryption_service
        self.db = db_session
    
    async def store(
        self,
        company_id: UUID,
        name: str,
        data: Dict[str, Any],
        item_type: VaultItemType,
        user_id: UUID = None,
        access_level: AccessLevel = AccessLevel.ADMIN,
        metadata: Dict[str, Any] = None,
        expires_in_days: int = None,
    ) -> VaultItem:
        """
        Store an item in the vault.
        
        Args:
            company_id: The tenant ID
            name: Human-readable name for the item
            data: The data to encrypt and store
            item_type: Type of vault item
            user_id: User performing the operation
            access_level: Who can access this item
            metadata: Unencrypted metadata
            expires_in_days: Auto-expire after this many days
        
        Returns:
            The created VaultItem
        """
        # Serialize and encrypt
        serialized = json.dumps(data).encode('utf-8')
        encrypted, key_id = self.encryption.encrypt(serialized, company_id)
        
        # Calculate expiration
        expires_at = None
        if expires_in_days:
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
        
        # Create vault item
        item = VaultItem(
            company_id=company_id,
            name=name,
            item_type=item_type,
            encrypted_data=encrypted,
            encryption_key_id=key_id,
            access_level=access_level,
            metadata=metadata or {},
            expires_at=expires_at,
            created_by_id=user_id,
            updated_by_id=user_id,
        )
        
        # In real implementation, save to database
        # self.db.add(item)
        # await self.db.commit()
        
        logger.info(
            f"Stored vault item: {name} (type={item_type}) for company {company_id}",
            extra={"vault_item_id": str(item.id)}
        )
        
        return item
    
    async def retrieve(
        self,
        item_id: UUID,
        company_id: UUID,
        user_id: UUID = None,
        service_name: str = None,
        ip_address: str = None,
    ) -> Dict[str, Any]:
        """
        Retrieve and decrypt a vault item.
        
        Args:
            item_id: The vault item ID
            company_id: The tenant ID (for verification)
            user_id: User requesting access
            service_name: Service name if system access
            ip_address: IP address for audit
        
        Returns:
            Decrypted data
        
        Raises:
            PermissionError: If access is denied
            ValueError: If item not found or expired
        """
        # In real implementation, fetch from database
        # item = await self.db.get(VaultItem, item_id)
        
        # For now, raise not implemented
        raise NotImplementedError("Database integration required")
        
        # Verification steps would be:
        # 1. Verify company_id matches
        # 2. Check access level against user role
        # 3. Check if expired
        # 4. Decrypt and return
        # 5. Log access
    
    async def store_api_credential(
        self,
        company_id: UUID,
        name: str,
        api_key: str,
        api_secret: str = None,
        service: str = None,
        user_id: UUID = None,
        additional_config: Dict[str, Any] = None,
    ) -> VaultItem:
        """
        Store API credentials securely.
        
        Convenience method for storing integration credentials.
        """
        data = {
            "api_key": api_key,
            "api_secret": api_secret,
            "service": service,
            "config": additional_config or {},
        }
        
        return await self.store(
            company_id=company_id,
            name=name,
            data=data,
            item_type=VaultItemType.API_CREDENTIAL,
            user_id=user_id,
            access_level=AccessLevel.SYSTEM,  # Only system can access credentials
            metadata={"service": service},
        )
    
    async def store_rate_table(
        self,
        company_id: UUID,
        name: str,
        rate_data: Dict[str, Any],
        user_id: UUID = None,
        is_proprietary: bool = True,
    ) -> VaultItem:
        """
        Store proprietary rate table data.
        
        Rate tables may contain competitive intelligence
        that should be protected.
        """
        return await self.store(
            company_id=company_id,
            name=name,
            data=rate_data,
            item_type=VaultItemType.RATE_TABLE,
            user_id=user_id,
            access_level=AccessLevel.MANAGER if is_proprietary else AccessLevel.STAFF,
            metadata={"is_proprietary": is_proprietary},
        )
    
    async def store_workflow(
        self,
        company_id: UUID,
        name: str,
        workflow_definition: Dict[str, Any],
        user_id: UUID = None,
    ) -> VaultItem:
        """
        Store a custom workflow definition.
        
        Workflows define automated processes specific to each company.
        """
        return await self.store(
            company_id=company_id,
            name=name,
            data=workflow_definition,
            item_type=VaultItemType.WORKFLOW,
            user_id=user_id,
            access_level=AccessLevel.ADMIN,
            metadata={
                "workflow_version": workflow_definition.get("version", "1.0"),
                "triggers": workflow_definition.get("triggers", []),
            },
        )
    
    async def rotate_encryption_key(
        self,
        company_id: UUID,
        user_id: UUID,
    ) -> int:
        """
        Rotate encryption key for a tenant.
        
        Re-encrypts all vault items with a new key.
        Returns count of items rotated.
        """
        # In real implementation:
        # 1. Generate new tenant key
        # 2. For each vault item:
        #    a. Decrypt with old key
        #    b. Encrypt with new key
        #    c. Update encryption_key_id
        # 3. Invalidate old key
        
        raise NotImplementedError("Key rotation requires database integration")
    
    async def audit_log(
        self,
        company_id: UUID,
        start_date: datetime = None,
        end_date: datetime = None,
        item_type: VaultItemType = None,
        user_id: UUID = None,
    ) -> List[VaultAccessLog]:
        """
        Retrieve vault access audit logs.
        
        Used for security review and compliance.
        """
        raise NotImplementedError("Audit log requires database integration")


# =============================================================================
# Workflow Definition Schema
# =============================================================================

class WorkflowTrigger(BaseModel):
    """Trigger that starts a workflow."""
    trigger_type: str  # event, schedule, manual, webhook
    config: Dict[str, Any] = Field(default_factory=dict)


class WorkflowStep(BaseModel):
    """A step in a workflow."""
    step_id: str
    step_type: str  # action, condition, delay, notification
    config: Dict[str, Any] = Field(default_factory=dict)
    next_steps: List[str] = Field(default_factory=list)
    on_error: Optional[str] = None


class WorkflowDefinition(BaseModel):
    """
    Custom workflow definition stored in vault.
    
    Workflows automate business processes specific to each company.
    """
    name: str
    description: Optional[str] = None
    version: str = "1.0"
    
    # Triggers
    triggers: List[WorkflowTrigger] = Field(default_factory=list)
    
    # Steps
    entry_point: str  # First step ID
    steps: Dict[str, WorkflowStep] = Field(default_factory=dict)
    
    # Settings
    is_enabled: bool = True
    max_executions_per_hour: int = 100
    timeout_seconds: int = 3600
    
    # Metadata
    tags: List[str] = Field(default_factory=list)
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "New Listing Processor",
                "description": "Process new listings from MLS feed",
                "version": "1.0",
                "triggers": [
                    {"trigger_type": "event", "config": {"event": "new_listing_detected"}}
                ],
                "entry_point": "check_geofence",
                "steps": {
                    "check_geofence": {
                        "step_id": "check_geofence",
                        "step_type": "condition",
                        "config": {"condition": "property.in_geofence"},
                        "next_steps": ["generate_proforma"],
                    },
                    "generate_proforma": {
                        "step_id": "generate_proforma",
                        "step_type": "action",
                        "config": {"action": "generate_proforma"},
                        "next_steps": ["notify_bd"],
                    },
                    "notify_bd": {
                        "step_id": "notify_bd",
                        "step_type": "notification",
                        "config": {
                            "channel": "slack",
                            "template": "new_listing_alert"
                        },
                        "next_steps": [],
                    },
                },
            }
        }
    )
