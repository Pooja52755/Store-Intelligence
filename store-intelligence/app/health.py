"""GET /health endpoint."""
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict
from sqlalchemy import select, func, text
import redis.asyncio as redis

from .models import HealthResponse, StoreHealth
from .db import db_manager, Event as DBEvent
from .graph import graph_manager

logger = logging.getLogger(__name__)


class HealthService:
    """System health monitoring."""
    
    async def check_health(self) -> HealthResponse:
        """
        Check system health across all components.
        
        Returns:
        - status: healthy, degraded, unhealthy
        - Per-store last event timestamp and feed status
        - Database, cache, graph connectivity
        
        Returns:
            HealthResponse with system status
        """
        stores_health: Dict[str, StoreHealth] = {}
        
        # Check database
        db_status = await self._check_database(stores_health)
        
        # Check cache
        cache_status = await self._check_cache()
        
        # Check graph
        graph_status = await self._check_graph()
        
        # Determine overall status
        if db_status == "unavailable" or cache_status == "unavailable":
            overall_status = "unhealthy"
        elif graph_status == "unavailable":
            overall_status = "degraded"
        else:
            overall_status = "healthy"
        
        return HealthResponse(
            status=overall_status,
            stores=stores_health,
            database=db_status,
            cache=cache_status,
            graph=graph_status
        )
    
    async def _check_database(self, stores_health: Dict[str, StoreHealth]) -> str:
        """Check database connectivity and get per-store status."""
        try:
            session = await db_manager.get_session()
            
            # Test query
            await session.execute(text("SELECT 1"))
            
            # Get last event timestamp per store
            store_last_events = await session.execute(
                select(
                    DBEvent.store_id,
                    func.max(DBEvent.timestamp).label("last_timestamp")
                ).group_by(DBEvent.store_id)
            )
            
            now = datetime.now(timezone.utc)
            stale_threshold_minutes = 10
            
            for store_id, last_timestamp in store_last_events:
                if last_timestamp:
                    lag_seconds = int((now - last_timestamp).total_seconds())
                    is_stale = lag_seconds > (stale_threshold_minutes * 60)
                    
                    stores_health[store_id] = StoreHealth(
                        last_event=last_timestamp.isoformat().replace("+00:00", "Z"),
                        lag_seconds=lag_seconds,
                        feed_status="STALE" if is_stale else "OK"
                    )
                else:
                    stores_health[store_id] = StoreHealth(
                        last_event=None,
                        lag_seconds=0,
                        feed_status="OK"
                    )
            
            await session.close()
            return "connected"
        
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return "unavailable"
    
    async def _check_cache(self) -> str:
        """Check Redis cache connectivity."""
        try:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            redis_client = await redis.from_url(
                redis_url,
                decode_responses=True
            )
            await redis_client.ping()
            await redis_client.close()
            return "connected"
        except Exception as e:
            logger.warning(f"Cache health check failed: {e}")
            return "unavailable"
    
    async def _check_graph(self) -> str:
        """Check Neo4j graph database connectivity."""
        enabled = os.getenv("NEO4J_ENABLED", "false").lower() == "true"
        if not enabled:
            return "disabled"
        try:
            is_connected = await graph_manager.is_connected()
            return "connected" if is_connected else "unavailable"
        except Exception as e:
            logger.warning(f"Graph health check failed: {e}")
            return "unavailable"


# Global instance
health_service = HealthService()
