import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def alter_database():
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/storedb"
    )
    print(f"Connecting to database to add columns: {database_url}")
    engine = create_async_engine(database_url, echo=False)
    
    async with engine.begin() as conn:
        try:
            print("Adding 'x' and 'y' columns to events table if they don't exist...")
            await conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS x DOUBLE PRECISION;"))
            await conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS y DOUBLE PRECISION;"))
            print("✅ Columns added successfully!")
        except Exception as e:
            print(f"❌ Error adding columns: {e}")
            
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(alter_database())
