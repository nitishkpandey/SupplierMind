"""
backend/scripts/verify_databases.py — Verify connection and contents of Redis and Milvus.

Run this script from the backend directory:
    uv run python scripts/verify_databases.py
"""

import sys
from pathlib import Path

# Add backend/ to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings


def verify_redis():
    print("=" * 60)
    print("1. VERIFYING REDIS STORAGE")
    print("=" * 60)
    print(f"Connecting to Redis at: {settings.REDIS_URL}")
    
    try:
        import redis
        # Connect to Redis
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        
        # Ping
        if r.ping():
            print("[OK] Connection successful!")
        
        # Get DB size
        db_size = r.dbsize()
        print(f"Total keys stored in DB: {db_size}")
        
        # Get key patterns
        keys = r.keys("*")
        if keys:
            print("\nStored Key Patterns:")
            # Group keys by prefix to make it easier to read
            prefixes = {}
            for key in keys:
                parts = key.split(":")
                prefix = f"{parts[0]}:*" if len(parts) > 1 else key
                prefixes[prefix] = prefixes.get(prefix, 0) + 1
                
            for prefix, count in prefixes.items():
                print(f"  - {prefix} ({count} keys)")
                
            print("\nSample Keys (up to 5):")
            for key in keys[:5]:
                try:
                    ttl = r.ttl(key)
                    ttl_str = f"{ttl}s" if ttl > 0 else "No TTL"
                    val_type = r.type(key)
                    print(f"  - Key: '{key}' | Type: {val_type} | TTL: {ttl_str}")
                except Exception as inner_err:
                    print(f"  - Key: '{key}' | Error reading metadata: {inner_err}")
        else:
            print("No keys found (Redis is empty).")
            
    except Exception as e:
        print(f"[ERROR] Redis verification failed:")
        print(f"  Error message: {e}")
        print("  Tip: Ensure your Redis service is running (e.g., run `docker compose -f infra/docker/docker-compose.yml up -d redis`).")
    print()


def verify_milvus():
    print("=" * 60)
    print("2. VERIFYING MILVUS STORAGE")
    print("=" * 60)
    
    if settings.effective_vector_db != "milvus":
        print(f"App is configured to use: {settings.effective_vector_db.upper()}")
        print("Skipping Milvus checks (LITE_MODE or Fallback active).")
        verify_chroma()
        return
        
    print(f"Connecting to Milvus Standalone at: {settings.MILVUS_HOST}:{settings.MILVUS_PORT}")
    
    try:
        from pymilvus import connections, utility, Collection
        
        # Connect to Milvus
        connections.connect(
            alias="default",
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
        )
        print("[OK] Connection successful!")
        
        # Check collections
        collections = utility.list_collections()
        print(f"Active collections in Milvus: {collections}")
        
        if "suppliers" in collections:
            col = Collection("suppliers")
            col.load()  # Make sure it's loaded in memory
            
            print("\nCollection 'suppliers' Details:")
            print(f"  - Number of Entities: {col.num_entities}")
            print(f"  - Schema Description: {col.schema.description}")
            print(f"  - Primary Key Field : {col.schema.primary_field.name}")
            
            # Print field structure
            print("  - Fields:")
            for field in col.schema.fields:
                print(f"    * {field.name}: {field.dtype} (dim={field.params.get('dim', 'N/A') if field.params else 'N/A'})")
                
            # Print index details
            indexes = col.indexes
            if indexes:
                print("  - Indexes:")
                for index in indexes:
                    print(f"    * Field: '{index.field_name}' | Info: {index.params}")
            else:
                print("  - Indexes: None built yet")
        else:
            print("[WARN] Collection 'suppliers' does not exist in Milvus.")
            print("  Run 'uv run python scripts/ingest_suppliers.py' to ingest and index data.")
            
    except Exception as e:
        print(f"[ERROR] Milvus verification failed:")
        print(f"  Error message: {e}")
        print("  Tip: Ensure your Milvus service is running (e.g., run `docker compose -f infra/docker/docker-compose.yml up -d milvus`).")
    print()


def verify_chroma():
    print("=" * 60)
    print("3. VERIFYING CHROMADB FALLBACK STORAGE")
    print("=" * 60)
    print(f"Connecting to ChromaDB path: {settings.CHROMA_PERSIST_PATH}")
    
    try:
        import chromadb
        client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_PATH)
        collections = client.list_collections()
        col_names = [c.name for c in collections]
        print(f"Active collections in ChromaDB: {col_names}")
        
        if "suppliers" in col_names:
            col = client.get_collection("suppliers")
            print(f"\nCollection 'suppliers' Details:")
            print(f"  - Number of Entities: {col.count()}")
            print(f"  - Metadata: {col.metadata}")
        else:
            print("[WARN] Collection 'suppliers' does not exist in ChromaDB.")
            
    except Exception as e:
        print(f"[ERROR] ChromaDB verification failed: {e}")
    print()


if __name__ == "__main__":
    verify_redis()
    verify_milvus()
