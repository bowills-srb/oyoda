"""
MCP (Model Context Protocol) Infrastructure for Beach Habitats

This package exposes your internal systems as MCP servers that agents
can call WITHOUT burning tokens on HTTP round-trips or re-parsing data.

Architecture:
    Agent (LLM)
        │
        ├──► SignalMCP       → direct in-process call to signal_pipeline
        ├──► KnowledgeMCP    → direct in-process call to librarian_agent
        ├──► PMSMCP          → direct in-process call to connectors
        ├──► ScraperMCP      → direct in-process call to market_scraper
        ├──► DetectorMCP     → direct in-process call to detector_engine
        └──► SanitizerMCP    → PII scrubber (runs BEFORE any LLM sees data)

Key principle: Every MCP server is STATELESS and TENANT-ISOLATED.
No cross-tenant data leakage. Every call requires operator_id.

Cost savings vs HTTP/external MCP:
    - No serialization overhead for large signal bundles
    - No network latency (in-process)
    - No token cost for tool-call round trips to external services
    - Shared process memory for signal cache hits
"""
from .registry import MCPRegistry, get_mcp_registry
from .base import MCPServer, MCPTool, MCPResult, MCPError

__all__ = [
    "MCPRegistry",
    "get_mcp_registry",
    "MCPServer",
    "MCPTool",
    "MCPResult",
    "MCPError",
]
