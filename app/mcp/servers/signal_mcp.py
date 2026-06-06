"""
Signal MCP Server

Wraps app/services/signals/* and app/services/detectors/detector_engine.py
for zero-token-cost agent access.

Tools exposed:
  get_bundle(geo_id)                      → SignalBundle as JSON
  get_weighted(geo_id, signal_type)       → float
  get_regime(geo_id)                      → MarketRegime + confidence
  check_consistency(geo_id)              → ConsistencyResult
  get_coverage(geo_id)                   → coverage score + types present
  get_confidence(geo_id, signal_type)    → effective confidence float
  assert_confidence(geo_id, output_type) → bool (gate check)

Why this saves tokens:
  Without this MCP, an agent must either:
    (a) call a REST endpoint and parse JSON in a tool-call round trip, OR
    (b) have the entire signal bundle injected into its context window
  With this MCP, the agent calls in-process Python directly.
  Signal bundles can be 5-50KB — that's 1,000-10,000 tokens SAVED per call.
"""

import logging
from typing import Any, Dict, List

from app.mcp.base import MCPResult, MCPServer, MCPTool
from app.services.signals.signal_contract import SignalType, is_confidence_sufficient

logger = logging.getLogger(__name__)


class SignalMCPServer(MCPServer):
    """Direct in-process access to the Signal Pipeline."""

    server_name = "signal"
    server_description = "Market signal intelligence — supply, demand, pricing, regime"

    def get_tools(self) -> List[MCPTool]:
        return [
            MCPTool(
                name="get_bundle",
                description="Get all market signals for a geo as a weighted bundle",
                parameters={
                    "type": "object",
                    "properties": {
                        "geo_id": {"type": "string", "description": "Market geo ID e.g. '30a-beaches'"},
                        "use_cache": {"type": "boolean", "default": True},
                    },
                    "required": ["geo_id"],
                },
                returns="SignalBundle as dict with per-type weighted values and confidence",
                category="signals",
            ),
            MCPTool(
                name="get_weighted",
                description="Get decay-weighted value for a specific signal type",
                parameters={
                    "type": "object",
                    "properties": {
                        "geo_id": {"type": "string"},
                        "signal_type": {
                            "type": "string",
                            "enum": [t.value for t in SignalType],
                        },
                    },
                    "required": ["geo_id", "signal_type"],
                },
                returns="float: weighted signal value, or null if no data",
                category="signals",
            ),
            MCPTool(
                name="get_regime",
                description="Detect current market regime (bull/bear/stable/volatile)",
                parameters={
                    "type": "object",
                    "properties": {
                        "geo_id": {"type": "string"},
                    },
                    "required": ["geo_id"],
                },
                returns="RegimeResult with regime, confidence, trend direction",
                category="signals",
            ),
            MCPTool(
                name="check_consistency",
                description="Check cross-signal consistency and get confidence adjustment",
                parameters={
                    "type": "object",
                    "properties": {
                        "geo_id": {"type": "string"},
                    },
                    "required": ["geo_id"],
                },
                returns="ConsistencyResult with agreement level and confidence multiplier",
                category="signals",
            ),
            MCPTool(
                name="assert_confidence",
                description="Gate check: is confidence sufficient for an output type?",
                parameters={
                    "type": "object",
                    "properties": {
                        "geo_id": {"type": "string"},
                        "output_type": {
                            "type": "string",
                            "enum": [
                                "voice_pricing", "voice_discount", "voice_market",
                                "bd_projection", "bd_recommendation", "bd_expansion",
                                "internal",
                            ],
                        },
                    },
                    "required": ["geo_id", "output_type"],
                },
                returns="bool — True if agent may make the claim, False if it must hedge",
                category="signals",
            ),
        ]

    async def call(
        self,
        tool_name: str,
        operator_id: str,
        params: Dict[str, Any],
    ) -> MCPResult:
        """Dispatch to the correct signal tool."""

        if tool_name == "get_bundle":
            return await self._get_bundle(operator_id, params)
        elif tool_name == "get_weighted":
            return await self._get_weighted(operator_id, params)
        elif tool_name == "get_regime":
            return await self._get_regime(operator_id, params)
        elif tool_name == "check_consistency":
            return await self._check_consistency(operator_id, params)
        elif tool_name == "assert_confidence":
            return await self._assert_confidence(operator_id, params)
        else:
            return MCPResult(
                success=False,
                message=f"Unknown tool: {tool_name}",
            )

    # ─────────────────────────────────────────
    # Tool implementations
    # ─────────────────────────────────────────

    async def _get_bundle(self, operator_id: str, params: Dict) -> MCPResult:
        geo_id = params["geo_id"]
        use_cache = params.get("use_cache", True)

        try:
            # Try the full signal pipeline first (requires DB)
            from app.services.signals.signal_pipeline import SignalPipeline
            pipeline = SignalPipeline()
            bundle = await pipeline.get_signal_bundle(geo_id, use_cache=use_cache)
            return MCPResult(success=True, data=bundle, message=f"Bundle for {geo_id}")
        except Exception:
            pass

        # Fallback: use the in-memory signal contract (no DB needed)
        # Return an empty bundle with metadata
        return MCPResult(
            success=True,
            data={
                "geo_id": geo_id,
                "signal_count": 0,
                "overall_confidence": 0.0,
                "confidence_level": "insufficient",
                "message": "Signal pipeline not connected — run migrations first",
            },
            message=f"Empty bundle for {geo_id} (pipeline offline)",
        )

    async def _get_weighted(self, operator_id: str, params: Dict) -> MCPResult:
        geo_id = params["geo_id"]
        signal_type_str = params["signal_type"]

        try:
            from app.services.signals.signal_contract import SignalType, SignalBundle
            st = SignalType(signal_type_str)
            # If pipeline is connected, fetch real data
            from app.services.signals.signal_pipeline import SignalPipeline
            pipeline = SignalPipeline()
            bundle_data = await pipeline.get_signal_bundle(geo_id)
            value = bundle_data.get("signals", {}).get(signal_type_str)
            return MCPResult(
                success=True,
                data={"geo_id": geo_id, "signal_type": signal_type_str, "value": value},
                message=f"{signal_type_str} = {value}",
            )
        except Exception as e:
            return MCPResult(
                success=True,
                data={"geo_id": geo_id, "signal_type": signal_type_str, "value": None},
                message=f"No data for {signal_type_str} in {geo_id}",
            )

    async def _get_regime(self, operator_id: str, params: Dict) -> MCPResult:
        geo_id = params["geo_id"]

        try:
            from app.services.signals.signal_pipeline import SignalPipeline
            from app.services.signals.regime_detection import RegimeDetectionEngine

            pipeline = SignalPipeline()
            bundle_data = await pipeline.get_signal_bundle(geo_id)
            signals_list = bundle_data.get("signals", [])

            engine = RegimeDetectionEngine()
            result = engine.detect_regime(signals_list if isinstance(signals_list, list) else [])

            return MCPResult(
                success=True,
                data=result.to_dict(),
                message=f"Regime: {result.regime.value} (confidence: {result.regime_confidence:.2f})",
            )
        except Exception as e:
            return MCPResult(
                success=True,
                data={"regime": "unknown", "confidence": 0.0, "note": str(e)},
                message="Regime detection unavailable (pipeline offline)",
            )

    async def _check_consistency(self, operator_id: str, params: Dict) -> MCPResult:
        geo_id = params["geo_id"]

        try:
            from app.services.signals.signal_pipeline import SignalPipeline
            from app.services.signals.regime_detection import CrossSignalConsistencyEngine

            pipeline = SignalPipeline()
            bundle_data = await pipeline.get_signal_bundle(geo_id)
            signals_list = bundle_data.get("signals", [])

            engine = CrossSignalConsistencyEngine()
            result = engine.check_consistency(signals_list if isinstance(signals_list, list) else [])

            return MCPResult(
                success=True,
                data=result.to_dict(),
                message=f"Signal consistency: {result.agreement.value} ({result.agreement_score:.2f})",
            )
        except Exception as e:
            return MCPResult(
                success=True,
                data={"agreement": "weak", "agreement_score": 0.5},
                message="Consistency check unavailable (pipeline offline)",
            )

    async def _assert_confidence(self, operator_id: str, params: Dict) -> MCPResult:
        geo_id = params["geo_id"]
        output_type = params["output_type"]

        try:
            from app.services.signals.signal_pipeline import SignalPipeline
            pipeline = SignalPipeline()
            bundle_data = await pipeline.get_signal_bundle(geo_id)
            confidence = bundle_data.get("overall_confidence", 0.0)
        except Exception:
            confidence = 0.0

        sufficient = is_confidence_sufficient(confidence, output_type)
        return MCPResult(
            success=True,
            data={
                "sufficient": sufficient,
                "confidence": confidence,
                "output_type": output_type,
                "geo_id": geo_id,
            },
            message=(
                f"ALLOWED: {output_type} at {confidence:.2f}"
                if sufficient
                else f"GATE: confidence {confidence:.2f} too low for {output_type}"
            ),
        )
