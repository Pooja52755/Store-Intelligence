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

    async def get_anomalies(self, store_id: str, run_id: Optional[str] = None) -> AnomaliesResponse:
        anomalies: List[Anomaly] = []
        try:
            stale = await self._check_stale_feed(store_id, run_id=run_id)
            if stale:
                anomalies.append(stale)

            for check in (
                self._check_queue_spike,
                self._check_conversion_drop,
            ):
                result = await check(store_id, run_id=run_id)
                if result:
                    anomalies.append(result)

            # Dead zones are suppressed when feed is stale (all zones look "dead")
            if not stale:
                dead = await self._check_dead_zones(store_id, run_id=run_id)
                anomalies.extend(dead)

            loops = await self._check_looping_pathways(store_id, run_id=run_id)
            anomalies.extend(loops)
        except Exception as e:
            logger.error("Error detecting anomalies: %s", e)

        return AnomaliesResponse(anomalies=anomalies, run_id=run_id)

    async def _check_queue_spike(self, store_id: str, run_id: Optional[str] = None) -> Optional[Anomaly]:
        try:
            session = await db_manager.get_session()
            now = datetime.now(timezone.utc)

            if run_id:
                rows = await session.execute(
                    select(DBEvent.timestamp, DBEvent.queue_depth)
                    .where(
                        and_(
                            DBEvent.store_id == store_id,
                            DBEvent.event_type == "BILLING_QUEUE_JOIN",
                            DBEvent.run_id == run_id,
                            DBEvent.is_staff == False,
                        )
                    )
                    .order_by(DBEvent.timestamp.desc())
                )
            else:
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
            events = await self._today_events(store_id, run_id=run_id)
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

    async def _check_conversion_drop(self, store_id: str, run_id: Optional[str] = None) -> Optional[Anomaly]:
        if run_id:
            return None
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

    async def _check_dead_zones(self, store_id: str, run_id: Optional[str] = None) -> List[Anomaly]:
        results: List[Anomaly] = []
        try:
            session = await db_manager.get_session()
            now = datetime.now(timezone.utc)
            window_start = now - timedelta(minutes=DEAD_ZONE_WINDOW_MINUTES)

            # Check if any events exist at all - cold start prevention
            where_clause = and_(DBEvent.store_id == store_id, DBEvent.is_staff == False)
            if run_id:
                where_clause = and_(where_clause, DBEvent.run_id == run_id)
            total_events = await session.execute(
                select(func.count(DBEvent.event_id)).where(where_clause)
            )
            event_count = total_events.scalar() or 0
            if event_count == 0:
                await session.close()
                return results

            zone_ids = load_layout_zone_ids(store_id)
            if not zone_ids:
                seen_clause = and_(DBEvent.store_id == store_id, DBEvent.zone_id.isnot(None), DBEvent.is_staff == False)
                if run_id:
                    seen_clause = and_(seen_clause, DBEvent.run_id == run_id)
                seen = await session.execute(
                    select(DBEvent.zone_id).where(seen_clause).distinct()
                )
                zone_ids = [r[0] for r in seen.fetchall() if r[0]]

            # Rule 8: Suppress minor or spurious dead zones unless there is a true retail dead zone
            # Avoid triggering dead zones due to tracking loss or mirrors
            for zone_id in zone_ids:
                if zone_id in ("access", "backlit", "entry", "central_aisle"):
                    continue

                last_visit_where = and_(
                    DBEvent.store_id == store_id,
                    DBEvent.event_type == "ZONE_ENTER",
                    DBEvent.zone_id == zone_id,
                    DBEvent.is_staff == False,
                )
                if run_id:
                    last_visit_where = and_(last_visit_where, DBEvent.run_id == run_id)

                last_visit_row = await session.execute(
                    select(func.max(DBEvent.timestamp)).where(last_visit_where)
                )
                last_visit_at = last_visit_row.scalar()

                if run_id:
                    window_count_row = await session.execute(
                        select(func.count(DBEvent.event_id)).where(
                            and_(
                                DBEvent.store_id == store_id,
                                DBEvent.event_type == "ZONE_ENTER",
                                DBEvent.zone_id == zone_id,
                                DBEvent.is_staff == False,
                                DBEvent.run_id == run_id,
                            )
                        )
                    )
                else:
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

                # Compute time since last visit or default
                minutes_since = 0
                if last_visit_at:
                    if last_visit_at.tzinfo is None:
                        last_visit_at = last_visit_at.replace(tzinfo=timezone.utc)
                    minutes_since = (now - last_visit_at).total_seconds() / 60.0

                detail = None
                if run_id:
                    if visits_in_window == 0:
                        detail = {
                            "zone_id": zone_id,
                            "last_visit_timestamp": last_visit_at.isoformat().replace("+00:00", "Z") if last_visit_at else "never",
                            "business_impact": "No shopper engagement recorded",
                            "suggested_action": "Review product placement or visibility",
                            "visits_in_window": 0
                        }
                else:
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
                            severity="WARN" if run_id else "INFO",
                            detected_at=now.isoformat().replace("+00:00", "Z"),
                            details=detail,
                            suggested_action=(
                                "Review product placement or visibility" if run_id else
                                f"Zone '{zone_id}' had no visits in the last {DEAD_ZONE_WINDOW_MINUTES} minutes"
                            ),
                        )
                    )

            await session.close()
        except Exception as e:
            logger.warning("Dead zone check failed: %s", e)
        return results[:5]

    async def _check_stale_feed(self, store_id: str, run_id: Optional[str] = None) -> Optional[Anomaly]:
        if run_id:
            return None
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

    async def _today_events(self, store_id: str, run_id: Optional[str] = None) -> list:
        session = await db_manager.get_session()
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        events = await fetch_store_events(session, store_id, since=None if run_id else start, run_id=run_id)
        await session.close()
        return events

    async def _check_looping_pathways(self, store_id: str, run_id: Optional[str] = None) -> List[Anomaly]:
        results = []
        try:
            events = await self._today_events(store_id, run_id=run_id)
            if not events:
                return results
                
            from collections import defaultdict
            visitor_paths = defaultdict(list)
            for ev in events:
                if ev.get("is_staff"):
                    continue
                visitor_id = ev["visitor_id"]
                visitor_paths[visitor_id].append(ev)
                
            now = datetime.now(timezone.utc)
            
            for visitor_id, evs in visitor_paths.items():
                sorted_evs = sorted(evs, key=lambda e: _parse(e["timestamp"]))
                
                zone_sequence = []
                for ev in sorted_evs:
                    if ev["event_type"] == "ZONE_ENTER" and ev.get("zone_id"):
                        zone = ev["zone_id"]
                        if not zone_sequence or zone_sequence[-1] != zone:
                            zone_sequence.append(zone)
                            
                zone_counts = defaultdict(int)
                for zone in zone_sequence:
                    zone_counts[zone] += 1
                    
                for zone, count in zone_counts.items():
                    if count >= 3 and zone in ("skincare", "moisturiser", "cash_counter", "beauty_counter", "face_wash", "makeup"):
                        results.append(
                            Anomaly(
                                type="SUSPICIOUS_LOOP",
                                severity="WARN",
                                detected_at=now.isoformat().replace("+00:00", "Z"),
                                details={
                                    "visitor_id": visitor_id,
                                    "zone_id": zone,
                                    "visit_count": count,
                                    "pathway": zone_sequence
                                },
                                suggested_action=f"Assign staff to assist visitor '{visitor_id}' at zone '{zone}'",
                            )
                        )
                        break
        except Exception as e:
            logger.warning("Looping pathway check failed: %s", e)
        return results


def _parse(ts):
    from .session_analytics import _parse_ts

    return _parse_ts(ts)


anomalies_service = AnomaliesService()
