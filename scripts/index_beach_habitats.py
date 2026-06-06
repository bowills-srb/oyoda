#!/usr/bin/env python3
"""
[DEPRECATED — Phase 3]

This script is superseded by POST /api/v1/operator/properties/reconcile.

The reconcile endpoint:
- Authenticates the operator (this script bypasses auth).
- Resolves canonical tenant_id from the auth context (this script hardcodes operator strings).
- Runs the same guidebook ingest path via GuidebookIngestService (3G).
- Reconciles property additions, deactivations, and embedding deletes atomically.

Running this script after Phase 3 will succeed mechanically but:
- Writes happen without operator authentication.
- Tenant scoping relies on the script's hardcoded constants, not the JWT.
- Property table state is NOT reconciled — only embeddings are touched.

To ingest a portfolio, call the reconcile endpoint with an operator JWT instead.

Index Beach Habitats Knowledge Base

This script initializes the vector knowledge base for Beach Habitats:
1. Indexes all 30A local area data (dining, activities, beach access)
2. Indexes sample property data

Run with:
    python scripts/index_beach_habitats.py

Or from the project root:
    python -m scripts.index_beach_habitats
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.db_connect import create_configured_async_engine
from app.services.knowledge import KnowledgeIndexer


def _print_deprecation_banner() -> None:
    banner = (
        "\n"
        "===================================================================\n"
        " DEPRECATED — Phase 3\n"
        "===================================================================\n"
        " This script is superseded by:\n"
        "   POST /api/v1/operator/properties/reconcile\n"
        "\n"
        " The reconcile endpoint authenticates the operator, resolves\n"
        " canonical tenant_id, runs the same guidebook ingest, and\n"
        " reconciles property additions/deactivations atomically.\n"
        "\n"
        " To proceed with this script anyway, set:\n"
        "   OYVODA_ALLOW_LEGACY_INGEST=1\n"
        "===================================================================\n"
    )
    print(banner, file=sys.stderr)
    if os.environ.get("OYVODA_ALLOW_LEGACY_INGEST") != "1":
        print(
            "Refusing to run. Set OYVODA_ALLOW_LEGACY_INGEST=1 to override.",
            file=sys.stderr,
        )
        sys.exit(1)


# Beach Habitats operator ID
BEACH_HABITATS_OPERATOR_ID = "op_beach_habitats"

# Sample properties to index
SAMPLE_PROPERTIES = [
    {
        "code": "SEALAVIE",
        "name": "Sea La Vie",
        "community": "watercolor",
        "wifi_network": "SeaLaVie-Guest",
        "wifi_password": "beach2026",
        "door_code": "4521",
        "check_in_time": "4:00 PM",
        "check_out_time": "10:00 AM",
        "parking": "2 cars in driveway, no street parking",
        "amenities": [
            "Private pool",
            "Hot tub",
            "Gulf views",
            "4 bikes included",
            "Beach chairs (available for rent)",
            "Outdoor shower",
            "Gas grill",
        ],
        "has_pool": True,
        "pool_heated": True,
        "has_hot_tub": True,
        "has_grill": True,
        "house_rules": [
            "No smoking anywhere on property",
            "No pets allowed",
            "Quiet hours 10pm-8am",
            "Maximum 10 guests",
            "No events or parties",
        ],
        "faq": [
            {
                "question": "How do I heat the pool?",
                "answer": "Pool heat is $50/day and requires 48 hours notice. Contact us to arrange."
            },
            {
                "question": "Where do I put the trash?",
                "answer": "Trash bins are in the garage. Take to the curb by 6am on Thursday for pickup."
            },
            {
                "question": "Are beach chairs included?",
                "answer": "Beach chairs are NOT included but can be rented from La Dolce Vita (850-267-1444) or Beach Chair Guys (850-419-4862)."
            },
        ],
    },
    {
        "code": "WAVEWATCHER",
        "name": "Wave Watcher",
        "community": "seaside",
        "wifi_network": "WaveWatcher-Guest",
        "wifi_password": "sunset2026",
        "door_code": "7834",
        "check_in_time": "4:00 PM",
        "check_out_time": "10:00 AM",
        "parking": "1 car in driveway, street parking available",
        "amenities": [
            "Gulf front",
            "Private beach access",
            "2 bikes included",
            "Outdoor shower",
        ],
        "has_pool": False,
        "has_grill": True,
        "house_rules": [
            "No smoking",
            "No pets",
            "Quiet hours 10pm-8am",
        ],
    },
    {
        "code": "SANDCASTLE",
        "name": "Sandcastle Dreams",
        "community": "rosemary_beach",
        "wifi_network": "Sandcastle-WiFi",
        "wifi_password": "rosemary123",
        "door_code": "2468",
        "check_in_time": "4:00 PM",
        "check_out_time": "11:00 AM",
        "parking": "2 cars, golf cart included",
        "amenities": [
            "Community pool access",
            "Golf cart included",
            "5 bedrooms",
            "Rooftop deck",
            "Outdoor kitchen",
        ],
        "has_grill": True,
        "faq": [
            {
                "question": "How do I use the golf cart?",
                "answer": "Keys are on the kitchen counter. Golf cart is for use within Rosemary Beach only. Must be 18+ to drive."
            },
        ],
    },
]


async def main():
    """Run the indexing."""
    print("=" * 60)
    print("Beach Habitats Knowledge Base Indexer")
    print("=" * 60)
    
    # Create database connection
    settings = get_settings()
    engine = create_configured_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        indexer = KnowledgeIndexer(session)
        
        # 1. Index local area data
        print("\n📍 Indexing 30A local area data...")
        print("-" * 40)
        
        local_result = await indexer.index_local_area(
            operator_id=BEACH_HABITATS_OPERATOR_ID,
        )
        
        print(f"✓ Indexed {local_result.documents_indexed} new documents")
        print(f"✓ Updated {local_result.documents_updated} existing documents")
        print(f"\nBy type:")
        for doc_type, count in local_result.by_type.items():
            print(f"  • {doc_type}: {count}")
        
        if local_result.errors:
            print(f"\n⚠️  Errors: {local_result.errors}")
        
        # 2. Index sample properties
        print("\n🏠 Indexing sample properties...")
        print("-" * 40)
        
        prop_result = await indexer.index_all_properties(
            operator_id=BEACH_HABITATS_OPERATOR_ID,
            properties=SAMPLE_PROPERTIES,
        )
        
        print(f"✓ Indexed {prop_result.documents_indexed} new documents")
        print(f"✓ Updated {prop_result.documents_updated} existing documents")
        print(f"\nBy type:")
        for doc_type, count in prop_result.by_type.items():
            print(f"  • {doc_type}: {count}")
        
        if prop_result.errors:
            print(f"\n⚠️  Errors: {prop_result.errors}")
        
        # 3. Summary
        total_docs = (
            local_result.documents_indexed + 
            local_result.documents_updated +
            prop_result.documents_indexed + 
            prop_result.documents_updated
        )
        
        print("\n" + "=" * 60)
        print("✅ Indexing Complete!")
        print("=" * 60)
        print(f"Total documents in knowledge base: {total_docs}")
        print(f"Operator: {BEACH_HABITATS_OPERATOR_ID}")
        print(f"Properties indexed: {len(SAMPLE_PROPERTIES)}")
        print("\nYou can now test retrieval with:")
        print("  curl -X POST http://localhost:8000/api/v1/knowledge/retrieve \\")
        print('    -H "Content-Type: application/json" \\')
        print(f'    -d \'{{"query": "good seafood restaurant", "operator_id": "{BEACH_HABITATS_OPERATOR_ID}"}}\'')
    
    await engine.dispose()


if __name__ == "__main__":
    _print_deprecation_banner()
    asyncio.run(main())
