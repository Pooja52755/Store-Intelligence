"""Neo4j graph database integration."""
import os
from typing import List, Dict, Any, Optional
from neo4j import AsyncGraphDatabase, AsyncDriver
import logging

logger = logging.getLogger(__name__)


class GraphManager:
    """Neo4j graph database manager."""
    
    def __init__(self):
        """Initialize graph manager."""
        self.driver: Optional[AsyncDriver] = None
    
    async def init(self):
        """Initialize Neo4j driver."""
        enabled = os.getenv("NEO4J_ENABLED", "false").lower() == "true"
        if not enabled:
            logger.info("Neo4j integration is disabled (NEO4J_ENABLED=false). Skipping driver initialization.")
            self.driver = None
            return
            
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "password")
        
        try:
            self.driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
            # Verify connection
            async with self.driver.session() as session:
                await session.run("RETURN 1")
            logger.info(f"Connected to Neo4j at {uri}")
        except Exception as e:
            logger.error(f"Could not connect to Neo4j: {e}")
            self.driver = None
    
    async def close(self):
        """Close driver."""
        if self.driver:
            await self.driver.close()
    
    async def is_connected(self) -> bool:
        """Check if connected to Neo4j."""
        if not self.driver:
            return False
        try:
            async with self.driver.session() as session:
                await session.run("RETURN 1")
            return True
        except Exception:
            return False
    
    async def create_or_update_visitor(
        self,
        visitor_id: str,
        store_id: str,
        embedding_hash: Optional[str] = None
    ):
        """Create or update visitor node."""
        if not self.driver:
            return
        
        try:
            async with self.driver.session() as session:
                await session.run(
                    """
                    MERGE (v:Visitor {visitor_id: $visitor_id})
                    SET v.store_id = $store_id,
                        v.first_seen = coalesce(v.first_seen, datetime()),
                        v.embedding_hash = $embedding_hash
                    """,
                    visitor_id=visitor_id,
                    store_id=store_id,
                    embedding_hash=embedding_hash
                )
        except Exception as e:
            logger.error(f"Error creating visitor node: {e}")
    
    async def create_or_update_session(
        self,
        session_id: str,
        visitor_id: str,
        store_id: str,
        started_at: str
    ):
        """Create or update session node and relationship to visitor."""
        if not self.driver:
            return
        
        try:
            async with self.driver.session() as session:
                await session.run(
                    """
                    MATCH (v:Visitor {visitor_id: $visitor_id})
                    CREATE (s:Session {
                        session_id: $session_id,
                        store_id: $store_id,
                        started_at: $started_at,
                        converted: false
                    })
                    CREATE (v)-[:HAD_SESSION]->(s)
                    """,
                    session_id=session_id,
                    visitor_id=visitor_id,
                    store_id=store_id,
                    started_at=started_at
                )
        except Exception as e:
            logger.error(f"Error creating session node: {e}")
    
    async def record_zone_visit(
        self,
        session_id: str,
        zone_id: str,
        store_id: str,
        entered_at: str,
        dwell_ms: int
    ):
        """Record zone visit in graph."""
        if not self.driver:
            return
        
        try:
            async with self.driver.session() as session:
                await session.run(
                    """
                    MATCH (s:Session {session_id: $session_id})
                    MERGE (z:Zone {zone_id: $zone_id, store_id: $store_id})
                    CREATE (s)-[:VISITED {entered_at: $entered_at, dwell_ms: $dwell_ms}]->(z)
                    """,
                    session_id=session_id,
                    zone_id=zone_id,
                    store_id=store_id,
                    entered_at=entered_at,
                    dwell_ms=dwell_ms
                )
        except Exception as e:
            logger.error(f"Error recording zone visit: {e}")
    
    async def record_transaction(
        self,
        session_id: str,
        txn_id: str,
        store_id: str,
        timestamp: str,
        basket_value: float
    ):
        """Record transaction purchase."""
        if not self.driver:
            return
        
        try:
            async with self.driver.session() as session:
                await session.run(
                    """
                    MATCH (s:Session {session_id: $session_id})
                    CREATE (t:Transaction {
                        txn_id: $txn_id,
                        store_id: $store_id,
                        timestamp: $timestamp,
                        basket_value: $basket_value
                    })
                    CREATE (s)-[:RESULTED_IN]->(t)
                    SET s.converted = true
                    """,
                    session_id=session_id,
                    txn_id=txn_id,
                    store_id=store_id,
                    timestamp=timestamp,
                    basket_value=basket_value
                )
        except Exception as e:
            logger.error(f"Error recording transaction: {e}")
    
    async def get_visitor_journey_paths(
        self,
        store_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get most common visitor journey paths."""
        if not self.driver:
            return []
        
        try:
            async with self.driver.session() as session:
                result = await session.run(
                    """
                    MATCH (s:Session {store_id: $store_id})-[:VISITED]->(z:Zone)
                    WITH s, collect(z.zone_id) AS path
                    RETURN path, count(*) AS frequency
                    ORDER BY frequency DESC
                    LIMIT $limit
                    """,
                    store_id=store_id,
                    limit=limit
                )
                
                records = await result.fetch(limit)
                return [
                    {"path": record["path"], "frequency": record["frequency"]}
                    for record in records
                ]
        except Exception as e:
            logger.error(f"Error getting journey paths: {e}")
            return []
    
    async def check_camera_overlap(
        self,
        camera_id_1: str,
        camera_id_2: str,
        store_id: str
    ) -> bool:
        """Check if two cameras have overlapping field of view."""
        if not self.driver:
            return False
        
        try:
            async with self.driver.session() as session:
                result = await session.run(
                    """
                    MATCH (c1:Camera {camera_id: $cam1, store_id: $store_id})-
                          [:OVERLAPS_WITH]->(c2:Camera {camera_id: $cam2})
                    RETURN true AS overlaps
                    """,
                    cam1=camera_id_1,
                    cam2=camera_id_2,
                    store_id=store_id
                )
                
                record = await result.single()
                return record is not None and record["overlaps"]
        except Exception as e:
            logger.error(f"Error checking camera overlap: {e}")
            return False
    
    async def get_dead_zones(
        self,
        store_id: str,
        time_window_minutes: int = 30
    ) -> List[str]:
        """Get zones with no visits in last N minutes."""
        if not self.driver:
            return []
        
        try:
            async with self.driver.session() as session:
                result = await session.run(
                    """
                    MATCH (z:Zone {store_id: $store_id})
                    OPTIONAL MATCH (s:Session {store_id: $store_id})-[:VISITED]->
                                   (z:Zone {zone_id: z.zone_id})
                    WHERE s.started_at > datetime() - duration({minutes: $window})
                    WITH z, count(s) AS recent_visits
                    WHERE recent_visits = 0
                    RETURN z.zone_id AS zone_id
                    """,
                    store_id=store_id,
                    window=time_window_minutes
                )
                
                records = await result.fetch(10)
                return [record["zone_id"] for record in records]
        except Exception as e:
            logger.error(f"Error getting dead zones: {e}")
            return []


# Global instance
graph_manager = GraphManager()
