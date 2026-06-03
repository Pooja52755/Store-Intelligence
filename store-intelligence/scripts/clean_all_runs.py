#!/usr/bin/env python3
"""Script to clean up all temporary run directories, uploads, generated events, and database tables."""
import asyncio
import os
import shutil
import sys
from pathlib import Path

# Force stdout/stderr to use UTF-8 on Windows to prevent UnicodeEncodeError
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

async def clean_database():
    """Truncate the events and sessions tables in PostgreSQL."""
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/storedb"
    )
    
    print(f"Connecting to database to clean data: {database_url}")
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text
        
        engine = create_async_engine(database_url, echo=False)
        async with engine.begin() as conn:
            print("Truncating database events and sessions tables...")
            await conn.execute(text("TRUNCATE TABLE events, sessions CASCADE;"))
            print("[OK] Database tables truncated successfully!")
        await engine.dispose()
    except Exception as e:
        print(f"[WARN] Could not clean database tables (maybe DB is offline?): {e}")

def clean_filesystem():
    """Remove temporary uploads, run metadata, and generated events."""
    project_root = Path(__file__).resolve().parent.parent
    events_dir = project_root / "events"
    uploads_dir = project_root / "uploads"
    
    print(f"Project root resolved to: {project_root}")
    
    # 1. Clean events directory
    if events_dir.exists():
        print("Cleaning events directory...")
        for item in events_dir.iterdir():
            # Keep store_layout.json and pos_transactions.csv
            if item.name in ("store_layout.json", "pos_transactions.csv"):
                continue
            
            try:
                if item.is_dir():
                    print(f"Removing directory: {item.relative_to(project_root)}")
                    shutil.rmtree(item)
                else:
                    print(f"Removing file: {item.relative_to(project_root)}")
                    item.unlink()
            except Exception as e:
                print(f"Error removing {item}: {e}")
                
    # 2. Clean uploads directory
    if uploads_dir.exists():
        print("Cleaning uploads directory...")
        for item in uploads_dir.iterdir():
            try:
                if item.is_dir():
                    print(f"Removing directory: {item.relative_to(project_root)}")
                    shutil.rmtree(item)
                else:
                    print(f"Removing file: {item.relative_to(project_root)}")
                    item.unlink()
            except Exception as e:
                print(f"Error removing {item}: {e}")
                
        # Recreate empty uploads directory structure or placeholder if needed
        uploads_dir.mkdir(parents=True, exist_ok=True)

    print("[OK] Filesystem cleanup complete!")

async def main():
    print("=== STARTING FULL CLEANUP ===")
    clean_filesystem()
    await clean_database()
    print("=== FULL CLEANUP COMPLETE ===")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
