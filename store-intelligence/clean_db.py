#!/usr/bin/env python3
import asyncio
import os
import sys
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def clean_database():
    """Truncate the events and sessions tables and clear filesystem run folders."""
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/storedb"
    )
    
    print(f"Connecting to database to clean data: {database_url}")
    engine = create_async_engine(database_url, echo=False)
    
    async with engine.begin() as conn:
        try:
            print("Truncating events and sessions tables...")
            await conn.execute(text("TRUNCATE TABLE events, sessions CASCADE;"))
            print("✅ Database tables truncated successfully!")
        except Exception as e:
            print(f"❌ Error truncating tables: {e}", file=sys.stderr)
            
    await engine.dispose()

    # Clear run folders on the filesystem
    import shutil
    from pathlib import Path
    events_dir = Path("./events")
    if events_dir.exists():
        print("Cleaning up filesystem run folders under ./events...")
        for child in events_dir.iterdir():
            if child.is_dir() and child.name.startswith("STORE_"):
                print(f"Purging store run directory: {child}")
                for run_dir in child.iterdir():
                    if run_dir.is_dir():
                        print(f"Removing run metadata folder: {run_dir}")
                        shutil.rmtree(run_dir)
        print("✅ Filesystem run folders purged successfully!")

if __name__ == "__main__":
    asyncio.run(clean_database())
