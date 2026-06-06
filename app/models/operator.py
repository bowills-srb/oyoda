"""
Operator Model

Represents a property management company using the platform.
Each operator has their own branding (logo, colors, name) that appears
on guest-facing interfaces.

Supports multi-tenant architecture where:
- Beach Habitats is the primary operator
- Additional operators can be onboarded with their own branding
- Each property belongs to one operator
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from pathlib import Path
import json
import logging

OPERATOR_STORE_PATH = Path(__file__).parent.parent.parent / "data" / "operators.json"

logger = logging.getLogger(__name__)


@dataclass
class OperatorBranding:
    """Branding configuration for operator"""
    # Logo
    logo_url: str  # Primary logo (light background)
    logo_dark_url: Optional[str] = None  # Logo for dark backgrounds
    favicon_url: Optional[str] = None
    
    # Colors
    primary_color: str = "#0ea5e9"  # Main brand color
    secondary_color: str = "#0284c7"  # Accent color
    header_gradient_start: str = "#0c4a6e"
    header_gradient_end: str = "#0369a1"
    
    # Text
    company_name: str = "Beach Habitats"
    tagline: Optional[str] = "Making beach vacations unforgettable"
    
    # Contact
    support_phone: Optional[str] = None
    support_email: Optional[str] = None
    website_url: Optional[str] = None
    
    # Concierge persona
    concierge_name: str = "Coral"
    concierge_emoji: str = "🐚"


@dataclass
class Operator:
    """
    Property management operator.
    
    Each operator manages a set of properties and has their own
    branding that appears on guest interfaces.
    """
    id: str
    code: str  # Short code, e.g., "BH" for Beach Habitats
    name: str
    
    # Branding
    branding: OperatorBranding
    
    # Settings
    is_active: bool = True
    timezone: str = "America/Chicago"  # Central Time for 30A
    
    # Concierge settings
    base_url: str = "https://beachhabitats.com"  # For concierge links
    session_expires_hours_after_checkout: int = 24  # When sessions expire
    
    # API Keys (operator-specific if needed)
    groq_api_key: Optional[str] = None
    
    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    properties_count: int = 0
    
    def get_concierge_url(self, token: str) -> str:
        """Get the full concierge URL for a guest token"""
        return f"{self.base_url}/c/{token}"


# =============================================================================
# Default Operators
# =============================================================================

# Beach Habitats - Primary operator
BEACH_HABITATS = Operator(
    id="op_beach_habitats",
    code="BH",
    name="Beach Habitats",
    branding=OperatorBranding(
        logo_url="https://beachhabitats.com/images/logo.png",
        logo_dark_url="https://beachhabitats.com/images/logo-white.png",
        primary_color="#0ea5e9",
        secondary_color="#0284c7",
        header_gradient_start="#0c4a6e",
        header_gradient_end="#0369a1",
        company_name="Beach Habitats",
        tagline="Making beach vacations unforgettable",
        support_phone="(850) 555-0123",
        support_email="hello@beachhabitats.com",
        website_url="https://beachhabitats.com",
        concierge_name="Coral",
        concierge_emoji="🐚",
    ),
    base_url="https://beachhabitats.com",
    session_expires_hours_after_checkout=24,
)


# =============================================================================
# Operator Registry
# =============================================================================

class OperatorRegistry:
    """
    Manages operators in the system.
    Persists custom operators to a JSON file so they survive restarts.
    """
    
    def __init__(self):
        self._operators: Dict[str, Operator] = {}
        self._by_code: Dict[str, Operator] = {}
        
        # Register default operator first
        self._register_internal(BEACH_HABITATS)
        
        # Load persisted operators from disk
        self._load_from_disk()
    
    def _register_internal(self, operator: Operator) -> None:
        """Register without saving (used for defaults and during load)"""
        self._operators[operator.id] = operator
        self._by_code[operator.code] = operator

    def _load_from_disk(self) -> None:
        """Load persisted operators from JSON file"""
        if not OPERATOR_STORE_PATH.exists():
            return
        try:
            data = json.loads(OPERATOR_STORE_PATH.read_text())
            for op_dict in data.get("operators", []):
                op_id = op_dict.get("id")
                if op_id == BEACH_HABITATS.id:
                    continue  # Never overwrite the default from disk
                try:
                    branding_dict = op_dict.pop("branding", {})
                    branding = OperatorBranding(**branding_dict)
                    op_dict.pop("created_at", None)  # Ignore serialized datetime
                    op = Operator(branding=branding, **op_dict)
                    self._register_internal(op)
                    logger.info(f"Loaded operator from disk: {op.name} ({op.code})")
                except Exception as e:
                    logger.warning(f"Could not load operator {op_id}: {e}")
        except Exception as e:
            logger.warning(f"Could not load operators from disk: {e}")

    def _save_to_disk(self) -> None:
        """Persist all non-default operators to JSON"""
        try:
            OPERATOR_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
            operators_to_save = [
                op for op in self._operators.values()
                if op.id != BEACH_HABITATS.id
            ]
            data = {"operators": []}
            for op in operators_to_save:
                d = asdict(op)
                d["created_at"] = op.created_at.isoformat()
                data["operators"].append(d)
            OPERATOR_STORE_PATH.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error(f"Could not save operators to disk: {e}")

    def register(self, operator: Operator) -> None:
        """Register an operator and persist to disk"""
        self._register_internal(operator)
        logger.info(f"Registered operator: {operator.name} ({operator.code})")
        if operator.id != BEACH_HABITATS.id:
            self._save_to_disk()
    
    def get(self, operator_id: str) -> Optional[Operator]:
        """Get operator by ID"""
        return self._operators.get(operator_id)
    
    def get_by_code(self, code: str) -> Optional[Operator]:
        """Get operator by code"""
        return self._by_code.get(code.upper())
    
    def get_default(self) -> Operator:
        """Get the default operator (Beach Habitats)"""
        return BEACH_HABITATS
    
    def list_all(self) -> List[Operator]:
        """List all operators"""
        return list(self._operators.values())
    
    def create_operator(
        self,
        code: str,
        name: str,
        logo_url: str,
        primary_color: str = "#0ea5e9",
        support_phone: Optional[str] = None,
        support_email: Optional[str] = None,
        concierge_name: str = "Coral",
        base_url: Optional[str] = None,
    ) -> Operator:
        """Create and register a new operator"""
        import uuid
        
        operator = Operator(
            id=f"op_{uuid.uuid4().hex[:12]}",
            code=code.upper(),
            name=name,
            branding=OperatorBranding(
                logo_url=logo_url,
                primary_color=primary_color,
                company_name=name,
                support_phone=support_phone,
                support_email=support_email,
                concierge_name=concierge_name,
            ),
            base_url=base_url or f"https://{code.lower()}.beachhabitats.com",
        )
        
        self.register(operator)
        return operator


# Singleton registry
_registry: Optional[OperatorRegistry] = None

def get_operator_registry() -> OperatorRegistry:
    """Get the operator registry singleton"""
    global _registry
    if _registry is None:
        _registry = OperatorRegistry()
    return _registry


def get_operator(operator_id: Optional[str] = None) -> Operator:
    """Get operator by ID, or return default"""
    registry = get_operator_registry()
    if operator_id:
        op = registry.get(operator_id)
        if op:
            return op
    return registry.get_default()
