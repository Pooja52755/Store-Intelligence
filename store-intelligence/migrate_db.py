#!/usr/bin/env python3
"""
Database migration script for adding run_id column and index.
Run this after deploying the updated code.
"""

import asyncio
import os
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def migrate():
    """Apply database migrations."""
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/storedb"
    )
    
    logger.info(f"Connecting to database: {database_url}")
    
    engine = create_async_engine(database_url, echo=False)
    
    async with engine.begin() as conn:
        # Check if run_id column already exists
        check_query = text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'events' AND column_name = 'run_id'
        """)
        result = await conn.execute(check_query)
        column_exists = result.scalar() is not None
        
        if column_exists:
            logger.info("✅ Column 'run_id' already exists")
        else:
            logger.info("Adding column 'run_id' to events table...")
            await conn.execute(text(
                "ALTER TABLE events ADD COLUMN run_id VARCHAR(50) NULL"
            ))
            logger.info("✅ Column 'run_id' added")
        
        # Check if index exists
        check_index = text("""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = 'events' AND indexname = 'idx_events_run_id'
        """)
        result = await conn.execute(check_index)
        index_exists = result.scalar() is not None
        
        if index_exists:
            logger.info("✅ Index 'idx_events_run_id' already exists")
        else:
            logger.info("Creating index on run_id...")
            await conn.execute(text(
                "CREATE INDEX idx_events_run_id ON events(run_id)"
            ))
            logger.info("✅ Index created")
        
        # Get table structure
        logger.info("\nCurrent events table schema:")
        schema_query = text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'events'
            ORDER BY ordinal_position
        """)
        result = await conn.execute(schema_query)
        rows = result.fetchall()
        for row in rows:
            logger.info(f"  {row[0]:25} {row[1]:20} nullable={row[2]}")
    
    await engine.dispose()
    logger.info("\n✅ Migration complete!")

if __name__ == "__main__":
    asyncio.run(migrate())
