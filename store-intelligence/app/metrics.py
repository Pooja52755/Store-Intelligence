"""GET /stores/{store_id}/metrics endpoint."""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, func, and_

from .models import MetricsResponse
from .db import db_manager, Event as DBEvent
from .session_analytics import (
    build_sessions_from_events,
    compute_funnel_counts,
    conversion_rate,
    avg_dwell_by_zone,
    unique_visitors,
    fetch_store_events,
)

logger = logging.getLogger(__name__)


class MetricsService:
    """Calculate store metrics from session-based analytics."""

    async def get_metrics(self, store_id: str, run_id: Optional[str] = None) -> MetricsResponse:
        session = await db_manager.get_session()

        try:
            now = datetime.now(timezone.utc)
            # Use last 48 hours instead of "today only" to handle batch processing
            start_window = now - timedelta(hours=48)

            # If run_id provided, use it; otherwise use time-based filtering
            events = await fetch_store_events(session, store_id, since=None if run_id else start_window, run_id=run_id)
            sessions = build_sessions_from_events(events)

            entry_sessions, _, _, purchase_sessions = compute_funnel_counts(sessions)
            visitors = entry_sessions  # Rule 3: unique_visitors = number of sessions, entry_sessions ≈ unique_visitors
            conv_rate = conversion_rate(entry_sessions, purchase_sessions)
            dwell_by_zone = avg_dwell_by_zone(sessions)

            # Build queue depth query with run_id filter if provided
            queue_where = and_(
                DBEvent.store_id == store_id,
                DBEvent.event_type == "BILLING_QUEUE_JOIN",
                DBEvent.is_staff == False,
                DBEvent.queue_depth.isnot(None),
            )
            if run_id:
                queue_where = and_(queue_where, DBEvent.run_id == run_id)
            else:
                queue_where = and_(queue_where, DBEvent.timestamp >= start_window)
            
            queue_result = await session.execute(
                select(DBEvent.queue_depth)
                .where(queue_where)
                .order_by(DBEvent.timestamp.desc())
                .limit(1)
            )
            current_queue_depth = int(queue_result.scalar() or 0)

            # Build queue joins query with run_id filter if provided
            joins_where = and_(
                DBEvent.store_id == store_id,
                DBEvent.event_type == "BILLING_QUEUE_JOIN",
                DBEvent.is_staff == False,
            )
            if run_id:
                joins_where = and_(joins_where, DBEvent.run_id == run_id)
            else:
                joins_where = and_(joins_where, DBEvent.timestamp >= start_window)
            
            queue_joins = await session.execute(
                select(func.count(DBEvent.event_id)).where(joins_where)
            )
            queue_joins_count = queue_joins.scalar() or 0

            # Build queue abandons query with run_id filter if provided
            abandons_where = and_(
                DBEvent.store_id == store_id,
                DBEvent.event_type == "BILLING_QUEUE_ABANDON",
                DBEvent.is_staff == False,
            )
            if run_id:
                abandons_where = and_(abandons_where, DBEvent.run_id == run_id)
            else:
                abandons_where = and_(abandons_where, DBEvent.timestamp >= start_window)
            
            queue_abandons = await session.execute(
                select(func.count(DBEvent.event_id)).where(abandons_where)
            )
            queue_abandons_count = queue_abandons.scalar() or 0

            abandonment_rate = (
                queue_abandons_count / queue_joins_count if queue_joins_count > 0 else 0.0
            )

            last_event_result = await session.execute(
                select(func.max(DBEvent.timestamp)).where(DBEvent.store_id == store_id)
            )
            last_event_time = last_event_result.scalar()
            data_freshness = (
                last_event_time.isoformat().replace("+00:00", "Z")
                if last_event_time
                else now.isoformat().replace("+00:00", "Z")
            )

            return MetricsResponse(
                store_id=store_id,
                window="today",
                unique_visitors=visitors,
                conversion_rate=conv_rate,
                avg_dwell_by_zone=dwell_by_zone,
                current_queue_depth=current_queue_depth,
                abandonment_rate=min(max(abandonment_rate, 0.0), 1.0),
                data_freshness=data_freshness,
            )

        except Exception as e:
            logger.error("Error calculating metrics: %s", e)
            return MetricsResponse(
                store_id=store_id,
                window="today",
                unique_visitors=0,
                conversion_rate=0.0,
                avg_dwell_by_zone={},
                current_queue_depth=0,
                abandonment_rate=0.0,
                data_freshness=datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
            )
        finally:
            await session.close()


metrics_service = MetricsService()
