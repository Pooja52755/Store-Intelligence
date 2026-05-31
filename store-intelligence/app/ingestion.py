"""POST /events/ingest endpoint."""
import logging
import os
import uuid
from typing import Dict, List
from datetime import datetime
from sqlalchemy.dialects.postgresql import insert as pg_insert
import redis.asyncio as redis

from .models import EventSchema, IngestionResponse
from .db import db_manager, Event as DBEvent
from .graph import graph_manager

logger = logging.getLogger(__name__)

# Active session id per visitor (in-memory; persisted to Neo4j)
_active_sessions: Dict[str, str] = {}


class EventIngestionService:
    """Handle event batch ingestion with deduplication."""
    
    def __init__(self):
        """Initialize service."""
        self.redis_client = None
    
    async def init_redis(self):
        """Initialize Redis connection."""
        try:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            self.redis_client = await redis.from_url(redis_url, decode_responses=True)
            await self.redis_client.ping()
            logger.info("Connected to Redis")
        except Exception as e:
            logger.error(f"Could not connect to Redis: {e}")
            self.redis_client = None
    
    async def ingest_events(self, events: List[EventSchema]) -> IngestionResponse:
        """
        Ingest batch of events with deduplication.
        
        Features:
        - Deduplicates by event_id (INSERT ... ON CONFLICT DO NOTHING)
        - Validates each event
        - Returns partial success
        - Updates Redis live counters atomically
        - Publishes to Redis pub/sub for WebSocket
        
        Args:
            events: List of events to ingest
        
        Returns:
            IngestionResponse with accepted/rejected counts and error details
        """
        accepted = 0
        rejected = 0
        errors = []
        
        # Validate all events first
        valid_events = []
        for event in events:
            try:
                # Event already validated by Pydantic, but do extra checks here
                if not self._validate_event(event):
                    rejected += 1
                    errors.append({
                        "event_id": event.event_id,
                        "reason": "Validation failed"
                    })
                    continue
                
                valid_events.append(event)
            except Exception as e:
                rejected += 1
                errors.append({
                    "event_id": getattr(event, "event_id", "unknown"),
                    "reason": str(e)
                })
        
        # Insert into database with deduplication
        session = await db_manager.get_session()
        try:
            for event in valid_events:
                try:
                    # Parse timestamp
                    timestamp_str = event.timestamp.replace("Z", "+00:00")
                    timestamp = datetime.fromisoformat(timestamp_str)
                    
                    # Prepare insert with ON CONFLICT DO NOTHING
                    stmt = pg_insert(DBEvent).values(
                        event_id=event.event_id,
                        store_id=event.store_id,
                        camera_id=event.camera_id,
                        visitor_id=event.visitor_id,
                        event_type=event.event_type,
                        timestamp=timestamp,
                        zone_id=event.zone_id,
                        dwell_ms=event.dwell_ms,
                        is_staff=event.is_staff,
                        confidence=event.confidence,
                        queue_depth=event.metadata.queue_depth,
                        sku_zone=event.metadata.sku_zone,
                        session_seq=event.metadata.session_seq,
                        partial_occlusion=event.metadata.partial_occlusion
                    ).on_conflict_do_nothing()
                    
                    result = await session.execute(stmt)
                    
                    # Check if actually inserted (not duplicate)
                    if result.rowcount > 0:
                        accepted += 1
                        await self._update_redis_counters(event)
                        await self._update_graph(event)
                    else:
                        # Duplicate - still count as accepted (idempotency)
                        accepted += 1
                
                except Exception as e:
                    rejected += 1
                    errors.append({
                        "event_id": event.event_id,
                        "reason": f"Database error: {str(e)}"
                    })
            
            # Commit transaction
            await session.commit()
        
        except Exception as e:
            logger.error(f"Transaction error: {e}")
            await session.rollback()
        
        finally:
            await session.close()
        
        # Publish to WebSocket subscribers
        if accepted > 0:
            await self._publish_update(valid_events)
        
        return IngestionResponse(
            accepted=accepted,
            rejected=rejected,
            errors=errors[:100]  # Limit error list
        )
    
    async def _update_redis_counters(self, event: EventSchema):
        """Update Redis live counters."""
        if not self.redis_client:
            return
        
        try:
            store_key_prefix = f"store:{event.store_id}"
            
            # ENTRY/REENTRY: increment visitors:today
            if event.event_type in ["ENTRY", "REENTRY"] and not event.is_staff:
                await self.redis_client.incr(f"{store_key_prefix}:visitors:today")
            
            # BILLING_QUEUE_JOIN: set queue depth
            if event.event_type == "BILLING_QUEUE_JOIN":
                queue_depth = event.metadata.queue_depth or 0
                await self.redis_client.hset(
                    f"{store_key_prefix}:queue_depth",
                    "current",
                    queue_depth
                )
            
            # Update last event timestamp
            await self.redis_client.set(
                f"{store_key_prefix}:last_event_timestamp",
                event.timestamp
            )
        
        except Exception as e:
            logger.warning(f"Redis counter update failed: {e}")
    
    async def _update_graph(self, event: EventSchema):
        """Persist visitor journey edges in Neo4j."""
        if event.is_staff:
            return
        try:
            await graph_manager.create_or_update_visitor(
                event.visitor_id, event.store_id
            )
            vid = event.visitor_id

            if event.event_type in ("ENTRY", "REENTRY"):
                session_id = str(event.metadata.session_seq or event.event_id or uuid.uuid4())
                _active_sessions[vid] = session_id
                await graph_manager.create_or_update_session(
                    session_id, vid, event.store_id, event.timestamp
                )
                logger.info("GRAPH WRITE OK: event_id=%s -> neo4j (ENTRY/REENTRY)", event.event_id)

            session_id = _active_sessions.get(vid)
            if not session_id:
                return

            if event.event_type == "ZONE_ENTER" and event.zone_id:
                await graph_manager.record_zone_visit(
                    session_id,
                    event.zone_id,
                    event.store_id,
                    event.timestamp,
                    event.dwell_ms or 0,
                )
                logger.info("GRAPH WRITE OK: event_id=%s -> neo4j (ZONE_ENTER)", event.event_id)

            if event.event_type == "EXIT":
                st = _active_sessions.pop(vid, session_id)
                if st:
                    await graph_manager.record_transaction(
                        session_id=st,
                        txn_id=str(event.event_id),
                        store_id=event.store_id,
                        timestamp=event.timestamp,
                        basket_value=0.0,
                    )
                    logger.info("GRAPH WRITE OK: event_id=%s -> neo4j (EXIT)", event.event_id)
        except Exception as e:
            logger.warning("Graph update failed: %s", e)

    async def _publish_update(self, events: List[EventSchema]):
        """Publish ingestion updates to WebSocket subscribers."""
        if not self.redis_client:
            return

        try:
            stores = {}
            for event in events:
                if event.store_id not in stores:
                    stores[event.store_id] = 0
                if not event.is_staff:
                    stores[event.store_id] += 1

            for store_id, count in stores.items():
                channel = f"store:{store_id}:updates"
                await self.redis_client.publish(
                    channel,
                    f'{{"events_ingested": {count}, "timestamp": "{events[-1].timestamp}"}}',
                )

        except Exception as e:
            logger.warning("WebSocket publish failed: %s", e)
    
    @staticmethod
    def _validate_event(event: EventSchema) -> bool:
        """Validate event beyond Pydantic schema."""
        # Check required fields based on event type
        if event.event_type in ["ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL"]:
            if not event.zone_id:
                return False
        
        if event.event_type == "ZONE_DWELL":
            if event.dwell_ms < 1000:
                return False
        
        # Confidence must be in valid range
        if not (0.0 <= event.confidence <= 1.0):
            return False
        
        return True


# Global instance
ingestion_service = EventIngestionService()
