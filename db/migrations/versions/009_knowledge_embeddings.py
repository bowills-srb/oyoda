"""
Migration: Knowledge Embeddings Table with pgvector

Creates the vector store table for semantic search.
Uses pgvector extension for efficient similarity search.

Run with:
    alembic upgrade head

Or manually:
    python db/migrations/versions/009_knowledge_embeddings.py
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# Revision identifiers
revision = '009_knowledge_embeddings'
down_revision = '008_concierge_sessions'
branch_labels = None
depends_on = None

EMBEDDING_DIM = 384  # Matches all-MiniLM-L6-v2


def upgrade():
    """Create knowledge_embeddings table with pgvector."""
    
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    
    # Create table
    op.create_table(
        'knowledge_embeddings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, 
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('doc_id', sa.String(64), unique=True, nullable=False),
        sa.Column('operator_id', sa.String(100), nullable=False, index=True),
        sa.Column('property_code', sa.String(100), nullable=True),
        sa.Column('doc_type', sa.String(100), nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('metadata', postgresql.JSONB, server_default='{}'),
        # Vector column - using raw SQL since SQLAlchemy doesn't have native vector type
        sa.Column('embedding', sa.LargeBinary, nullable=True),  # Placeholder, will alter
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    # Alter embedding column to vector type
    op.execute(f"""
        ALTER TABLE knowledge_embeddings 
        ALTER COLUMN embedding TYPE vector({EMBEDDING_DIM})
        USING NULL;
    """)
    
    # Create indexes
    op.create_index(
        'idx_knowledge_operator_property',
        'knowledge_embeddings',
        ['operator_id', 'property_code']
    )
    
    op.create_index(
        'idx_knowledge_operator_type',
        'knowledge_embeddings',
        ['operator_id', 'doc_type']
    )
    
    # Create vector index for similarity search (IVFFlat)
    # Note: IVFFlat requires the table to have data to build the index
    # We'll create it without lists parameter initially
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_knowledge_embedding_cosine
        ON knowledge_embeddings 
        USING ivfflat (embedding vector_cosine_ops);
    """)


def downgrade():
    """Drop knowledge_embeddings table."""
    op.drop_table('knowledge_embeddings')
    # Note: We don't drop the pgvector extension as other tables might use it


# Allow running as standalone script
if __name__ == "__main__":
    import os
    import psycopg2
    
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql://rental:rental@localhost:5433/rental_revenue"
    )
    
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    
    print("Running migration: 009_knowledge_embeddings")
    
    try:
        # Enable extension
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        print("✓ pgvector extension enabled")
        
        # Create table
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS knowledge_embeddings (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                doc_id VARCHAR(64) UNIQUE NOT NULL,
                operator_id VARCHAR(100) NOT NULL,
                property_code VARCHAR(100),
                doc_type VARCHAR(100) NOT NULL,
                content TEXT NOT NULL,
                metadata JSONB DEFAULT '{{}}',
                embedding vector({EMBEDDING_DIM}),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        print("✓ knowledge_embeddings table created")
        
        # Create indexes
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_operator 
            ON knowledge_embeddings(operator_id);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_operator_property 
            ON knowledge_embeddings(operator_id, property_code);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_operator_type 
            ON knowledge_embeddings(operator_id, doc_type);
        """)
        print("✓ Indexes created")
        
        # Vector index
        cur.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_knowledge_embedding_cosine
            ON knowledge_embeddings 
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
        """)
        print("✓ Vector index created")
        
        print("\n✓ Migration complete!")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        raise
    finally:
        cur.close()
        conn.close()
