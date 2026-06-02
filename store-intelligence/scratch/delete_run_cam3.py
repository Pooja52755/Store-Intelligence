import asyncio
import os
import sys

# Include app directory in sys.path
sys.path.append(os.path.abspath('.'))

from app.db import db_manager, Event as DBEvent
from sqlalchemy import delete

async def main():
    session = await db_manager.get_session()
    
    run_id = "f3cfba03-5948-41d4-a818-64936262775a"
    
    print(f"Deleting events for run {run_id} from DB...")
    
    async with session.begin():
        stmt = delete(DBEvent).where(DBEvent.run_id == run_id)
        result = await session.execute(stmt)
        print(f"✅ Deleted {result.rowcount} events.")
    
    await db_manager.close()

if __name__ == '__main__':
    asyncio.run(main())
