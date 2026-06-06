"""
MCP Registry — The "Trust Registry" Gemini described.

All agent-accessible MCP servers are hard-coded here.
Agents CANNOT discover or register new servers at runtime.
This prevents prompt injection via fake MCP server references.

Usage:
    registry = get_mcp_registry()
    result = await registry.call("signal", "get_bundle", operator_id, params)
    tools = registry.list_tools()          # For agent system prompt
    servers = registry.list_servers()      # For dashboard
"""

import logging
from typing import Dict, List, Optional

from .base import MCPServer, MCPTool, MCPResult

logger = logging.getLogger(__name__)


class MCPRegistry:
    """
    Hard-coded, immutable registry of vetted MCP servers.

    WHY HARD-CODED:
        If agents could register new servers dynamically, a prompt injection
        attack could point the agent at a malicious MCP server that exfiltrates
        data or executes arbitrary actions. Hard-coding is the security boundary.

    ADDING A NEW SERVER:
        1. Build the server in app/mcp/servers/
        2. Import it here
        3. Register it in _build_registry()
        4. Document what data it exposes and to whom
    """

    def __init__(self):
        self._servers: Dict[str, MCPServer] = {}
        self._initialized = False

    def _build_registry(self) -> None:
        """Register all vetted internal MCP servers."""
        # Import here to avoid circular imports at module load time
        from .servers.signal_mcp import SignalMCPServer
        from .servers.knowledge_mcp import KnowledgeMCPServer
        from .servers.pms_mcp import PMSMCPServer
        from .servers.scraper_mcp import ScraperMCPServer
        from .servers.detector_mcp import DetectorMCPServer
        from .servers.sanitizer_mcp import SanitizerMCPServer
        from .servers.eq_mcp import EQMCPServer
        from .servers.governance_mcp import GovernanceMCPServer
        from .servers.concierge_mcp import ConciergeMCPServer
        from .servers.neighborhood_intel_mcp import NeighborhoodIntelligenceMCPServer

        # Registration order matters for display in agent prompts
        # Concierge first — it's the primary consumer-facing server
        self._register(ConciergeMCPServer())
        self._register(NeighborhoodIntelligenceMCPServer())
        self._register(EQMCPServer())
        self._register(SignalMCPServer())
        self._register(KnowledgeMCPServer())
        self._register(PMSMCPServer())
        self._register(ScraperMCPServer())
        self._register(DetectorMCPServer())
        self._register(SanitizerMCPServer())
        self._register(GovernanceMCPServer())

    def _register(self, server: MCPServer) -> None:
        name = server.server_name
        if name in self._servers:
            raise ValueError(f"Duplicate MCP server name: {name}")
        self._servers[name] = server
        logger.info(f"[MCPRegistry] Registered server: {name}")

    def initialize(self) -> None:
        """Build the registry. Call once at app startup."""
        if self._initialized:
            return
        self._build_registry()
        self._initialized = True
        logger.info(f"[MCPRegistry] Initialized with {len(self._servers)} servers")

    async def call(
        self,
        server_name: str,
        tool_name: str,
        operator_id: str,
        params: Dict,
    ) -> MCPResult:
        """
        Route a call to the correct server and tool.

        This is the single entry point for all agent MCP calls.
        Validates server exists before calling.
        """
        if not self._initialized:
            self.initialize()

        server = self._servers.get(server_name)
        if not server:
            from .base import MCPError
            return MCPError(
                code="SERVER_NOT_FOUND",
                message=f"No MCP server named '{server_name}'. Available: {list(self._servers.keys())}",
                tool_name=tool_name,
                operator_id=operator_id,
            ).to_result()

        return await server.safe_call(tool_name, operator_id, params)

    def list_tools(self, server_name: Optional[str] = None) -> List[MCPTool]:
        """Return all tools (or tools for a specific server)."""
        if not self._initialized:
            self.initialize()

        tools = []
        for name, server in self._servers.items():
            if server_name and name != server_name:
                continue
            tools.extend(server.get_tools())
        return tools

    def list_servers(self) -> List[Dict]:
        """Return server metadata for the dashboard."""
        if not self._initialized:
            self.initialize()

        return [
            {
                "name": s.server_name,
                "description": s.server_description,
                "tool_count": len(s.get_tools()),
                "call_count": s._call_count,
            }
            for s in self._servers.values()
        ]

    def build_agent_tool_manifest(self, categories: Optional[List[str]] = None) -> str:
        """
        Build a compact tool manifest string for injection into agent system prompts.

        Categories filter to only relevant tools (e.g. a VoicePod only needs
        'knowledge' tools, not 'scraper' tools).
        """
        if not self._initialized:
            self.initialize()

        lines = ["AVAILABLE MCP TOOLS (call via mcp.call(server, tool, params)):"]
        for server_name, server in self._servers.items():
            server_tools = server.get_tools()
            if categories:
                server_tools = [t for t in server_tools if t.category in categories]
            if not server_tools:
                continue
            lines.append(f"\n[{server_name}] {server.server_description}")
            for tool in server_tools:
                lines.append(tool.to_llm_description())

        return "\n".join(lines)


# ─────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────
_registry: Optional[MCPRegistry] = None


def get_mcp_registry() -> MCPRegistry:
    """Get (or lazily create) the global MCP registry."""
    global _registry
    if _registry is None:
        _registry = MCPRegistry()
        _registry.initialize()
    return _registry
