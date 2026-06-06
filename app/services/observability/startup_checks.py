"""
Strict startup checks for concierge-critical dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from sqlalchemy import text

from app.core.config import Settings
from app.core.database import get_db_session
from app.mcp.registry import get_mcp_registry
from app.services.observability.deployment_runtime import get_config_revision, is_railway_runtime


@dataclass
class StartupCheckReport:
    failures: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


async def run_startup_checks(settings: Settings) -> StartupCheckReport:
    report = StartupCheckReport()

    registry = get_mcp_registry()
    server_names = {s["name"] for s in registry.list_servers()}
    required_servers = _split_csv(settings.required_mcp_servers)
    missing_servers = sorted(set(required_servers) - server_names)
    if missing_servers:
        # Downgrade to warning — MCPs failing startup causes full app crash
        # The registry itself validates servers at call time
        report.warnings.append(f"MCP server config mismatch (non-fatal): {', '.join(missing_servers)}")

    if settings.enable_concierge_market_signals:
        market_dependencies = {"signal", "scraper", "detector"}
        missing_market = sorted(market_dependencies - server_names)
        if missing_market:
            report.warnings.append(
                f"Market signal MCP servers not found (non-fatal): {', '.join(missing_market)}"
            )

    required_tables = _split_csv(settings.required_concierge_tables)
    if required_tables:
        try:
            async with get_db_session() as db:
                for table_name in required_tables:
                    exists = await db.scalar(
                        text(
                            """
                            SELECT EXISTS (
                              SELECT 1
                              FROM information_schema.tables
                              WHERE table_schema = 'public'
                                AND table_name = :table_name
                            )
                            """
                        ),
                        {"table_name": table_name},
                    )
                    if not exists:
                        report.warnings.append(f"Missing table (will be created on first use): {table_name}")
        except Exception as e:
            # Non-fatal: log warning but never crash startup over a table check
            report.warnings.append(f"Table check skipped (DB not ready at startup): {e}")

    if settings.focus_concierge_only and settings.enable_market_intel_api:
        report.warnings.append("focus_concierge_only is enabled but enable_market_intel_api is also true")
    if settings.focus_concierge_only and settings.enable_watch_api:
        report.warnings.append("focus_concierge_only is enabled but enable_watch_api is also true")

    if settings.concierge_dining_enabled:
        if not any([settings.escapia_api_key, settings.escapia_client_id]):
            report.warnings.append(
                "Dining/PMS live integration credentials are not configured yet; running in fallback mode"
            )

    if is_railway_runtime():
        config_revision = get_config_revision()
        if not config_revision["value"]:
            report.warnings.append(
                "Railway runtime has no config revision marker (set OYVODA_CONFIG_REVISION, "
                "CONFIG_REVISION, or SECRET_EPOCH). Secret rotation propagation will be hard "
                "to prove across deploy/restart boundaries."
            )

    if not any([settings.groq_api_key, settings.gemini_api_key]):
        report.warnings.append(
            "No LLM API key configured (set GROQ_API_KEY and/or GEMINI_API_KEY); concierge replies may fall back"
        )

    if settings.enforce_ops_auth:
        if not settings.ops_api_key:
            report.warnings.append("enforce_ops_auth is enabled but ops_api_key is not set")
        if not settings.metrics_api_key:
            report.warnings.append("enforce_ops_auth is enabled but metrics_api_key is not set")

    return report
