"""
Security utilities for authentication and authorization.

NOTE: Password hashing functions (hash_password / verify_password) are in
app.core.security_layer which uses bcrypt directly with SHA-256 pre-hashing
for unlimited password length. Do NOT use pwd_context from this file for
new code — it is kept only for the JWT / TokenPayload helpers used by
legacy API routes.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, TokenExpiredError

settings = get_settings()


# ---------------------------------------------------------------------------
# Password hashing — delegate to security_layer which owns this correctly.
# These shims exist so legacy callers of security.py don’t break.
# ---------------------------------------------------------------------------

def verify_password(plain_password: str, hashed_password: str) -> bool:
    from app.core.security_layer import verify_password as _vp
    return _vp(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    from app.core.security_layer import hash_password as _hp
    return _hp(password)

class TokenPayload(BaseModel):
    """JWT token payload schema."""
    sub: str  # Subject (user ID)
    company_id: str  # Tenant ID for multi-tenancy
    exp: datetime  # Expiration time
    iat: datetime  # Issued at time
    type: str  # Token type: "access" or "refresh"
    roles: list[str] = []  # User roles
    permissions: list[str] = []  # Specific permissions


class TokenPair(BaseModel):
    """Access and refresh token pair."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # Seconds until access token expires


def create_access_token(
    user_id: UUID,
    company_id: UUID,
    roles: list[str] = None,
    permissions: list[str] = None,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a new access token.
    
    Args:
        user_id: The user's unique identifier
        company_id: The company/tenant identifier
        roles: List of user roles
        permissions: List of specific permissions
        expires_delta: Custom expiration time
    
    Returns:
        Encoded JWT access token
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    
    payload = {
        "sub": str(user_id),
        "company_id": str(company_id),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
        "roles": roles or [],
        "permissions": permissions or []
    }
    
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(
    user_id: UUID,
    company_id: UUID,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a new refresh token.
    
    Args:
        user_id: The user's unique identifier
        company_id: The company/tenant identifier
        expires_delta: Custom expiration time
    
    Returns:
        Encoded JWT refresh token
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    
    payload = {
        "sub": str(user_id),
        "company_id": str(company_id),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh"
    }
    
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_token_pair(
    user_id: UUID,
    company_id: UUID,
    roles: list[str] = None,
    permissions: list[str] = None
) -> TokenPair:
    """
    Create both access and refresh tokens.
    
    Args:
        user_id: The user's unique identifier
        company_id: The company/tenant identifier
        roles: List of user roles
        permissions: List of specific permissions
    
    Returns:
        TokenPair containing both tokens
    """
    access_token = create_access_token(user_id, company_id, roles, permissions)
    refresh_token = create_refresh_token(user_id, company_id)
    
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60
    )


def decode_token(token: str) -> TokenPayload:
    """
    Decode and validate a JWT token.
    
    Args:
        token: The JWT token to decode
    
    Returns:
        TokenPayload with decoded claims
    
    Raises:
        TokenExpiredError: If the token has expired
        AuthenticationError: If the token is invalid
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm]
        )
        
        # Validate required fields
        if "sub" not in payload or "company_id" not in payload:
            raise AuthenticationError("Invalid token payload")
        
        return TokenPayload(
            sub=payload["sub"],
            company_id=payload["company_id"],
            exp=datetime.fromtimestamp(payload["exp"]),
            iat=datetime.fromtimestamp(payload["iat"]),
            type=payload.get("type", "access"),
            roles=payload.get("roles", []),
            permissions=payload.get("permissions", [])
        )
        
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError()
    except JWTError as e:
        raise AuthenticationError(f"Invalid token: {str(e)}")


def validate_token_type(token_payload: TokenPayload, expected_type: str) -> bool:
    """Validate that the token is of the expected type."""
    return token_payload.type == expected_type


class Permission:
    """Permission constants for the platform."""
    
    # Property permissions
    PROPERTY_CREATE = "property:create"
    PROPERTY_READ = "property:read"
    PROPERTY_UPDATE = "property:update"
    PROPERTY_DELETE = "property:delete"
    
    # Pro forma permissions
    PROFORMA_CREATE = "proforma:create"
    PROFORMA_READ = "proforma:read"
    PROFORMA_UPDATE = "proforma:update"
    PROFORMA_DELETE = "proforma:delete"
    PROFORMA_GENERATE = "proforma:generate"
    
    # Market data permissions
    MARKET_READ = "market:read"
    MARKET_UPDATE = "market:update"
    MARKET_ADMIN = "market:admin"
    
    # Company management permissions
    COMPANY_READ = "company:read"
    COMPANY_UPDATE = "company:update"
    COMPANY_ADMIN = "company:admin"
    
    # User management permissions
    USER_CREATE = "user:create"
    USER_READ = "user:read"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"
    
    # AI features permissions
    AI_ADVISOR = "ai:advisor"
    AI_PRICING = "ai:pricing"
    
    # Integration permissions
    INTEGRATION_MANAGE = "integration:manage"
    INTEGRATION_SYNC = "integration:sync"


class Role:
    """Role definitions with their associated permissions."""
    
    # Super admin - full access
    SUPER_ADMIN = "super_admin"
    
    # Company admin - full access within their company
    COMPANY_ADMIN = "company_admin"
    
    # Business development - can create properties and pro formas
    BUSINESS_DEV = "business_dev"
    
    # Operations - can view and manage existing properties
    OPERATIONS = "operations"
    
    # Viewer - read-only access
    VIEWER = "viewer"
    
    @classmethod
    def get_permissions(cls, role: str) -> list[str]:
        """Get all permissions for a given role."""
        role_permissions = {
            cls.SUPER_ADMIN: [
                # All permissions
                Permission.PROPERTY_CREATE, Permission.PROPERTY_READ,
                Permission.PROPERTY_UPDATE, Permission.PROPERTY_DELETE,
                Permission.PROFORMA_CREATE, Permission.PROFORMA_READ,
                Permission.PROFORMA_UPDATE, Permission.PROFORMA_DELETE,
                Permission.PROFORMA_GENERATE,
                Permission.MARKET_READ, Permission.MARKET_UPDATE, Permission.MARKET_ADMIN,
                Permission.COMPANY_READ, Permission.COMPANY_UPDATE, Permission.COMPANY_ADMIN,
                Permission.USER_CREATE, Permission.USER_READ,
                Permission.USER_UPDATE, Permission.USER_DELETE,
                Permission.AI_ADVISOR, Permission.AI_PRICING,
                Permission.INTEGRATION_MANAGE, Permission.INTEGRATION_SYNC,
            ],
            cls.COMPANY_ADMIN: [
                Permission.PROPERTY_CREATE, Permission.PROPERTY_READ,
                Permission.PROPERTY_UPDATE, Permission.PROPERTY_DELETE,
                Permission.PROFORMA_CREATE, Permission.PROFORMA_READ,
                Permission.PROFORMA_UPDATE, Permission.PROFORMA_DELETE,
                Permission.PROFORMA_GENERATE,
                Permission.MARKET_READ,
                Permission.COMPANY_READ, Permission.COMPANY_UPDATE,
                Permission.USER_CREATE, Permission.USER_READ,
                Permission.USER_UPDATE, Permission.USER_DELETE,
                Permission.AI_ADVISOR, Permission.AI_PRICING,
                Permission.INTEGRATION_MANAGE, Permission.INTEGRATION_SYNC,
            ],
            cls.BUSINESS_DEV: [
                Permission.PROPERTY_CREATE, Permission.PROPERTY_READ,
                Permission.PROPERTY_UPDATE,
                Permission.PROFORMA_CREATE, Permission.PROFORMA_READ,
                Permission.PROFORMA_GENERATE,
                Permission.MARKET_READ,
                Permission.AI_ADVISOR, Permission.AI_PRICING,
            ],
            cls.OPERATIONS: [
                Permission.PROPERTY_READ, Permission.PROPERTY_UPDATE,
                Permission.PROFORMA_READ,
                Permission.MARKET_READ,
                Permission.AI_PRICING,
            ],
            cls.VIEWER: [
                Permission.PROPERTY_READ,
                Permission.PROFORMA_READ,
                Permission.MARKET_READ,
            ],
        }
        return role_permissions.get(role, [])


def check_permission(
    token_payload: TokenPayload,
    required_permission: str
) -> bool:
    """
    Check if the token has the required permission.
    
    Args:
        token_payload: Decoded token payload
        required_permission: Permission to check
    
    Returns:
        True if permission is granted
    """
    # Check direct permissions
    if required_permission in token_payload.permissions:
        return True
    
    # Check role-based permissions
    for role in token_payload.roles:
        if required_permission in Role.get_permissions(role):
            return True
    
    return False


def check_any_permission(
    token_payload: TokenPayload,
    required_permissions: list[str]
) -> bool:
    """Check if the token has any of the required permissions."""
    return any(
        check_permission(token_payload, perm)
        for perm in required_permissions
    )


def check_all_permissions(
    token_payload: TokenPayload,
    required_permissions: list[str]
) -> bool:
    """Check if the token has all of the required permissions."""
    return all(
        check_permission(token_payload, perm)
        for perm in required_permissions
    )
