"""
Vector Store - pgvector-based semantic search.

Uses the knowledge_embeddings table with pgvector extension
for efficient similarity search across operator knowledge bases.

Key design decisions:
- Uses sentence-transformers (all-MiniLM-L6-v2) for embeddings (384 dim)
- Partitioned by tenant_id (canonical UUID, per migration 071)
- Supports filtering by property_code and doc_type
- Cosine similarity for semantic matching
"""

import hashlib
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_connect import asyncpg_connection_kwargs, normalize_asyncpg_dsn

logger = logging.getLogger(__name__)

# Embedding dimension for all-MiniLM-L6-v2
EMBEDDING_DIM = 384


@dataclass
class Document:
    """A document with content and metadata."""
    content: str
    metadata: Dict[str, Any]
    doc_id: Optional[str] = None
    score: Optional[float] = None
    
    def __post_init__(self):
        if not self.doc_id:
            # Generate deterministic doc_id from content + key metadata
            key_parts = [
                self.content[:200],
                str(self.metadata.get("tenant_id", "")),
                self.metadata.get("property_code", ""),
                self.metadata.get("doc_type", ""),
            ]
            self.doc_id = hashlib.md5("|".join(key_parts).encode()).hexdigest()[:16]


@dataclass
class RetrievalResult:
    """Result from a retrieval query."""
    documents: List[Document]
    query: str
    retrieval_time_ms: float
    total_candidates: int


# Module-level singleton — loaded once, reused across all requests
_embedding_model_instance: Optional['EmbeddingModel'] = None
_vector_pool = None
_vector_pool_lock: Optional[asyncio.Lock] = None


class EmbeddingModel:
    """
    Sentence transformer embedding model.
    
    Uses all-MiniLM-L6-v2 for fast, high-quality embeddings.
    Falls back to a simple TF-IDF-like approach if sentence-transformers unavailable.
    """
    
    def __init__(self):
        self._model = None
        self._fallback_mode = False
        self._load_model()
    
    @classmethod
    def get_instance(cls) -> 'EmbeddingModel':
        """Get or create the singleton embedding model."""
        global _embedding_model_instance
        if _embedding_model_instance is None:
            _embedding_model_instance = cls()
        return _embedding_model_instance
    
    def _load_model(self):
        """Load the embedding model."""
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Loaded sentence-transformers model: all-MiniLM-L6-v2")
        except ImportError:
            logger.warning(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers --break-system-packages"
            )
            self._fallback_mode = True
    
    def encode(self, texts: List[str]) -> np.ndarray:
        """Encode texts to embeddings."""
        if self._fallback_mode:
            return self._fallback_encode(texts)
        
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return embeddings.astype(np.float32)
    
    def _fallback_encode(self, texts: List[str]) -> np.ndarray:
        """
        Simple fallback encoding using character n-grams.
        Not as good as sentence-transformers but works without dependencies.
        """
        def text_to_vector(text: str) -> np.ndarray:
            # Simple character 3-gram hashing
            vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
            text = text.lower()
            for i in range(len(text) - 2):
                ngram = text[i:i+3]
                idx = hash(ngram) % EMBEDDING_DIM
                vec[idx] += 1
            # Normalize
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec /= norm
            return vec
        
        return np.array([text_to_vector(t) for t in texts])


class VectorStore:
    """
    pgvector-based vector store for semantic search.
    
    Uses the knowledge_embeddings table which has:
    - id: UUID primary key
    - doc_id: deterministic document identifier
    - tenant_id: canonical tenant isolation
    - property_code: property filter (nullable)
    - doc_type: document type (dining, activity, property_info, etc.)
    - content: the text content
    - metadata: JSONB for additional data
    - embedding: vector(384) for similarity search
    - created_at: row insertion timestamp
    - updated_at: row last-modified timestamp
    
    Example usage:
        store = VectorStore(session)
        
        # Index documents
        await store.add_documents(documents)
        
        # Search
        results = await store.similarity_search(
            query="good seafood restaurant",
            tenant_id=UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1"),
            top_k=5
        )
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self._embedder = EmbeddingModel.get_instance()

    @staticmethod
    def _require_tenant_id(metadata: Dict[str, Any]) -> str:
        """Extract the canonical tenant_id from document metadata."""
        tenant_id = metadata.get("tenant_id")
        if tenant_id is None:
            raise ValueError("Document metadata must include tenant_id for knowledge_embeddings writes")
        return str(tenant_id)
    
    async def add_documents(
        self,
        documents: List[Document],
        batch_size: int = 100,
    ) -> Dict[str, Any]:
        """
        Add documents to the vector store.
        
        Upserts based on doc_id - existing documents are updated.
        """
        if not documents:
            return {"inserted": 0, "updated": 0}
        
        inserted = 0
        updated = 0
        
        # Process in batches
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            
            # Generate embeddings
            texts = [doc.content for doc in batch]
            embeddings = self._embedder.encode(texts)
            
            for doc, embedding in zip(batch, embeddings):
                tenant_id = self._require_tenant_id(doc.metadata)
                property_code = doc.metadata.get("property_code")
                doc_type = doc.metadata.get("doc_type", "general")

                # Check if exists
                result = await self.session.execute(
                    text("SELECT id FROM knowledge_embeddings WHERE doc_id = :doc_id"),
                    {"doc_id": doc.doc_id}
                )
                existing = result.fetchone()
                
                # Convert embedding to PostgreSQL vector format
                embedding_str = "[" + ",".join(map(str, embedding.tolist())) + "]"
                
                import json
                metadata_json = json.dumps(doc.metadata)
                
                if existing:
                    # Update
                    await self.session.execute(
                        text("""
                            UPDATE knowledge_embeddings 
                            SET tenant_id = CAST(:tenant_id AS uuid),
                                property_code = :property_code,
                                doc_type = :doc_type,
                                content = :content,
                                metadata = CAST(:metadata AS jsonb),
                                embedding = CAST(:embedding AS vector),
                                updated_at = NOW()
                            WHERE doc_id = :doc_id
                        """),
                        {
                            "doc_id": doc.doc_id,
                            "tenant_id": tenant_id,
                            "property_code": property_code,
                            "doc_type": doc_type,
                            "content": doc.content,
                            "metadata": metadata_json,
                            "embedding": embedding_str,
                        }
                    )
                    updated += 1
                else:
                    # Insert
                    await self.session.execute(
                        text("""
                            INSERT INTO knowledge_embeddings 
                            (doc_id, tenant_id, property_code, doc_type, content, metadata, embedding, updated_at)
                            VALUES (:doc_id, CAST(:tenant_id AS uuid), :property_code, :doc_type, :content,
                                    CAST(:metadata AS jsonb), CAST(:embedding AS vector), NOW())
                        """),
                        {
                            "doc_id": doc.doc_id,
                            "tenant_id": tenant_id,
                            "property_code": property_code,
                            "doc_type": doc_type,
                            "content": doc.content,
                            "metadata": metadata_json,
                            "embedding": embedding_str,
                        }
                    )
                    inserted += 1
            
            await self.session.commit()
        
        logger.info(f"VectorStore: added {inserted} new, updated {updated} existing documents")
        return {"inserted": inserted, "updated": updated}
    
    async def similarity_search(
        self,
        query: str,
        tenant_id: UUID,
        property_code: Optional[str] = None,
        doc_types: Optional[List[str]] = None,
        top_k: int = 5,
        min_score: float = 0.1,
    ) -> RetrievalResult:
        """
        Search for similar documents using cosine similarity.
        Fetches candidates via asyncpg, scores in Python with numpy.
        """
        import time, json as _json
        start = time.time()
        
        # Generate query embedding
        query_embedding = self._embedder.encode([query])[0]
        
        embedding_str = "[" + ",".join(map(str, query_embedding.tolist())) + "]"

        # Keep filtering parameterized to avoid brittle string assembly.
        doc_types_filter: Optional[List[str]] = doc_types if doc_types else None
        property_filter: Optional[str] = property_code if property_code else None
        fetch_k = max(int(top_k), 1) * 5

        count_sql = """
            SELECT COUNT(*)::bigint
            FROM knowledge_embeddings
            WHERE tenant_id = $1::uuid
              AND ($2::text IS NULL OR property_code = $2 OR property_code IS NULL)
              AND ($3::text[] IS NULL OR doc_type = ANY($3::text[]))
        """
        vector_sql = """
            SELECT
                doc_id,
                content,
                metadata,
                property_code,
                doc_type,
                1 - (embedding <=> $1::vector) / 2 AS similarity
            FROM knowledge_embeddings
            WHERE tenant_id = $2::uuid
              AND ($3::text IS NULL OR property_code = $3 OR property_code IS NULL)
              AND ($4::text[] IS NULL OR doc_type = ANY($4::text[]))
            ORDER BY embedding <=> $1::vector
            LIMIT $5
        """
        fallback_sql = """
            SELECT
                doc_id,
                content,
                metadata,
                property_code,
                doc_type,
                embedding::text AS embedding
            FROM knowledge_embeddings
            WHERE tenant_id = $1::uuid
              AND ($2::text IS NULL OR property_code = $2 OR property_code IS NULL)
              AND ($3::text[] IS NULL OR doc_type = ANY($3::text[]))
        """

        all_rows = []
        candidate_count = 0
        try:
            import asyncpg
            pool = await _get_vector_pool()
            async with pool.acquire() as conn:

                candidate_count = await conn.fetchval(
                    count_sql,
                    str(tenant_id),
                    property_filter,
                    doc_types_filter,
                )
                logger.debug(
                    "VectorStore candidates=%s tenant=%s property=%s doc_types=%s",
                    candidate_count, tenant_id, property_filter, doc_types_filter,
                )

                # If doc-type filtering excludes everything, fall back to all types.
                if candidate_count == 0 and doc_types_filter:
                    logger.warning(
                        "VectorStore doc_type filter produced zero candidates; retrying without doc_types."
                    )
                    doc_types_filter = None

                all_rows = await conn.fetch(
                    vector_sql,
                    embedding_str,
                    str(tenant_id),
                    property_filter,
                    doc_types_filter,
                    fetch_k,
                )

                # Defensive fallback: if ANN returns nothing but candidates exist,
                # score in Python so concierge never returns a false empty result.
                if not all_rows and candidate_count > 0:
                    logger.warning(
                        "VectorStore ANN returned 0 rows with %s candidates; falling back to Python scoring",
                        candidate_count,
                    )
                    all_rows = await conn.fetch(
                        fallback_sql,
                        str(tenant_id),
                        property_filter,
                        doc_types_filter,
                    )
                    logger.info(
                        "VectorStore: fallback fetched %s candidates for Python scoring",
                        len(all_rows),
                    )
                    scored = []
                    norm_q = float(np.linalg.norm(query_embedding))
                    for row in all_rows:
                        try:
                            emb = np.array(_json.loads(row["embedding"]), dtype=np.float32)
                            score = (
                                float(np.dot(query_embedding, emb))
                                / (norm_q * float(np.linalg.norm(emb)))
                                + 1
                            ) / 2
                        except Exception:
                            score = 0.0
                        if score >= min_score:
                            scored.append((score, row))
                    scored.sort(key=lambda x: x[0], reverse=True)
                    all_rows = [dict(r, similarity=s) for s, r in scored[:top_k]]
        except Exception as e:
            logger.error(f"VectorStore.similarity_search DB error: {type(e).__name__}: {e}")
            # Fallback: fetch all candidates and score in Python
            try:
                pool = await _get_vector_pool()
                async with pool.acquire() as conn2:
                    all_rows = await conn2.fetch(
                        fallback_sql,
                        str(tenant_id),
                        property_filter,
                        doc_types_filter,
                    )
                    logger.info(f"VectorStore: fallback fetched {len(all_rows)} candidates for Python scoring")
                # Score in Python
                scored = []
                norm_q = float(np.linalg.norm(query_embedding))
                for row in all_rows:
                    try:
                        emb = np.array(_json.loads(row['embedding']), dtype=np.float32)
                        score = (float(np.dot(query_embedding, emb)) / (norm_q * float(np.linalg.norm(emb))) + 1) / 2
                    except Exception:
                        score = 0.0
                    if score >= min_score:
                        scored.append((score, row))
                scored.sort(key=lambda x: x[0], reverse=True)
                all_rows = [dict(r, similarity=s) for s, r in scored[:top_k]]
            except Exception as e2:
                logger.error(f"VectorStore fallback error: {e2}")
                all_rows = []

        # Filter by min_score, sort by similarity, take top_k
        if all_rows:
            filtered = [(float(row.get('similarity', 0) or 0), row) for row in all_rows]
            filtered = [(s, r) for s, r in filtered if s >= min_score]
            filtered.sort(key=lambda x: x[0], reverse=True)
            all_rows = [r for _, r in filtered[:top_k]]
        
        documents = []
        for row in all_rows:
            meta = row['metadata'] or {}
            if isinstance(meta, str):
                meta = _json.loads(meta)
            doc = Document(
                doc_id=row['doc_id'],
                content=row['content'],
                metadata=meta,
                score=float(row['similarity']),
            )
            doc.metadata["property_code"] = row['property_code']
            doc.metadata["doc_type"] = row['doc_type']
            documents.append(doc)
        
        elapsed_ms = (time.time() - start) * 1000
        logger.debug(f"VectorStore: {len(documents)} results for '{query[:50]}' in {elapsed_ms:.0f}ms")
        
        return RetrievalResult(
            documents=documents,
            query=query,
            retrieval_time_ms=elapsed_ms,
            total_candidates=len(all_rows),
        )
    
    async def delete_by_tenant(self, tenant_id: UUID) -> int:
        """Delete all documents for a tenant."""
        result = await self.session.execute(
            text("DELETE FROM knowledge_embeddings WHERE tenant_id = CAST(:tenant_id AS uuid)"),
            {"tenant_id": str(tenant_id)}
        )
        await self.session.commit()
        return result.rowcount
    
    async def delete_by_property(self, tenant_id: UUID, property_code: str) -> int:
        """Delete all documents for a property."""
        result = await self.session.execute(
            text("""
                DELETE FROM knowledge_embeddings 
                WHERE tenant_id = CAST(:tenant_id AS uuid) AND property_code = :property_code
            """),
            {"tenant_id": str(tenant_id), "property_code": property_code}
        )
        await self.session.commit()
        return result.rowcount
    
    async def count(self, tenant_id: Optional[UUID] = None) -> Dict[str, int]:
        """Get document counts."""
        if tenant_id:
            result = await self.session.execute(
                text("""
                    SELECT doc_type, COUNT(*) as count 
                    FROM knowledge_embeddings 
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                    GROUP BY doc_type
                """),
                {"tenant_id": str(tenant_id)}
            )
        else:
            result = await self.session.execute(
                text("""
                    SELECT doc_type, COUNT(*) as count 
                    FROM knowledge_embeddings 
                    GROUP BY doc_type
                """)
            )
        
        counts = {"total": 0}
        for row in result.fetchall():
            counts[row.doc_type] = row.count
            counts["total"] += row.count
        
        return counts


# Singleton pattern
_vector_store: Optional[VectorStore] = None


async def get_vector_store(session: AsyncSession) -> VectorStore:
    """Get or create vector store instance."""
    return VectorStore(session)


async def _get_vector_pool():
    """
    Shared asyncpg pool for vector queries.

    Reuses connections and registers pgvector codec once per connection.
    """
    global _vector_pool, _vector_pool_lock
    if _vector_pool is not None:
        return _vector_pool
    if _vector_pool_lock is None:
        _vector_pool_lock = asyncio.Lock()
    async with _vector_pool_lock:
        if _vector_pool is not None:
            return _vector_pool

        import asyncpg
        from app.core.config import get_settings

        settings = get_settings()
        dsn = normalize_asyncpg_dsn(settings.database_url)

        async def _init_conn(conn):
            await conn.set_type_codec(
                "vector",
                encoder=lambda v: v,
                decoder=lambda v: v,
                schema="public",
                format="text",
            )
            # Safe before/after migration 072; ignored when no ivfflat index exists.
            await conn.execute("SET ivfflat.probes = 10")

        _vector_pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=5,
            max_size=50,
            init=_init_conn,
            command_timeout=30,
            **asyncpg_connection_kwargs(settings.database_url),
        )
        logger.info("VectorStore asyncpg pool initialized")
        return _vector_pool
