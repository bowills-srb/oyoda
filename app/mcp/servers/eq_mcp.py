"""
EQ (Emotional Intelligence) MCP Server

Wraps app/services/agents/emotional_intelligence/eq_analyzer.py
for zero-token sentiment analysis.

This is the MCP Gemini specifically called out as the EQ MCP:
  "A specialized server that takes the last 30 seconds of voice audio
   and returns a Sentiment Payload (vibe: 'agitated', urgency: 8/10)"

Tools exposed:
  analyze_text(text, session_id)           → EmotionalContext
  analyze_session_trend(session_id)        → trend over conversation
  get_urgency_level(text)                  → quick urgency int 1-10
  should_escalate(session_id)              → bool + reason

Why this saves tokens:
  Without this MCP, every agent response must include EQ context in
  the system prompt (200-400 tokens per turn).
  With this MCP, agents call analyze_text() and get a 3-field struct.
  At 1000 conversations/day × 10 turns each × 300 tokens saved = 3M tokens/day.
  At $3/M tokens that's ~$9/day or $3,285/year saved from this one MCP alone.
"""

import logging
from typing import Any, Dict, List, Optional

from app.mcp.base import MCPResult, MCPServer, MCPTool

logger = logging.getLogger(__name__)


class EQMCPServer(MCPServer):
    """Direct in-process access to the EQ Analyzer."""

    server_name = "eq"
    server_description = "Emotional intelligence — guest sentiment, urgency detection, escalation signals"

    def get_tools(self) -> List[MCPTool]:
        return [
            MCPTool(
                name="analyze_text",
                description="Analyze emotional state and urgency from guest text",
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "session_id": {"type": "string"},
                    },
                    "required": ["text"],
                },
                returns="Dict: {state, urgency_level, urgency_score, mode, tone, prompt_context}",
                category="eq",
            ),
            MCPTool(
                name="get_urgency_level",
                description="Quick urgency check 1-10 from text — for routing decisions",
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                    },
                    "required": ["text"],
                },
                returns="Dict: {urgency_score: int 1-10, urgency_label: str, should_escalate: bool}",
                category="eq",
            ),
            MCPTool(
                name="should_escalate",
                description="Should this conversation be escalated to a human operator?",
                parameters={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "current_text": {"type": "string"},
                    },
                    "required": [],
                },
                returns="Dict: {escalate: bool, reason: str, urgency_level: str}",
                category="eq",
            ),
            MCPTool(
                name="get_response_guidance",
                description="Get tone/mode guidance for generating a response based on emotional context",
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "session_id": {"type": "string"},
                    },
                    "required": ["text"],
                },
                returns="Dict: {mode, tone, instructions, urgency_level}",
                category="eq",
            ),
        ]

    async def call(
        self,
        tool_name: str,
        operator_id: str,
        params: Dict[str, Any],
    ) -> MCPResult:
        if tool_name == "analyze_text":
            return await self._analyze_text(operator_id, params)
        elif tool_name == "get_urgency_level":
            return await self._get_urgency_level(operator_id, params)
        elif tool_name == "should_escalate":
            return await self._should_escalate(operator_id, params)
        elif tool_name == "get_response_guidance":
            return await self._get_response_guidance(operator_id, params)
        return MCPResult(success=False, message=f"Unknown tool: {tool_name}")

    async def _analyze_text(self, operator_id: str, params: Dict) -> MCPResult:
        text = params["text"]
        session_id = params.get("session_id", "")

        try:
            from app.services.agents.emotional_intelligence.eq_analyzer import get_eq_analyzer
            analyzer = get_eq_analyzer()
            context = await analyzer.analyze_text(text, session_id=session_id)

            return MCPResult(
                success=True,
                data={
                    "state": context.state.value if hasattr(context.state, 'value') else str(context.state),
                    "urgency_level": context.urgency_level.value if hasattr(context.urgency_level, 'value') else str(context.urgency_level),
                    "urgency_score": getattr(context, 'urgency_score', None),
                    "mode": getattr(context, 'mode', None),
                    "tone": getattr(context, 'tone', None),
                    "prompt_context": context.to_prompt_context() if hasattr(context, 'to_prompt_context') else "",
                },
                message=f"EQ: {context.state} / urgency: {context.urgency_level}",
            )
        except ImportError:
            return self._fallback_eq(text)
        except Exception as e:
            return self._fallback_eq(text)

    async def _get_urgency_level(self, operator_id: str, params: Dict) -> MCPResult:
        text = params["text"]

        try:
            from app.services.agents.emotional_intelligence.eq_analyzer import get_eq_analyzer
            analyzer = get_eq_analyzer()
            context = await analyzer.analyze_text(text)

            urgency_level = context.urgency_level.value if hasattr(context.urgency_level, 'value') else str(context.urgency_level)
            urgency_score = getattr(context, 'urgency_score', 3)

            return MCPResult(
                success=True,
                data={
                    "urgency_score": urgency_score,
                    "urgency_label": urgency_level,
                    "should_escalate": urgency_level in ("crisis", "high"),
                },
                message=f"Urgency: {urgency_score}/10 ({urgency_level})",
            )
        except Exception:
            return self._fallback_urgency(text)

    async def _should_escalate(self, operator_id: str, params: Dict) -> MCPResult:
        text = params.get("current_text", "")
        session_id = params.get("session_id", "")

        try:
            from app.services.agents.emotional_intelligence.eq_analyzer import get_eq_analyzer
            analyzer = get_eq_analyzer()
            context = await analyzer.analyze_text(text, session_id=session_id)

            urgency_level = context.urgency_level.value if hasattr(context.urgency_level, 'value') else str(context.urgency_level)
            state = context.state.value if hasattr(context.state, 'value') else str(context.state)

            escalate = urgency_level == "crisis" or state in ("angry", "distressed")
            reason = ""
            if urgency_level == "crisis":
                reason = "Crisis-level urgency detected"
            elif state in ("angry", "distressed"):
                reason = f"Guest state: {state}"

            return MCPResult(
                success=True,
                data={"escalate": escalate, "reason": reason, "urgency_level": urgency_level},
                message=f"{'ESCALATE' if escalate else 'No escalation needed'}: {reason}",
            )
        except Exception:
            return MCPResult(
                success=True,
                data={"escalate": False, "reason": "EQ analyzer offline", "urgency_level": "unknown"},
                message="Escalation check (EQ offline)",
            )

    async def _get_response_guidance(self, operator_id: str, params: Dict) -> MCPResult:
        text = params["text"]

        try:
            from app.services.agents.emotional_intelligence.eq_analyzer import get_eq_analyzer
            analyzer = get_eq_analyzer()
            context = await analyzer.analyze_text(text)
            prompt_ctx = context.to_prompt_context() if hasattr(context, 'to_prompt_context') else ""

            urgency_level = context.urgency_level.value if hasattr(context.urgency_level, 'value') else "normal"
            state = context.state.value if hasattr(context.state, 'value') else "neutral"

            # Map state → guidance (mirrors VoicePod's existing logic)
            MODE_MAP = {
                "crisis": ("emergency", "calm and directive"),
                "high": ("urgent", "concise and efficient"),
                "frustrated": ("empathetic", "warm and apologetic"),
                "anxious": ("reassuring", "patient and thorough"),
                "happy": ("enthusiastic", "warm and friendly"),
            }
            mode, tone = MODE_MAP.get(urgency_level, MODE_MAP.get(state, ("standard", "helpful")))

            return MCPResult(
                success=True,
                data={
                    "mode": mode,
                    "tone": tone,
                    "urgency_level": urgency_level,
                    "state": state,
                    "instructions": prompt_ctx,
                },
                message=f"Response guidance: {mode} mode, {tone} tone",
            )
        except Exception:
            return MCPResult(
                success=True,
                data={"mode": "standard", "tone": "helpful", "urgency_level": "normal"},
                message="Default guidance (EQ offline)",
            )

    # ─────────────────────────────────────────
    # Fallbacks (pure keyword heuristics — zero tokens, zero API)
    # ─────────────────────────────────────────

    def _fallback_eq(self, text: str) -> MCPResult:
        """Heuristic EQ when analyzer is offline — better than nothing."""
        text_lower = text.lower()
        crisis_words = {"emergency", "fire", "flood", "break-in", "injured", "ambulance", "help"}
        urgent_words = {"urgent", "asap", "immediately", "now", "broken", "not working", "can't"}
        angry_words = {"terrible", "awful", "disgusting", "unacceptable", "refund", "manager", "lawsuit"}

        if any(w in text_lower for w in crisis_words):
            state, urgency = "distressed", "crisis"
        elif any(w in text_lower for w in angry_words):
            state, urgency = "frustrated", "high"
        elif any(w in text_lower for w in urgent_words):
            state, urgency = "anxious", "medium"
        else:
            state, urgency = "neutral", "normal"

        return MCPResult(
            success=True,
            data={"state": state, "urgency_level": urgency, "_source": "heuristic_fallback"},
            message=f"EQ (heuristic): {state} / {urgency}",
        )

    def _fallback_urgency(self, text: str) -> MCPResult:
        result = self._fallback_eq(text)
        urgency_label = result.data["urgency_level"]
        score_map = {"crisis": 9, "high": 7, "medium": 5, "normal": 3}
        score = score_map.get(urgency_label, 3)
        return MCPResult(
            success=True,
            data={
                "urgency_score": score,
                "urgency_label": urgency_label,
                "should_escalate": score >= 7,
                "_source": "heuristic_fallback",
            },
            message=f"Urgency: {score}/10 ({urgency_label})",
        )
