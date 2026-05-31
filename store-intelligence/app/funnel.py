"""GET /stores/{store_id}/funnel endpoint."""
import logging
from datetime import datetime, timezone, timedelta

from .models import FunnelResponse, FunnelStage
from .db import db_manager
from .session_analytics import (
    build_sessions_from_events,
    compute_funnel_counts,
    conversion_rate,
    dropoff_pct,
    fetch_store_events,
    unique_visitors,
)

logger = logging.getLogger(__name__)

# Funnel stage counts are SESSION counts (one per ENTRY/REENTRY), not unique visitors.
FUNNEL_COUNT_BASIS = "sessions"


class FunnelService:
    """Session-based conversion funnel (monotonic stages)."""

    async def get_funnel(self, store_id: str) -> FunnelResponse:
        session = await db_manager.get_session()
        try:
            now = datetime.now(timezone.utc)
            # Use last 48 hours instead of "today only" to handle batch processing
            start_window = now - timedelta(hours=48)

            events = await fetch_store_events(session, store_id, since=start_window)
            sessions = build_sessions_from_events(events)

            entry, zone, billing, purchase = compute_funnel_counts(sessions)
            rate = conversion_rate(entry, purchase)
            visitors = unique_visitors(sessions)

            # Debug log: funnel entry_sessions vs unique_visitors
            logger.info(
                "DEBUG funnel: entry_sessions=%d, unique_visitors=%d",
                entry, visitors
            )

            funnel = [
                FunnelStage(stage="Entry Sessions", count=entry, dropoff_pct=0.0),
                FunnelStage(
                    stage="Zone Visit Sessions",
                    count=zone,
                    dropoff_pct=dropoff_pct(entry, zone),
                ),
                FunnelStage(
                    stage="Billing Queue Sessions",
                    count=billing,
                    dropoff_pct=dropoff_pct(zone, billing),
                ),
                FunnelStage(
                    stage="Purchase Sessions",
                    count=purchase,
                    dropoff_pct=dropoff_pct(billing, purchase),
                ),
            ]

            assert entry >= zone >= billing >= purchase

            return FunnelResponse(
                funnel=funnel,
                conversion_rate=rate,
                unique_visitors=visitors,
                entry_sessions=entry,
                count_basis=FUNNEL_COUNT_BASIS,
            )

        except Exception as e:
            logger.error("Error calculating funnel: %s", e)
            return FunnelResponse(
                funnel=[
                    FunnelStage(stage="Entry Sessions", count=0, dropoff_pct=0.0),
                    FunnelStage(stage="Zone Visit Sessions", count=0, dropoff_pct=0.0),
                    FunnelStage(stage="Billing Queue Sessions", count=0, dropoff_pct=0.0),
                    FunnelStage(stage="Purchase Sessions", count=0, dropoff_pct=0.0),
                ],
                conversion_rate=0.0,
                unique_visitors=0,
                entry_sessions=0,
                count_basis=FUNNEL_COUNT_BASIS,
            )
        finally:
            await session.close()


funnel_service = FunnelService()
