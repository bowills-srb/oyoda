"""
Custom exceptions for the RentalRevenue.ai platform.
"""

from typing import Any, Dict, Optional


class RentalRevenueException(Exception):
    """Base exception for all platform errors."""
    
    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API response."""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details
            }
        }


# =============================================================================
# Authentication & Authorization Exceptions
# =============================================================================

class AuthenticationError(RentalRevenueException):
    """Raised when authentication fails."""
    
    def __init__(self, message: str = "Authentication failed", details: Optional[Dict] = None):
        super().__init__(
            message=message,
            code="AUTHENTICATION_ERROR",
            status_code=401,
            details=details
        )


class AuthorizationError(RentalRevenueException):
    """Raised when user lacks required permissions."""
    
    def __init__(self, message: str = "Insufficient permissions", details: Optional[Dict] = None):
        super().__init__(
            message=message,
            code="AUTHORIZATION_ERROR",
            status_code=403,
            details=details
        )


class TokenExpiredError(AuthenticationError):
    """Raised when JWT token has expired."""
    
    def __init__(self, message: str = "Token has expired"):
        super().__init__(message=message, details={"reason": "token_expired"})


# =============================================================================
# Resource Exceptions
# =============================================================================

class ResourceNotFoundError(RentalRevenueException):
    """Raised when a requested resource is not found."""
    
    def __init__(
        self,
        resource_type: str,
        resource_id: Any,
        message: Optional[str] = None
    ):
        super().__init__(
            message=message or f"{resource_type} with ID '{resource_id}' not found",
            code="RESOURCE_NOT_FOUND",
            status_code=404,
            details={"resource_type": resource_type, "resource_id": str(resource_id)}
        )


class ResourceAlreadyExistsError(RentalRevenueException):
    """Raised when attempting to create a duplicate resource."""
    
    def __init__(
        self,
        resource_type: str,
        identifier: Any,
        message: Optional[str] = None
    ):
        super().__init__(
            message=message or f"{resource_type} already exists with identifier '{identifier}'",
            code="RESOURCE_ALREADY_EXISTS",
            status_code=409,
            details={"resource_type": resource_type, "identifier": str(identifier)}
        )


class ResourceConflictError(RentalRevenueException):
    """Raised when there's a conflict with the current resource state."""
    
    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            message=message,
            code="RESOURCE_CONFLICT",
            status_code=409,
            details=details
        )


# =============================================================================
# Validation Exceptions
# =============================================================================

class ValidationError(RentalRevenueException):
    """Raised when input validation fails."""
    
    def __init__(self, message: str, field: Optional[str] = None, details: Optional[Dict] = None):
        error_details = details or {}
        if field:
            error_details["field"] = field
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            status_code=422,
            details=error_details
        )


class InvalidPropertyDataError(ValidationError):
    """Raised when property data is invalid or incomplete."""
    
    def __init__(self, message: str, missing_fields: Optional[list] = None):
        super().__init__(
            message=message,
            details={"missing_fields": missing_fields or []}
        )


# =============================================================================
# Pro Forma Exceptions
# =============================================================================

class ProFormaGenerationError(RentalRevenueException):
    """Raised when pro forma generation fails."""
    
    def __init__(self, message: str, property_id: Optional[str] = None, details: Optional[Dict] = None):
        error_details = details or {}
        if property_id:
            error_details["property_id"] = property_id
        super().__init__(
            message=message,
            code="PROFORMA_GENERATION_ERROR",
            status_code=500,
            details=error_details
        )


class InsufficientMarketDataError(ProFormaGenerationError):
    """Raised when there's not enough market data to generate a pro forma."""
    
    def __init__(self, market_id: str, required_data: list):
        super().__init__(
            message=f"Insufficient market data for market '{market_id}' to generate pro forma",
            details={"market_id": market_id, "required_data": required_data}
        )


class NoComparablePropertiesError(ProFormaGenerationError):
    """Raised when no comparable properties are found."""
    
    def __init__(self, property_id: str, search_criteria: Dict):
        super().__init__(
            message="No comparable properties found matching the criteria",
            property_id=property_id,
            details={"search_criteria": search_criteria}
        )


# =============================================================================
# Integration Exceptions
# =============================================================================

class IntegrationError(RentalRevenueException):
    """Base exception for external integration failures."""
    
    def __init__(
        self,
        service: str,
        message: str,
        details: Optional[Dict] = None
    ):
        error_details = details or {}
        error_details["service"] = service
        super().__init__(
            message=message,
            code="INTEGRATION_ERROR",
            status_code=502,
            details=error_details
        )


class MLSIntegrationError(IntegrationError):
    """Raised when MLS integration fails."""
    
    def __init__(self, message: str, mls_provider: str, details: Optional[Dict] = None):
        super().__init__(
            service=f"MLS:{mls_provider}",
            message=message,
            details=details
        )


class PMSIntegrationError(IntegrationError):
    """Raised when PMS integration fails."""
    
    def __init__(self, message: str, pms_provider: str, details: Optional[Dict] = None):
        super().__init__(
            service=f"PMS:{pms_provider}",
            message=message,
            details=details
        )


class MarketDataAPIError(IntegrationError):
    """Raised when market data API call fails."""
    
    def __init__(self, message: str, provider: str, details: Optional[Dict] = None):
        super().__init__(
            service=f"MarketData:{provider}",
            message=message,
            details=details
        )


# =============================================================================
# AI Service Exceptions
# =============================================================================

class AIServiceError(RentalRevenueException):
    """Raised when AI service call fails."""
    
    def __init__(self, message: str, model: Optional[str] = None, details: Optional[Dict] = None):
        error_details = details or {}
        if model:
            error_details["model"] = model
        super().__init__(
            message=message,
            code="AI_SERVICE_ERROR",
            status_code=503,
            details=error_details
        )


class AIRateLimitError(AIServiceError):
    """Raised when AI service rate limit is exceeded."""
    
    def __init__(self, retry_after: Optional[int] = None):
        super().__init__(
            message="AI service rate limit exceeded",
            details={"retry_after_seconds": retry_after}
        )


# =============================================================================
# Rate Limiting Exceptions
# =============================================================================

class RateLimitExceededError(RentalRevenueException):
    """Raised when API rate limit is exceeded."""
    
    def __init__(self, limit: int, window: str, retry_after: Optional[int] = None):
        super().__init__(
            message=f"Rate limit of {limit} requests per {window} exceeded",
            code="RATE_LIMIT_EXCEEDED",
            status_code=429,
            details={
                "limit": limit,
                "window": window,
                "retry_after_seconds": retry_after
            }
        )


# =============================================================================
# Company/Tenant Exceptions
# =============================================================================

class CompanyNotFoundError(ResourceNotFoundError):
    """Raised when company is not found."""
    
    def __init__(self, company_id: str):
        super().__init__(resource_type="Company", resource_id=company_id)


class CompanySubscriptionError(RentalRevenueException):
    """Raised when company subscription is invalid or expired."""
    
    def __init__(self, company_id: str, reason: str):
        super().__init__(
            message=f"Company subscription error: {reason}",
            code="SUBSCRIPTION_ERROR",
            status_code=402,
            details={"company_id": company_id, "reason": reason}
        )


class CompanyQuotaExceededError(RentalRevenueException):
    """Raised when company exceeds their plan quotas."""
    
    def __init__(self, company_id: str, quota_type: str, limit: int, current: int):
        super().__init__(
            message=f"Company quota exceeded for {quota_type}",
            code="QUOTA_EXCEEDED",
            status_code=429,
            details={
                "company_id": company_id,
                "quota_type": quota_type,
                "limit": limit,
                "current_usage": current
            }
        )
