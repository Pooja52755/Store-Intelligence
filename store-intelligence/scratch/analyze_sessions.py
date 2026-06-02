import asyncio
import os
import sys

# Include app directory in sys.path
sys.path.append(os.path.abspath('.'))

from app.db import db_manager, Event as DBEvent
from app.session_analytics import build_sessions_from_events, compute_funnel_counts
from sqlalchemy import select

async def main():
    session = await db_manager.get_session()
    
    run_id = "5dfb6818-c85e-4541-9be9-f8815ab80b00"
    
    # Query database
    result = await session.execute(
        select(DBEvent).where(DBEvent.run_id == run_id)
    )
    db_events = result.scalars().all()
    print(f"Total DB events for run {run_id}: {len(db_events)}")
    
    # Convert to list of dicts as done in fetch_store_events
    events = []
    for ev in db_events:
        events.append({
            "event_id": str(ev.event_id),
            "store_id": ev.store_id,
            "camera_id": ev.camera_id,
            "visitor_id": ev.visitor_id,
            "event_type": ev.event_type,
            "timestamp": ev.timestamp.isoformat(),
            "zone_id": ev.zone_id,
            "dwell_ms": ev.dwell_ms,
            "is_staff": ev.is_staff,
            "confidence": ev.confidence,
        })
        
    print(f"Total events converted: {len(events)}")
    
    sessions = build_sessions_from_events(events)
    print(f"Total customer sessions built (excl. staff): {len(sessions)}")
    
    for idx, s in enumerate(sessions):
        print(f"Session {idx+1}: Visitor: {s.visitor_id} | Entry: {s.started_at} | Exit: {s.ended_at} | Zones Visited: {s.zones_visited} | Has Entry: {s.has_entry}")
        
    entry, zone, billing, purchase = compute_funnel_counts(sessions)
    print(f"Funnel: Entry={entry}, Zone={zone}, Billing={billing}, Purchase={purchase}")
    
    await db_manager.close()

if __name__ == '__main__':
    asyncio.run(main())
