"""GET /stores/{store_id}/anomalies endpoint with RL threshold tuning."""
import logging
import os
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func, and_

from .models import AnomaliesResponse, Anomaly
from .db import db_manager, Event as DBEvent
from .rl_tuner import rl_tuner
from .anomaly_logic import check_stale_feed, check_dead_zone
from .session_analytics import (
    build_sessions_from_events,
    compute_funnel_counts,
    conversion_rate,
    fetch_store_events,
    load_layout_zone_ids,
)

logger = logging.getLogger(__name__)

STALE_FEED_THRESHOLD_MINUTES = int(os.getenv("STALE_FEED_THRESHOLD_MINUTES", "1440"))  # 24 hours for batch processing
DEAD_ZONE_WINDOW_MINUTES = int(os.getenv("DEAD_ZONE_WINDOW_MINUTES", "30"))
QUEUE_SPIKE_DURATION_MINUTES = int(os.getenv("QUEUE_SPIKE_DURATION_MINUTES", "3"))


class AnomaliesService:
    """Detect active anomalies with RL-tuned thresholds."""

    BILLING_QUEUE_SPIKE = "BILLING_QUEUE_SPIKE"
    CONVERSION_DROP = "CONVERSION_DROP"
    DEAD_ZONE = "DEAD_ZONE"
    STALE_FEED = "STALE_FEED"

    def __init__(self):
        self.redis_client = None

    async def init_redis(self):
        try:
            import redis.asyncio as redis

            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            self.redis_client = await redis.from_url(redis_url, decode_responses=True)
            await self.redis_client.ping()
        except Exception as e:
            logger.warning("Redis unavailable for anomalies: %s", e)
            self.redis_client = None

    async def get_anomalies(self, store_id: str) -> AnomaliesResponse:
        anomalies: List[Anomaly] = []
        try:
            stale = await self._check_stale_feed(store_id)
            if stale:
                anomalies.append(stale)

            for check in (
                self._check_queue_spike,
                self._check_conversion_drop,
            ):
                result = await check(store_id)
                if result:
                    anomalies.append(result)

            # Dead zones are suppressed when feed is stale (all zones look "dead")
            if not stale:
                dead = await self._check_dead_zones(store_id)
                anomalies.extend(dead)
        except Exception as e:
            logger.error("Error detecting anomalies: %s", e)

        return AnomaliesResponse(anomalies=anomalies)

    async def _check_queue_spike(self, store_id: str) -> Optional[Anomaly]:
        try:
            session = await db_manager.get_session()
            now = datetime.now(timezone.utc)
            window_start = now - timedelta(minutes=QUEUE_SPIKE_DURATION_MINUTES + 2)

            rows = await session.execute(
                select(DBEvent.timestamp, DBEvent.queue_depth)
                .where(
                    and_(
                        DBEvent.store_id == store_id,
                        DBEvent.event_type == "BILLING_QUEUE_JOIN",
                        DBEvent.timestamp >= window_start,
                        DBEvent.is_staff == False,
                    )
                )
                .order_by(DBEvent.timestamp.desc())
            )
            recent = rows.fetchall()
            await session.close()

            if not recent:
                return None

            latest_depth = int(recent[0][1] or 0)
            events = await self._today_events(store_id)
            sessions = build_sessions_from_events(events)
            entry, _, _, purchase = compute_funnel_counts(sessions)
            rate = conversion_rate(entry, purchase)

            threshold = rl_tuner.get_optimal_threshold(
                queue_depth=latest_depth,
                conversion_rate=rate,
                hour=now.hour,
                visitor_count=max(entry, 1),
            )

            sustained = [
                r for r in recent if int(r[1] or 0) >= threshold
            ]
            if len(sustained) >= 2 and latest_depth > threshold:
                return Anomaly(
                    type=self.BILLING_QUEUE_SPIKE,
                    severity="CRITICAL",
                    detected_at=now.isoformat().replace("+00:00", "Z"),
                    details={
                        "queue_depth": latest_depth,
                        "threshold": threshold,
                        "duration_minutes": QUEUE_SPIKE_DURATION_MINUTES,
                    },
                    suggested_action="Open additional billing counter immediately",
                )
            return None
        except Exception as e:
            logger.warning("Queue spike check failed: %s", e)
            return None

    async def _check_conversion_drop(self, store_id: str) -> Optional[Anomaly]:
        try:
            session = await db_manager.get_session()
            now = datetime.now(timezone.utc)
            start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            start_of_7days = now - timedelta(days=7)

            today_events = await fetch_store_events(session, store_id, since=start_of_today)
            past_events = await fetch_store_events(session, store_id, since=start_of_7days)
            past_events = [e for e in past_events if _parse(e["timestamp"]) < start_of_today]
            await session.close()

            today_sessions = build_sessions_from_events(today_events)
            past_sessions = build_sessions_from_events(past_events)

            t_entry, _, _, t_purchase = compute_funnel_counts(today_sessions)
            p_entry, _, _, p_purchase = compute_funnel_counts(past_sessions)

            today_rate = conversion_rate(t_entry, t_purchase)
            past_rate = conversion_rate(p_entry, p_purchase)
            threshold = past_rate * 0.7

            if past_rate > 0 and today_rate < threshold:
                return Anomaly(
                    type=self.CONVERSION_DROP,
                    severity="WARN",
                    detected_at=now.isoformat().replace("+00:00", "Z"),
                    details={
                        "today_rate": round(today_rate, 3),
                        "avg_rate": round(past_rate, 3),
                        "threshold": round(threshold, 3),
                    },
                    suggested_action="Review pricing, promotions, or checkout flow",
                )
            return None
        except Exception as e:
            logger.warning("Conversion drop check failed: %s", e)
            return None

    async def _check_dead_zones(self, store_id: str) -> List[Anomaly]:
        """
        Per-zone: no ZONE_ENTER in the last DEAD_ZONE_WINDOW_MINUTES.

        Only zones with at least one historical visit are eligible.
        Zones never visited are skipped (unused layout != dead zone).
        
        If no events exist in DB at all, skip dead zone check (cold start).
        """
        results: List[Anomaly] = []
        try:
            session = await db_manager.get_session()
            now = datetime.now(timezone.utc)
            window_start = now - timedelta(minutes=DEAD_ZONE_WINDOW_MINUTES)

            # Check if any events exist at all - if not, skip dead zone check (cold start)
            total_events = await session.execute(
                select(func.count(DBEvent.event_id)).where(
                    and_(
                        DBEvent.store_id == store_id,
                        DBEvent.is_staff == False,
                    )
                )
            )
            event_count = total_events.scalar() or 0
            if event_count == 0:
                # No events in DB - cold start, don't flag dead zones
                await session.close()
                return results

            zone_ids = load_layout_zone_ids(store_id)
            if not zone_ids:
                seen = await session.execute(
                    select(DBEvent.zone_id)
                    .where(
                        and_(
                            DBEvent.store_id == store_id,
                            DBEvent.zone_id.isnot(None),
                            DBEvent.is_staff == False,
                        )
                    )
                    .distinct()
                )
                zone_ids = [r[0] for r in seen.fetchall() if r[0]]

            for zone_id in zone_ids:
                if zone_id in ("access", "backlit"):
                    continue

                last_visit_row = await session.execute(
                    select(func.max(DBEvent.timestamp)).where(
                        and_(
                            DBEvent.store_id == store_id,
                            DBEvent.event_type == "ZONE_ENTER",
                            DBEvent.zone_id == zone_id,
                            DBEvent.is_staff == False,
                        )
                    )
                )
                last_visit_at = last_visit_row.scalar()

                window_count_row = await session.execute(
                    select(func.count(DBEvent.event_id)).where(
                        and_(
                            DBEvent.store_id == store_id,
                            DBEvent.event_type == "ZONE_ENTER",
                            DBEvent.zone_id == zone_id,
                            DBEvent.is_staff == False,
                            DBEvent.timestamp >= window_start,
                        )
                    )
                )
                visits_in_window = window_count_row.scalar() or 0

                # Debug log per zone
                minutes_since = 0
                if last_visit_at:
                    if last_visit_at.tzinfo is None:
                        last_visit_at = last_visit_at.replace(tzinfo=timezone.utc)
                    minutes_since = (now - last_visit_at).total_seconds() / 60.0
                logger.info(
                    "DEBUG dead_zone: zone_id=%s, last_visit=%s, minutes_since=%.1f, visits_in_window=%d",
                    zone_id,
                    last_visit_at.isoformat().replace("+00:00", "Z") if last_visit_at else "never",
                    minutes_since,
                    visits_in_window
                )

                detail = check_dead_zone(
                    zone_id=zone_id,
                    last_visit_at=last_visit_at,
                    now=now,
                    window_minutes=DEAD_ZONE_WINDOW_MINUTES,
                    visits_in_window=visits_in_window,
                )
                if detail:
                    results.append(
                        Anomaly(
                            type=self.DEAD_ZONE,
                            severity="INFO",
                            detected_at=now.isoformat().replace("+00:00", "Z"),
                            details=detail,
                            suggested_action=(
                                f"Zone '{zone_id}' had no visits in the last "
                                f"{DEAD_ZONE_WINDOW_MINUTES} minutes "
                                f"(last visit: {detail['last_visit_timestamp']})"
                            ),
                        )
                    )

            await session.close()
        except Exception as e:
            logger.warning("Dead zone check failed: %s", e)
        return results[:5]

    async def _check_stale_feed(self, store_id: str) -> Optional[Anomaly]:
        try:
            session = await db_manager.get_session()
            last_event = await session.execute(
                select(func.max(DBEvent.timestamp)).where(DBEvent.store_id == store_id)
            )
            last_event_time = last_event.scalar()
            await session.close()

            now = datetime.now(timezone.utc)
            detail = check_stale_feed(
                now, last_event_time, STALE_FEED_THRESHOLD_MINUTES
            )
            if not detail:
                return None

            return Anomaly(
                type=self.STALE_FEED,
                severity="INFO",
                detected_at=now.isoformat().replace("+00:00", "Z"),
                details=detail,
                suggested_action="Check pipeline status and camera connections",
            )
        except Exception as e:
            logger.warning("Stale feed check failed: %s", e)
            return None

    async def _today_events(self, store_id: str) -> list:
        session = await db_manager.get_session()
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        events = await fetch_store_events(session, store_id, since=start)
        await session.close()
        return events


def _parse(ts):
    from .session_analytics import _parse_ts

    return _parse_ts(ts)


anomalies_service = AnomaliesService()
