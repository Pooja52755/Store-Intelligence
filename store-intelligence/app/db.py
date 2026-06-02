"""SQLAlchemy async database setup."""

import os

import logging

from sqlalchemy.ext.asyncio import (

    create_async_engine,

    AsyncSession,

    async_sessionmaker

)

from sqlalchemy import Column, String, DateTime, Float, Integer, Boolean, Text, func

from sqlalchemy.orm import declarative_base

from sqlalchemy.dialects.postgresql import UUID

import uuid

from datetime import datetime, timezone



logger = logging.getLogger(__name__)



Base = declarative_base()


class Event(Base):
    """Events table."""
    __tablename__ = "events"
    
    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(String(50), nullable=False, index=True)
    camera_id = Column(String(50), nullable=False)
    visitor_id = Column(String(50), nullable=False, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    zone_id = Column(String(100), nullable=True, index=True)
    dwell_ms = Column(Integer, default=0)
    is_staff = Column(Boolean, default=False, index=True)
    confidence = Column(Float, nullable=False)
    queue_depth = Column(Integer, nullable=True)
    sku_zone = Column(String(100), nullable=True)
    session_seq = Column(Integer, nullable=True)
    partial_occlusion = Column(Boolean, default=False)
    run_id = Column(String(50), nullable=True, index=True)
    x = Column(Float, nullable=True)
    y = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        # Composite indices
        # Index 'idx_events_store_time' on (store_id, timestamp)
        # Index 'idx_events_visitor' on (visitor_id, timestamp)
        # Index 'idx_events_type' on (event_type, store_id)
    )


class Session(Base):
    """Sessions table for funnel analysis."""
    __tablename__ = "sessions"
    
    session_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(String(50), nullable=False, index=True)
    visitor_id = Column(String(50), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    converted = Column(Boolean, default=False, index=True)
    is_reentry = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class DatabaseManager:
    """Async database connection manager."""
    
    def __init__(self):
        """Initialize database manager."""
        self.engine = None
        self.async_session_factory = None
    
    async def init(self):
        """Initialize async engine and session factory."""
        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/storedb"
        )
        
        self.engine = create_async_engine(
            database_url,
            echo=False,
            pool_size=10,
            max_overflow=20
        )
        
        self.async_session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # Create tables
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
            # Auto-migrate: check if run_id column already exists
            from sqlalchemy import text
            check_query = text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'events' AND column_name = 'run_id'
            """)
            result = await conn.execute(check_query)
            column_exists = result.scalar() is not None
            
            if not column_exists:
                logger.info("Migrating schema: Adding run_id column to events table...")
                await conn.execute(text("ALTER TABLE events ADD COLUMN run_id VARCHAR(50) NULL"))
                await conn.execute(text("CREATE INDEX idx_events_run_id ON events(run_id)"))
                logger.info("✅ Migrating schema: run_id column and index added successfully.")
            else:
                logger.info("✅ Database schema: run_id column exists.")
    
    async def get_session(self) -> AsyncSession:
        """Get async session."""
        if self.async_session_factory is None:
            await self.init()
        return self.async_session_factory()
    
    async def close(self):
        """Close connection pool."""
        if self.engine:
            await self.engine.dispose()


# Global instance
db_manager = DatabaseManager()
