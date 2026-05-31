"""Pytest configuration and shared fixtures."""
import pytest
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import db_manager, Base


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def test_db():
    """Setup and teardown test database."""
    # Initialize database
    await db_manager.init()
    
    # Create tables
    async with db_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield db_manager
    
    # Cleanup - drop all tables
    async with db_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    # Close connection
    await db_manager.close()


@pytest.fixture
async def db_session(test_db: any) -> AsyncSession:
    """Get database session for tests."""
    session = await test_db.get_session()
    yield session
    await session.close()
