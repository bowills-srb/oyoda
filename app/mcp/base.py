"""
MCP Base Classes — The contract every internal MCP server must implement.

Design principles:
1. Every call is tenant-isolated (operator_id required)
2. Every call is auditable (returns MCPResult with trace)
3. Servers are stateless — no cross-call memory
4. Errors are structured — agents can handle them predictably
5. Tools declare their schema — agents can self-discover capabilities
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Type
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class MCPResult:
    """
    Structured result from any MCP tool call.

    Agents receive this and can decide what to do with it.
    The trace_id links this call to audit logs and Watch Layer events.
    """
    success: bool
    data: Any = None

    # For agents to explain what happened
    message: str = ""

    # Observability
    trace_id: str = field(default_factory=lambda: str(uuid4())[:8])
    latency_ms: float = 0.0
    tool_name: str = ""
    operator_id: Optional[str] = None

    # Cost attribution (zero for in-process calls)
    token_cost: float = 0.0

    def to_agent_context(self) -> str:
        """Serialize result as a compact string for LLM context injection."""
        if not self.success:
            return f"[{self.tool_name} ERROR] {self.message}"
        if isinstance(self.data, dict):
            import json
            return json.dumps(self.data, default=str)
        return str(self.data)


@dataclass
class MCPError:
    """Structured error from an MCP call."""
    code: str
    message: str
    tool_name: str
    operator_id: Optional[str] = None
    retryable: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def to_result(self) -> MCPResult:
        return MCPResult(
            success=False,
            message=f"[{self.code}] {self.message}",
            tool_name=self.tool_name,
            operator_id=self.operator_id,
        )


@dataclass
class MCPTool:
    """
    Descriptor for a single tool exposed by an MCP server.

    Agents use this for self-discovery: they can ask "what can you do?"
    and receive a list of MCPTools with schemas.
    """
    name: str
    description: str
    parameters: Dict[str, Any]   # JSON Schema
    returns: str                 # Human description of return value
    requires_operator_id: bool = True
    category: str = "general"    # e.g. "signals", "knowledge", "pms", "scraper"

    def to_llm_description(self) -> str:
        """Compact description for injecting into agent system prompt."""
        params = ", ".join(self.parameters.get("required", []))
        return f"  {self.name}({params}) → {self.returns}"


class MCPServer(ABC):
    """
    Abstract base for all internal MCP servers.

    Subclass this for each domain:
        class SignalMCPServer(MCPServer): ...
        class KnowledgeMCPServer(MCPServer): ...
    """

    server_name: str = "base_mcp"
    server_description: str = "Base MCP server"

    def __init__(self):
        self._audit_log: List[Dict[str, Any]] = []
        self._call_count: int = 0

    @abstractmethod
    def get_tools(self) -> List[MCPTool]:
        """Return all tools this server exposes."""
        pass

    @abstractmethod
    async def call(
        self,
        tool_name: str,
        operator_id: str,
        params: Dict[str, Any],
    ) -> MCPResult:
        """Execute a tool call. Must be tenant-safe."""
        pass

    async def safe_call(
        self,
        tool_name: str,
        operator_id: str,
        params: Dict[str, Any],
    ) -> MCPResult:
        """Wrapper that adds timing, audit logging, and error catching."""
        start = time.time()
        self._call_count += 1
        trace_id = str(uuid4())[:8]

        try:
            result = await self.call(tool_name, operator_id, params)
            result.latency_ms = (time.time() - start) * 1000
            result.trace_id = trace_id
            result.tool_name = tool_name
            result.operator_id = operator_id

            self._audit_log.append({
                "trace_id": trace_id,
                "server": self.server_name,
                "tool": tool_name,
                "operator_id": operator_id,
                "success": result.success,
                "latency_ms": result.latency_ms,
                "ts": datetime.now(timezone.utc).isoformat(),
            })

            return result

        except Exception as e:
            logger.error(f"[MCP:{self.server_name}:{tool_name}] {e}", exc_info=True)
            err = MCPError(
                code="INTERNAL_ERROR",
                message=str(e),
                tool_name=tool_name,
                operator_id=operator_id,
            )
            result = err.to_result()
            result.latency_ms = (time.time() - start) * 1000
            result.trace_id = trace_id
            return result

    def get_recent_audit(self, n: int = 20) -> List[Dict[str, Any]]:
        return list(reversed(self._audit_log[-n:]))
