"""
Knowledge MCP Server

Wraps app/services/knowledge/* (VectorStore, LibrarianAgent, VoicePod)
for zero-token-cost agent access.

Tools exposed:
  retrieve(query, property_code)         → top-k docs from vector store
  get_property_basics(property_code)     → WiFi, door code, check-in/out
  search_house_rules(property_code)      → house rules relevant to query
  get_local_recommendations(category)   → curated local picks
  index_document(content, doc_type)     → add a doc to the vector store

Degradation handling:
  Every tool returns result.data["_degraded"] = True when the knowledge
  base is offline/uninitialized. Callers should:
    1. Check result.data.get("_degraded") before trusting content
    2. Surface the flag to the Watch Layer so ops is alerted
    3. Fall back gracefully (safe defaults, ask operator, etc.)

DB-session injection:
  Call KnowledgeMCPServer.set_db_session(session) at request startup
  (or use the global init_knowledge_mcp(db_session) helper) so the
  Librarian Agent has a live AsyncSession.  Without it the server
  stays in degraded mode but still returns safe stubs — it never raises.
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.base import MCPResult, MCPServer, MCPTool

logger = logging.getLogger(__name__)

# Transitional operator_id (legacy string) -> tenant_id (canonical UUID) map.
#
# The MCP base contract takes operator_id: str for tenant scoping. Different
# callers pass different values today:
#   - Legacy strings like "op_beach_habitats" (voice.py, some old paths)
#   - Canonical tenant UUIDs (newer paths post-Phase 3)
#
# This resolver handles both cases: if the value parses as a UUID, treat it
# as canonical tenant_id directly. Otherwise look up in this transitional
# map. Unknown legacy strings fail loud.
#
# When operator #2 onboards, two options:
#   (a) Add their entry to this map (cheap, one-line)
#   (b) Upgrade resolver to DB lookup against operator_accounts
#
# Phase 3D follow-up: as more callers migrate to passing canonical
# tenant_id directly, this map shrinks. Eventually it becomes empty and
# we drop the resolver entirely.
_LEGACY_OPERATOR_TO_TENANT: Dict[str, UUID] = {
    "op_beach_habitats": UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1"),
}


def _resolve_tenant_id(operator_id: str) -> UUID:
    """
    Resolve the MCP operator_id parameter to canonical tenant_id.

    Handles both legacy operator strings and direct tenant UUIDs.
    Raises ValueError on unknown legacy strings.
    """
    if operator_id in _LEGACY_OPERATOR_TO_TENANT:
        return _LEGACY_OPERATOR_TO_TENANT[operator_id]
    try:
        return UUID(operator_id)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"KnowledgeMCPServer: cannot resolve operator_id={operator_id!r} "
            f"to canonical tenant_id. Either pass a tenant UUID directly, or "
            f"add the legacy operator string to _LEGACY_OPERATOR_TO_TENANT "
            f"in knowledge_mcp.py."
        ) from exc


class KnowledgeMCPServer(MCPServer):
    """Direct in-process access to the Knowledge / RAG system."""

    server_name = "knowledge"
    server_description = "Property knowledge — house manuals, rules, local info, vector search"

    def __init__(self) -> None:
        super().__init__()
        # Injected at startup (or per-request).  None → degraded mode.
        self._db_session: Optional[AsyncSession] = None
        # Cached librarian so we don't reconstruct it every call
        self._librarian = None

    # ------------------------------------------------------------------
    # DB-session injection API
    # ------------------------------------------------------------------

    def set_db_session(self, db_session: Optional[AsyncSession]) -> None:
        """
        Inject the async DB session so the Librarian can do real queries.
        Call this once per request (or once at startup for a shared session).
        Passing None puts the server back into degraded / stub mode.
        """
        self._db_session = db_session
        # Invalidate the cached librarian whenever the session changes
        self._librarian = None

    @property
    def is_degraded(self) -> bool:
        """True when the server has no live DB session."""
        return self._db_session is None

    # ------------------------------------------------------------------
    # Degradation sentinel injected into every stubbed response
    # ------------------------------------------------------------------

    _OFFLINE_FLAG: Dict[str, Any] = {
        "_degraded": True,
        "_degradation_reason": "knowledge_mcp_offline — no db_session injected",
    }

    # ------------------------------------------------------------------
    # Tool manifest
    # ------------------------------------------------------------------

    def get_tools(self) -> List[MCPTool]:
        return [
            MCPTool(
                name="retrieve",
                description="Semantic search over property knowledge base",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "property_code": {"type": "string"},
                        "top_k": {"type": "integer", "default": 5},
                        "min_score": {"type": "number", "default": 0.35},
                    },
                    "required": ["query", "property_code"],
                },
                returns="List of {text, score, source} dicts; _degraded flag when offline",
                category="knowledge",
            ),
            MCPTool(
                name="get_property_basics",
                description="Get WiFi, door code, check-in/out times for a property",
                parameters={
                    "type": "object",
                    "properties": {
                        "property_code": {"type": "string"},
                    },
                    "required": ["property_code"],
                },
                returns=(
                    "Dict with wifi_network, wifi_password, door_code, "
                    "check_in_time, check_out_time; _degraded flag when offline"
                ),
                category="knowledge",
            ),
            MCPTool(
                name="search_house_rules",
                description="Find house rules relevant to a guest's question",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "e.g. 'can I bring my dog?'"},
                        "property_code": {"type": "string"},
                    },
                    "required": ["query", "property_code"],
                },
                returns="Relevant house rules as a list of strings; _degraded flag when offline",
                category="knowledge",
            ),
            MCPTool(
                name="get_local_recommendations",
                description="Get curated local recommendations (restaurants, activities)",
                parameters={
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["restaurant", "activity", "grocery", "beach", "nightlife"],
                        },
                        "property_code": {"type": "string"},
                        "limit": {"type": "integer", "default": 3},
                    },
                    "required": ["category", "property_code"],
                },
                returns="List of {name, description, phone, address} dicts; _degraded flag when offline",
                category="knowledge",
            ),
            MCPTool(
                name="index_document",
                description=(
                    "[DEPRECATED Phase 3] Use POST /api/v1/operator/properties/reconcile "
                    "instead. This tool now returns a deprecation error."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "doc_type": {
                            "type": "string",
                            "enum": ["house_manual", "house_rules", "local_guide", "amenity_guide", "faq"],
                        },
                        "property_code": {"type": "string"},
                        "source": {"type": "string", "default": "operator"},
                    },
                    "required": ["content", "doc_type", "property_code"],
                },
                returns="Document ID if indexed successfully",
                category="knowledge",
            ),
        ]

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def call(
        self,
        tool_name: str,
        operator_id: str,
        params: Dict[str, Any],
    ) -> MCPResult:
        if tool_name == "retrieve":
            return await self._retrieve(operator_id, params)
        elif tool_name == "get_property_basics":
            return await self._get_property_basics(operator_id, params)
        elif tool_name == "search_house_rules":
            return await self._search_house_rules(operator_id, params)
        elif tool_name == "get_local_recommendations":
            return await self._get_local_recommendations(operator_id, params)
        elif tool_name == "index_document":
            return await self._index_document(operator_id, params)
        return MCPResult(success=False, message=f"Unknown tool: {tool_name}")

    # ------------------------------------------------------------------
    # Librarian accessor (lazy, cached per db-session)
    # ------------------------------------------------------------------

    async def _get_librarian(self):
        if self._librarian is None and self._db_session is not None:
            try:
                from app.services.knowledge.librarian_agent import get_librarian_agent
                self._librarian = await get_librarian_agent(self._db_session)
            except Exception as exc:
                logger.error("[knowledge_mcp] Librarian init failed: %s", exc)
        return self._librarian

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def _retrieve(self, operator_id: str, params: Dict) -> MCPResult:
        query = params["query"]
        property_code = params["property_code"]
        top_k = params.get("top_k", 5)
        min_score = params.get("min_score", 0.35)

        librarian = await self._get_librarian()
        if librarian is None:
            logger.warning(
                "[knowledge_mcp] retrieve degraded — no db_session "
                "query='%.60s' property=%s",
                query, property_code,
            )
            return MCPResult(
                success=True,
                data={
                    "results": [],
                    "query": query,
                    "property_code": property_code,
                    **self._OFFLINE_FLAG,
                },
                message="Knowledge base offline (no db_session injected)",
            )

        try:
            tenant_id = _resolve_tenant_id(operator_id)
            from app.services.knowledge.librarian_agent import LibrarianQuery
            q = LibrarianQuery(
                query=query,
                tenant_id=tenant_id,
                property_code=property_code,
                top_k=top_k,
                min_score=min_score,
            )
            response = await librarian.retrieve(q)
            results = [
                {"text": chunk.text, "score": chunk.score, "source": getattr(chunk, "source", "unknown")}
                for chunk in (response.chunks or [])
            ]
            return MCPResult(
                success=True,
                data={
                    "results": results,
                    "query": query,
                    "property_code": property_code,
                    "_degraded": False,
                },
                message=f"Retrieved {len(results)} chunks (min_score={min_score})",
            )
        except Exception as exc:
            logger.error(
                "[knowledge_mcp] retrieve error: operator=%s exc=%s",
                operator_id,
                exc,
            )
            return MCPResult(
                success=True,
                data={
                    "results": [],
                    "query": query,
                    "property_code": property_code,
                    "_degraded": True,
                    "_degradation_reason": f"retrieve error: {exc}",
                },
                message=f"Retrieval error (safe fallback): {exc}",
            )

    async def _get_property_basics(self, operator_id: str, params: Dict) -> MCPResult:
        property_code = params["property_code"]

        librarian = await self._get_librarian()
        if librarian is None:
            logger.warning(
                "[knowledge_mcp] get_property_basics degraded property=%s", property_code
            )
            return MCPResult(
                success=True,
                data={
                    "property_code": property_code,
                    "wifi_network": None,
                    "wifi_password": None,
                    "door_code": None,
                    "check_in_time": "4:00 PM",
                    "check_out_time": "10:00 AM",
                    **self._OFFLINE_FLAG,
                },
                message="Property basics (defaults — knowledge base offline)",
            )

        try:
            tenant_id = _resolve_tenant_id(operator_id)
            basics = await librarian.retrieve_property_basics(tenant_id, property_code)
            if basics:
                return MCPResult(
                    success=True,
                    data={
                        "property_code": property_code,
                        "wifi_network": basics.get("wifi_network"),
                        "wifi_password": basics.get("wifi_password"),
                        "door_code": basics.get("door_code"),
                        "check_in_time": basics.get("check_in_time", "4:00 PM"),
                        "check_out_time": basics.get("check_out_time", "10:00 AM"),
                        "_degraded": False,
                    },
                    message=f"Property basics loaded for {property_code}",
                )
            # Property found in DB but no basics populated — partial degradation
            return MCPResult(
                success=True,
                data={
                    "property_code": property_code,
                    "wifi_network": None,
                    "wifi_password": None,
                    "door_code": None,
                    "check_in_time": "4:00 PM",
                    "check_out_time": "10:00 AM",
                    "_degraded": True,
                    "_degradation_reason": "property_basics_not_populated",
                },
                message=f"Property basics empty for {property_code} — operator needs to populate",
            )
        except Exception as exc:
            logger.error(
                "[knowledge_mcp] get_property_basics error: operator=%s exc=%s",
                operator_id,
                exc,
            )
            return MCPResult(
                success=True,
                data={
                    "property_code": property_code,
                    "wifi_network": None,
                    "wifi_password": None,
                    "door_code": None,
                    "check_in_time": "4:00 PM",
                    "check_out_time": "10:00 AM",
                    "_degraded": True,
                    "_degradation_reason": str(exc),
                },
                message=f"Property basics error (safe defaults): {exc}",
            )

    async def _search_house_rules(self, operator_id: str, params: Dict) -> MCPResult:
        query = params["query"]
        property_code = params["property_code"]

        librarian = await self._get_librarian()
        if librarian is None:
            return MCPResult(
                success=True,
                data={"rules": [], "query": query, "property_code": property_code, **self._OFFLINE_FLAG},
                message="House rules (knowledge base offline)",
            )

        try:
            tenant_id = _resolve_tenant_id(operator_id)
            from app.services.knowledge.librarian_agent import LibrarianQuery
            q = LibrarianQuery(
                query=query,
                tenant_id=tenant_id,
                property_code=property_code,
                top_k=3,
                min_score=0.4,
                doc_types=["house_rules", "house_manual"],
            )
            response = await librarian.retrieve(q)
            rules = [chunk.text for chunk in (response.chunks or [])]
            return MCPResult(
                success=True,
                data={"rules": rules, "query": query, "property_code": property_code, "_degraded": False},
                message=f"Found {len(rules)} relevant house rules",
            )
        except Exception as exc:
            logger.error(
                "[knowledge_mcp] search_house_rules error: operator=%s exc=%s",
                operator_id,
                exc,
            )
            return MCPResult(
                success=True,
                data={"rules": [], "query": query, "property_code": property_code,
                      "_degraded": True, "_degradation_reason": str(exc)},
                message=f"House rules error (safe fallback): {exc}",
            )

    async def _get_local_recommendations(self, operator_id: str, params: Dict) -> MCPResult:
        category = params["category"]
        property_code = params["property_code"]
        limit = params.get("limit", 3)

        librarian = await self._get_librarian()
        if librarian is None:
            return MCPResult(
                success=True,
                data={
                    "category": category,
                    "property_code": property_code,
                    "recommendations": [],
                    **self._OFFLINE_FLAG,
                },
                message=f"Local {category} recommendations (knowledge base offline)",
            )

        try:
            tenant_id = _resolve_tenant_id(operator_id)
            from app.services.knowledge.librarian_agent import LibrarianQuery
            q = LibrarianQuery(
                query=f"{category} recommendations near {property_code}",
                tenant_id=tenant_id,
                property_code=property_code,
                top_k=limit,
                min_score=0.3,
                doc_types=["local_guide"],
            )
            response = await librarian.retrieve(q)
            recs = [
                {"text": chunk.text, "score": chunk.score}
                for chunk in (response.chunks or [])
            ]
            return MCPResult(
                success=True,
                data={
                    "category": category,
                    "property_code": property_code,
                    "recommendations": recs,
                    "_degraded": False,
                },
                message=f"Found {len(recs)} {category} recommendations",
            )
        except Exception as exc:
            logger.error(
                "[knowledge_mcp] get_local_recommendations error: operator=%s exc=%s",
                operator_id,
                exc,
            )
            return MCPResult(
                success=True,
                data={
                    "category": category,
                    "property_code": property_code,
                    "recommendations": [],
                    "_degraded": True,
                    "_degradation_reason": str(exc),
                },
                message=f"Recommendations error (safe fallback): {exc}",
            )

    async def _index_document(self, operator_id: str, params: Dict) -> MCPResult:
        """
        DEPRECATED as of Phase 3.

        The canonical knowledge ingestion path is
        POST /api/v1/operator/properties/reconcile, which orchestrates
        guidebook ingestion via guidebook_ingest_service for an entire
        operator portfolio at once.

        This MCP tool was designed for agent-driven single-document
        indexing against the pre-Phase-3 KnowledgeIndexer.index() API
        (which no longer exists). It was not the primary indexing
        path in production and has no current callers.

        Returning a clean failure here rather than silently no-op'ing
        or pretending to succeed.
        """
        logger.warning(
            "[knowledge_mcp] _index_document called but is deprecated "
            "(operator=%s, doc_type=%s, property_code=%s). Use "
            "POST /api/v1/operator/properties/reconcile instead.",
            operator_id,
            params.get("doc_type"),
            params.get("property_code"),
        )
        return MCPResult(
            success=False,
            message=(
                "index_document is deprecated as of Phase 3. "
                "Use POST /api/v1/operator/properties/reconcile to ingest "
                "guidebooks for an operator portfolio."
            ),
        )


# ---------------------------------------------------------------------------
# Per-request session injection helper
# ---------------------------------------------------------------------------

def init_knowledge_mcp(db_session: AsyncSession) -> None:
    """
    Inject a live async DB session into the global KnowledgeMCPServer.

    Call this once per request from a FastAPI dependency or middleware so
    every MCP call within that request has a real DB connection.

    Example (FastAPI dep):
        @app.middleware("http")
        async def inject_mcp_session(request: Request, call_next):
            async with AsyncSessionLocal() as db:
                init_knowledge_mcp(db)
                response = await call_next(request)
            init_knowledge_mcp(None)   # clear after request
            return response
    """
    from app.mcp.registry import get_mcp_registry
    registry = get_mcp_registry()
    server = registry._servers.get("knowledge")
    if isinstance(server, KnowledgeMCPServer):
        server.set_db_session(db_session)
    else:
        logger.warning("[knowledge_mcp] init_knowledge_mcp: knowledge server not found in registry")
