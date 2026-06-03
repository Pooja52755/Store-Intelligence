import asyncio
from app.db import db_manager, Event, Session
from sqlalchemy import select, func

async def check():
    await db_manager.init()
    session = await db_manager.get_session()
    try:
        # Check event count
        res_events = await session.execute(select(func.count(Event.event_id)))
        event_count = res_events.scalar()
        print(f"Total events in DB: {event_count}")
        
        # Check distinct run_ids
        res_runs = await session.execute(select(Event.run_id, func.count(Event.event_id)).group_by(Event.run_id))
        runs = res_runs.all()
        print("Runs and their event counts in DB:")
        for r_id, count in runs:
            print(f"  Run ID: {r_id}, Events: {count}")
            
    except Exception as e:
        print(f"Error checking DB: {e}")
    finally:
        await session.close()
        await db_manager.close()

if __name__ == "__main__":
    asyncio.run(check())
