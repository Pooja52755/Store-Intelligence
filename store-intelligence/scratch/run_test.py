import asyncio
import os
from app.db import db_manager
from app.ingestion import ingestion_service
from app.models import EventSchema, EventMetadata
import uuid

async def main():
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@db:5432/storedb"
    await db_manager.init()
    
    # 1. Clean DB
    session = await db_manager.get_session()
    try:
        from sqlalchemy import text
        await session.execute(text("DELETE FROM events"))
        await session.execute(text("DELETE FROM sessions"))
        await session.commit()
    except Exception as e:
        await session.rollback()
    finally:
        await session.close()
        
    # 2. Ingest first batch (happy path)
    events1 = [
        EventSchema(
            event_id=str(uuid.uuid4()),
            store_id="STORE_BLR_002",
            camera_id="CAM_ENTRY_01",
            visitor_id="VIS_001",
            event_type="ENTRY",
            timestamp="2026-03-03T14:22:10Z",
            zone_id=None,
            dwell_ms=0,
            is_staff=False,
            confidence=0.91,
            metadata=EventMetadata()
        )
    ]
    res1 = await ingestion_service.ingest_events(events1)
    print("Ingest 1 accepted:", res1.accepted)
    print("Ingest 1 errors:", res1.errors)
    
    # 3. Ingest second batch (should trigger idempotency or work)
    res2 = await ingestion_service.ingest_events(events1)
    print("Ingest 2 accepted:", res2.accepted)
    print("Ingest 2 errors:", res2.errors)

if __name__ == "__main__":
    asyncio.run(main())
