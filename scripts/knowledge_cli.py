#!/usr/bin/env python3
"""
Knowledge Base CLI

Commands to manage the vector knowledge base.

Usage:
    # Initialize pgvector and create tables
    python -m scripts.knowledge_cli init
    
    # Index all data for Beach Habitats
    python -m scripts.knowledge_cli index --operator op_beach_habitats
    
    # Test a search query
    python -m scripts.knowledge_cli search --operator op_beach_habitats --query "Where should we eat dinner?"
    
    # Get stats
    python -m scripts.knowledge_cli stats
"""

import argparse
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def cmd_init(args):
    """Initialize the vector store (creates tables)."""
    print("Initializing vector store...")
    
    from app.services.knowledge.vector_store import VectorStore
    
    try:
        store = VectorStore()
        print("✓ pgvector extension enabled")
        print("✓ knowledge_embeddings table created")
        print("✓ Indexes created")
        print("\nVector store ready!")
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


def cmd_index(args):
    """Index knowledge for an operator."""
    operator_id = args.operator
    
    print(f"Indexing knowledge for operator: {operator_id}")
    print("-" * 50)
    
    from app.services.knowledge.indexer import KnowledgeIndexer
    
    indexer = KnowledgeIndexer()
    
    # Index local area data
    print("\n1. Indexing local area data...")
    result = indexer.index_local_area_data(operator_id)
    print(f"   ✓ {result.documents_indexed} documents indexed")
    if result.errors:
        for err in result.errors:
            print(f"   ✗ Error: {err}")
    
    # Index properties
    print("\n2. Indexing properties...")
    result = indexer.index_all_properties(operator_id)
    print(f"   ✓ {result.documents_indexed} documents indexed")
    if result.errors:
        for err in result.errors[:5]:  # Show first 5 errors
            print(f"   ✗ Error: {err}")
    
    print("\n" + "=" * 50)
    print("Indexing complete!")
    
    # Show stats
    from app.services.knowledge.vector_store import get_vector_store
    store = get_vector_store()
    stats = store.get_stats(operator_id)
    print(f"\nTotal documents for {operator_id}: {stats.get('total_docs', 0)}")


def cmd_search(args):
    """Test a search query."""
    operator_id = args.operator
    query = args.query
    property_code = args.property
    
    print(f"Searching for: \"{query}\"")
    print(f"Operator: {operator_id}")
    if property_code:
        print(f"Property: {property_code}")
    print("-" * 50)
    
    from app.services.knowledge.librarian_agent import LibrarianAgent
    
    librarian = LibrarianAgent()
    
    # Classify intent
    intent = librarian.classify_intent(query)
    print(f"\nDetected intent: {intent.value}")
    
    # Retrieve
    result = librarian.retrieve(
        query=query,
        operator_id=operator_id,
        property_code=property_code,
        top_k=5,
    )
    
    print(f"Retrieval time: {result.retrieval_time_ms:.1f}ms")
    print(f"Documents found: {len(result.documents)}")
    print("\n" + "=" * 50)
    
    for i, (doc, source) in enumerate(zip(result.documents, result.sources), 1):
        print(f"\n[{i}] Score: {source['score']} | Type: {source['type']}")
        print(f"    {doc[:200]}..." if len(doc) > 200 else f"    {doc}")
    
    print("\n" + "=" * 50)
    print("\nContext for LLM:")
    print(result.context_for_llm)


def cmd_stats(args):
    """Show vector store statistics."""
    from app.services.knowledge.vector_store import get_vector_store
    
    store = get_vector_store()
    
    if args.operator:
        stats = store.get_stats(args.operator)
        print(f"Stats for operator: {args.operator}")
    else:
        stats = store.get_stats()
        print("Global stats:")
    
    print("-" * 30)
    for key, value in stats.items():
        print(f"  {key}: {value}")


def cmd_clear(args):
    """Clear knowledge for an operator."""
    operator_id = args.operator
    
    if not args.confirm:
        print(f"This will delete ALL documents for operator: {operator_id}")
        confirm = input("Type 'yes' to confirm: ")
        if confirm.lower() != 'yes':
            print("Cancelled.")
            return
    
    from app.services.knowledge.vector_store import get_vector_store
    
    store = get_vector_store()
    deleted = store.delete_by_operator(operator_id)
    print(f"Deleted {deleted} documents for {operator_id}")


def main():
    parser = argparse.ArgumentParser(description="Knowledge Base CLI")
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # init
    init_parser = subparsers.add_parser("init", help="Initialize vector store")
    init_parser.set_defaults(func=cmd_init)
    
    # index
    index_parser = subparsers.add_parser("index", help="Index knowledge for an operator")
    index_parser.add_argument("--operator", "-o", required=True, help="Operator ID")
    index_parser.set_defaults(func=cmd_index)
    
    # search
    search_parser = subparsers.add_parser("search", help="Test a search query")
    search_parser.add_argument("--operator", "-o", required=True, help="Operator ID")
    search_parser.add_argument("--query", "-q", required=True, help="Search query")
    search_parser.add_argument("--property", "-p", help="Property code (optional)")
    search_parser.set_defaults(func=cmd_search)
    
    # stats
    stats_parser = subparsers.add_parser("stats", help="Show statistics")
    stats_parser.add_argument("--operator", "-o", help="Operator ID (optional)")
    stats_parser.set_defaults(func=cmd_stats)
    
    # clear
    clear_parser = subparsers.add_parser("clear", help="Clear knowledge for an operator")
    clear_parser.add_argument("--operator", "-o", required=True, help="Operator ID")
    clear_parser.add_argument("--confirm", "-y", action="store_true", help="Skip confirmation")
    clear_parser.set_defaults(func=cmd_clear)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    
    args.func(args)


if __name__ == "__main__":
    main()
