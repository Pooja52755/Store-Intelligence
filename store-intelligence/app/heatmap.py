"""GET /stores/{store_id}/heatmap endpoint."""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func, and_

from .models import HeatmapResponse, HeatmapZone
from .db import db_manager, Event as DBEvent
from .session_analytics import (
    build_sessions_from_events,
    fetch_store_events,
    heatmap_zone_stats,
    normalize_heatmap_scores,
)

logger = logging.getLogger(__name__)


class HeatmapService:
    """Session-based zone heatmap with normalized scores (today's window)."""

    async def get_heatmap(self, store_id: str) -> HeatmapResponse:
        session = await db_manager.get_session()

        try:
            now = datetime.now(timezone.utc)
            # Use last 48 hours instead of "today only" to handle batch processing
            start_window = now - timedelta(hours=48)

            events = await fetch_store_events(session, store_id, since=start_window)
            sessions = build_sessions_from_events(events)
            stats = heatmap_zone_stats(sessions)

            if not stats:
                return HeatmapResponse(zones=[])

            # Last visit per zone (48-hour window) for alignment with DEAD_ZONE semantics
            last_visits: dict = {}
            for zone_id in stats:
                row = await session.execute(
                    select(func.max(DBEvent.timestamp)).where(
                        and_(
                            DBEvent.store_id == store_id,
                            DBEvent.event_type == "ZONE_ENTER",
                            DBEvent.zone_id == zone_id,
                            DBEvent.is_staff == False,
                            DBEvent.timestamp >= start_window,
                        )
                    )
                )
                ts = row.scalar()
                if ts:
                    last_visits[zone_id] = ts.isoformat().replace("+00:00", "Z")

            scores = normalize_heatmap_scores(stats)
            zones = []
            for zone_id, data in stats.items():
                visit_count = data["visit_count"]
                if visit_count >= 20:
                    confidence = "HIGH"
                elif visit_count >= 5:
                    confidence = "MEDIUM"
                else:
                    confidence = "LOW"

                zones.append(
                    HeatmapZone(
                        zone_id=zone_id,
                        visit_count=visit_count,
                        avg_dwell_ms=data["avg_dwell_ms"],
                        score=scores[zone_id],
                        data_confidence=confidence,
                        last_visit_timestamp=last_visits.get(zone_id),
                    )
                )

            zones.sort(key=lambda z: z.score, reverse=True)
            return HeatmapResponse(zones=zones)

        except Exception as e:
            logger.error("Error calculating heatmap: %s", e)
            return HeatmapResponse(zones=[])
        finally:
            await session.close()


heatmap_service = HeatmapService()
