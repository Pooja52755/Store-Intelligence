import asyncio
import os
from app.db import db_manager
from sqlalchemy import text

async def main():
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@db:5432/storedb"
    await db_manager.init()
    
    session = await db_manager.get_session()
    try:
        print("Attempting to delete events...")
        await session.execute(text("DELETE FROM events"))
        await session.execute(text("DELETE FROM sessions"))
        await session.commit()
        print("DELETE succeeded!")
    except Exception as e:
        print("DELETE failed with exception:")
        import traceback
        traceback.print_exc()
        await session.rollback()
    finally:
        await session.close()
    
    await db_manager.close()

if __name__ == "__main__":
    asyncio.run(main())
