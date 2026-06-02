"""Pytest configuration and shared fixtures."""
import pytest
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import db_manager, Base




@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def test_db():
    """Setup and teardown test database using DELETE to avoid locking conflicts."""
    # Initialize database
    await db_manager.init()
    
    # Ensure tables exist
    async with db_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    # Clean tables before test
    session = await db_manager.get_session()
    try:
        from sqlalchemy import text
        count_before = await session.execute(text("SELECT count(*) FROM events"))
        print(">>> BEFORE TEST CLEAN: EVENTS IN DB =", count_before.scalar())
        await session.execute(text("DELETE FROM events"))
        await session.execute(text("DELETE FROM sessions"))
        await session.commit()
        count_after = await session.execute(text("SELECT count(*) FROM events"))
        print(">>> AFTER TEST CLEAN: EVENTS IN DB =", count_after.scalar())
    except Exception as e:
        import traceback
        traceback.print_exc()
        await session.rollback()
        raise e
    finally:
        await session.close()


    
    yield db_manager
    
    # Clean tables after test
    session = await db_manager.get_session()
    try:
        from sqlalchemy import text
        count_before = await session.execute(text("SELECT count(*) FROM events"))
        print(">>> BEFORE TEST TEARDOWN CLEAN: EVENTS IN DB =", count_before.scalar())
        await session.execute(text("DELETE FROM events"))
        await session.execute(text("DELETE FROM sessions"))
        await session.commit()
        count_after = await session.execute(text("SELECT count(*) FROM events"))
        print(">>> AFTER TEST TEARDOWN CLEAN: EVENTS IN DB =", count_after.scalar())
    except Exception as e:
        import traceback
        traceback.print_exc()
        await session.rollback()
        raise e
    finally:
        await session.close()






@pytest.fixture
async def db_session(test_db: any) -> AsyncSession:
    """Get database session for tests."""
    session = await test_db.get_session()
    yield session
    await session.close()
