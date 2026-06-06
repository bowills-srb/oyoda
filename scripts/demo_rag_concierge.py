#!/usr/bin/env python3
"""
Demo: RAG-based Concierge

Demonstrates the new Orchestrated RAG architecture:
1. Initialize vector store
2. Index local area data
3. Test retrieval queries
4. Compare response times/costs

Run:
    python scripts/demo_rag_concierge.py
"""

import asyncio
import time
import os
import sys

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OPERATOR_ID = "op_beach_habitats"


def print_header(text: str):
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)


def print_step(num: int, text: str):
    print(f"\n[{num}] {text}")
    print("-" * 40)


async def main():
    print_header("Beach Habitats RAG Concierge Demo")
    
    # Step 1: Initialize vector store
    print_step(1, "Initializing Vector Store")
    
    try:
        from app.services.knowledge.vector_store import VectorStore
        store = VectorStore()
        print("✓ pgvector extension enabled")
        print("✓ knowledge_embeddings table ready")
    except Exception as e:
        print(f"✗ Error: {e}")
        print("\nMake sure PostgreSQL is running and pgvector is installed:")
        print("  CREATE EXTENSION IF NOT EXISTS vector;")
        return
    
    # Step 2: Index local area data
    print_step(2, "Indexing Local Area Data")
    
    try:
        from app.services.knowledge.indexer import KnowledgeIndexer
        indexer = KnowledgeIndexer()
        
        result = indexer.index_local_area_data(OPERATOR_ID)
        print(f"✓ Indexed {result.documents_indexed} local area documents")
        
        if result.errors:
            for err in result.errors:
                print(f"  ⚠ {err}")
    except Exception as e:
        print(f"✗ Error indexing: {e}")
    
    # Step 3: Show stats
    print_step(3, "Vector Store Statistics")
    
    stats = store.get_stats(OPERATOR_ID)
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Step 4: Test retrieval queries
    print_step(4, "Testing Retrieval Queries")
    
    from app.services.knowledge.librarian_agent import LibrarianAgent
    librarian = LibrarianAgent()
    
    test_queries = [
        "Where should we eat dinner tonight?",
        "What's a good seafood restaurant?",
        "Where can I rent beach chairs?",
        "What's the wifi password?",
        "Is there an urgent care nearby?",
        "What activities can we do with kids?",
    ]
    
    for query in test_queries:
        print(f"\n  Query: \"{query}\"")
        
        # Classify intent
        intent = librarian.classify_intent(query)
        print(f"  Intent: {intent.value}")
        
        # Check if retrieval needed
        needs_retrieval = librarian.needs_retrieval(query)
        print(f"  Needs retrieval: {needs_retrieval}")
        
        if needs_retrieval:
            start = time.time()
            result = librarian.retrieve(
                query=query,
                operator_id=OPERATOR_ID,
                top_k=3,
            )
            elapsed = (time.time() - start) * 1000
            
            print(f"  Retrieved: {len(result.documents)} docs in {elapsed:.1f}ms")
            
            if result.documents:
                # Show first result
                doc = result.documents[0]
                preview = doc[:80] + "..." if len(doc) > 80 else doc
                print(f"  Top result: {preview}")
    
    # Step 5: Test full AI response
    print_step(5, "Testing Full AI Response (with Gemini)")
    
    # Check for API key
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    
    if not api_key:
        print("  ⚠ No GOOGLE_API_KEY found, skipping AI test")
        print("  Set GOOGLE_API_KEY to test full AI responses")
    else:
        from app.services.concierge.ai_concierge import get_ai_response
        
        test_message = "What are some good dinner spots with sunset views?"
        
        print(f"\n  Message: \"{test_message}\"")
        
        start = time.time()
        response = await get_ai_response(
            message=test_message,
            property_context={
                "wifi_network": "SeaLaVie-Guest",
                "wifi_password": "beach2024",
                "check_in_time": "4:00 PM",
                "check_out_time": "10:00 AM",
            },
            guest_name="Hunter",
            property_name="Sea La Vie",
            operator_id=OPERATOR_ID,
        )
        elapsed = (time.time() - start) * 1000
        
        print(f"\n  Response ({elapsed:.0f}ms):")
        print(f"  {response}")
    
    # Step 6: Cost comparison
    print_step(6, "Cost Comparison")
    
    print("""
  Traditional "God-like" Agent:
    - Context: 1000s of properties + all restaurants + all activities
    - Tokens per request: ~8,000-15,000
    - Cost per request: ~$0.30-0.50
    - At scale (100 ops × 100 calls/day): ~$150,000/month

  RAG-based Approach:
    - Context: Only 3-5 relevant docs per query
    - Tokens per request: ~500-1,000
    - Cost per request: ~$0.02-0.03
    - At scale (100 ops × 100 calls/day): ~$10,000/month

  Savings: ~93%
    """)
    
    print_header("Demo Complete!")
    print("""
Next steps:
  1. Index properties: python scripts/knowledge_cli.py index --operator op_beach_habitats
  2. Test searches: python scripts/knowledge_cli.py search --operator op_beach_habitats --query "seafood restaurant"
  3. Run the API: uvicorn app.main:app --reload
  4. Test mobile interface: GET /c/{token}
    """)


if __name__ == "__main__":
    asyncio.run(main())
