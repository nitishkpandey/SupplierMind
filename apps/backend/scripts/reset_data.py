import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.db.session import engine
from app.core.config import settings
from pymilvus import connections, utility

async def reset_data():
    # 1. Clear PostgreSQL suppliers table
    print("Clearing PostgreSQL suppliers table...")
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE suppliers CASCADE;"))
    print("PostgreSQL table cleared.")

    # 2. Drop Milvus collection
    print("Dropping Milvus collection...")
    connections.connect(
        alias="default",
        host=settings.MILVUS_HOST,
        port=settings.MILVUS_PORT,
    )
    if utility.has_collection("suppliers"):
        utility.drop_collection("suppliers")
        print("Milvus collection 'suppliers' dropped.")
    else:
        print("Milvus collection 'suppliers' does not exist.")

if __name__ == "__main__":
    asyncio.run(reset_data())
