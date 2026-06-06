"""
Core configuration for the RentalRevenue.ai platform.
Manages environment variables and application settings.
"""

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Application
    app_name: str = "RentalRevenue.ai"
    app_version: str = "0.1.0"
    debug: bool = False
    environment: str = Field(default="development", pattern="^(development|staging|production)$")
    
    # API
    api_v1_prefix: str = "/api/v1"
    allowed_origins: List[str] = ["http://localhost:3000", "http://localhost:8000", "https://oyvoda.com", "https://oyvoda-production.up.railway.app"]

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v):
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return ["https://oyvoda.com", "https://oyvoda-production.up.railway.app"]
            try:
                import json
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
            # comma-separated fallback
            return [x.strip() for x in v.split(",") if x.strip()]
        return v
    
    # Security
    secret_key: str = Field(default="change-me-in-production")
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    algorithm: str = "HS256"

    # Encryption
    oyvoda_master_key: Optional[str] = None       # base64 AES-256 key — required in production
    oyvoda_master_key_id: str = "v1"              # key version for rotation
    oyvoda_previous_master_keys: Optional[str] = None  # comma-separated old keys

    # Sentry
    sentry_dsn: Optional[str] = None              # Set in Railway to enable error tracking
    sentry_traces_sample_rate: float = 0.1        # 10% performance tracing

    # Login security
    login_max_attempts: int = 5                   # Lock after N failed attempts
    login_lockout_minutes: int = 15               # Lockout duration

    # Security flags
    hide_api_docs: bool = True                    # Disable /docs and /redoc in production
    
    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/rental_revenue"
    )
    local_database_url: str = Field(
        default="postgresql+asyncpg://rental:rental@localhost:5433/rental_revenue"
    )
    prefer_local_database: bool = False
    auto_fallback_local_database: bool = False
    database_pool_size: int = 20
    database_max_overflow: int = 10
    database_echo: bool = False
    
    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_cache_ttl: int = 3600  # 1 hour default cache TTL
    
    # Celery
    celery_broker_url: str = Field(default="redis://localhost:6379/1")
    celery_result_backend: str = Field(default="redis://localhost:6379/2")
    
    # Base URL for guest concierge links (override with ngrok / production domain)
    base_url: str = Field(default="http://localhost:8000")

    # Object storage (Cloudflare R2 / S3-compatible)
    r2_endpoint_url: Optional[str] = None
    r2_access_key_id: Optional[str] = None
    r2_secret_access_key: Optional[str] = None
    r2_bucket_name: Optional[str] = None

    # AI/ML Services
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    groq_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"  # Groq LPU, 0.49s TTFT, 750 t/s
    groq_model_fallback: str = "llama-3.3-70b-versatile"  # fallback if Scout unavailable
    gemini_api_key: Optional[str] = None
    ai_model_default: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    
    # SMS/Messaging Services
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_phone_number: Optional[str] = None          # E.164 fallback number for SMS
    # Escapia PMS
    escapia_api_key: Optional[str] = None          # Live API key from Escapia/Vrbo
    first_operator_company_id: Optional[str] = None  # UUID of the first operator

    twilio_messaging_sid: Optional[str] = None         # Messaging Service SID (MG...) — required for RCS
    twilio_rcs_enabled: bool = False                   # Gate: enable only after Twilio RCS account approval
    twilio_validate_signatures: bool = False           # Enable in production

    # Apple Messages for Business
    abm_business_account_id: Optional[str] = None     # From Apple Business Register
    abm_api_key: Optional[str] = None
    abm_api_secret: Optional[str] = None
    abm_webhook_secret: Optional[str] = None           # For validating inbound webhook signatures

    # Email
    sendgrid_api_key: Optional[str] = None
    sendgrid_from_email: str = "concierge@oyvoda.com"
    
    # Voice Services (Concierge)
    deepgram_api_key: Optional[str] = None
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_voice_id: str = "rachel"  # Default voice
    
    # External Integrations
    airdna_api_key: Optional[str] = None
    airdna_base_url: str = "https://api.airdna.co/v1"
    escapia_api_key: Optional[str] = None
    escapia_client_id: Optional[str] = None
    escapia_client_secret: Optional[str] = None
    escapia_username: Optional[str] = None
    escapia_password: Optional[str] = None
    escapia_base_url: str = "https://api.escapia.com/v1"
    
    # Feature Flags
    enable_ai_advisor: bool = True
    enable_auto_proforma: bool = True
    enable_mls_sync: bool = False
    concierge_dining_enabled: bool = True
    focus_concierge_only: bool = True
    enable_concierge_market_signals: bool = True
    enable_concierge_health_checks: bool = True
    enable_market_intel_api: bool = False
    enable_watch_api: bool = False
    strict_startup_checks: bool = False  # default false — set True only for explicit validation runs
    run_embedded_background_workers: bool = False
    run_gmail_polling_worker: bool = False
    required_mcp_servers: str = "concierge,knowledge,pms"
    required_concierge_tables: str = "concierge_guest_sessions,knowledge_embeddings,concierge_escalations"

    # SLO thresholds
    slo_api_latency_ms_threshold: int = 1200
    slo_knowledge_latency_ms_threshold: int = 1500
    slo_voice_latency_ms_threshold: int = 2500
    slo_empty_retrieval_rate_threshold: float = 0.05
    slo_error_rate_threshold: float = 0.01
    slo_escalation_backlog_threshold: int = 25

    # Ops auth/RBAC for internal observability surfaces
    enforce_ops_auth: bool = False
    ops_api_key: Optional[str] = None
    metrics_api_key: Optional[str] = None
    
    # Rate Limiting
    rate_limit_per_minute: int = 60
    rate_limit_per_hour: int = 1000
    rate_limit_login_per_minute: int = 10         # Stricter limit for login endpoint
    
    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Ensure database URL uses asyncpg driver."""
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v
    
    @property
    def sync_database_url(self) -> str:
        """Return synchronous database URL for Alembic migrations."""
        return self.database_url.replace("+asyncpg", "")


class MarketSettings(BaseSettings):
    """Market-specific configuration defaults."""
    
    model_config = SettingsConfigDict(env_prefix="MARKET_")
    
    # Default commission rates
    default_commission_rate: float = 0.20  # 20%
    
    # Occupancy estimation defaults
    min_occupancy_rate: float = 0.25
    max_occupancy_rate: float = 0.95
    default_occupancy_rate: float = 0.48
    
    # Rate calculation defaults
    rate_adjustment_cap: float = 0.30  # Max 30% adjustment from base
    minimum_nightly_rate: float = 100.0
    
    # Seasonal periods (can be overridden per market)
    peak_season_months: List[int] = [6, 7]  # June, July
    shoulder_season_months: List[int] = [3, 4, 5, 8, 9, 10]
    off_season_months: List[int] = [1, 2, 11, 12]


class ProFormaSettings(BaseSettings):
    """Pro forma generation configuration."""
    
    model_config = SettingsConfigDict(env_prefix="PROFORMA_")
    
    # Sensitivity analysis ranges
    sensitivity_rate_range: List[float] = [0.80, 0.90, 1.00, 1.10, 1.20]
    sensitivity_occupancy_range: List[float] = [0.80, 0.90, 1.00, 1.10, 1.20]
    
    # Output formats
    default_output_format: str = "pdf"
    supported_formats: List[str] = ["pdf", "xlsx", "json"]
    
    # Comparable property settings
    max_comps: int = 10
    comp_radius_miles: float = 5.0
    comp_bedroom_variance: int = 1
    comp_sqft_variance_pct: float = 0.25


@lru_cache()
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()


@lru_cache()
def get_market_settings() -> MarketSettings:
    """Get cached market settings."""
    return MarketSettings()


@lru_cache()
def get_proforma_settings() -> ProFormaSettings:
    """Get cached pro forma settings."""
    return ProFormaSettings()
