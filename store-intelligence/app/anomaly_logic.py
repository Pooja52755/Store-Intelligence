"""Pure functions for anomaly detection (testable without DB)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


DEAD_ZONE_SEMANTICS = "no_visits_in_window"


def iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def check_stale_feed(
    now: datetime,
    last_event_at: Optional[datetime],
    threshold_minutes: float,
) -> Optional[Dict[str, Any]]:
    """
    STALE_FEED when (now - last_event_at) > threshold.

    Does not fire when there are no events at all (empty store).
    """
    if last_event_at is None:
        return None
    if last_event_at.tzinfo is None:
        last_event_at = last_event_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    lag_minutes = (now - last_event_at).total_seconds() / 60.0
    if lag_minutes <= threshold_minutes:
        return None

    return {
        "semantics": "pipeline_lag_exceeds_threshold",
        "lag_minutes": round(lag_minutes, 1),
        "threshold_minutes": threshold_minutes,
        "last_event_timestamp": iso_z(last_event_at),
    }


def check_dead_zone(
    zone_id: str,
    last_visit_at: Optional[datetime],
    now: datetime,
    window_minutes: int,
    visits_in_window: int = 0,
) -> Optional[Dict[str, Any]]:
    """
    DEAD_ZONE semantics (option 1): no ZONE_ENTER in the last N minutes.

    - Requires the zone to have been visited at least once (last_visit_at set).
      Zones never visited are NOT flagged (unused layout zone != dead zone).
    - When visits_in_window > 0, zone is active and not dead.
    """
    if visits_in_window > 0:
        return None

    if last_visit_at is None:
        # Never visited — not a dead-zone anomaly (would contradict heatmap "never seen")
        return None

    if last_visit_at.tzinfo is None:
        last_visit_at = last_visit_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    minutes_since = (now - last_visit_at).total_seconds() / 60.0
    if minutes_since <= window_minutes:
        return None

    return {
        "zone_id": zone_id,
        "semantics": DEAD_ZONE_SEMANTICS,
        "window_minutes": window_minutes,
        "last_visit_timestamp": iso_z(last_visit_at),
        "minutes_since_last_visit": round(minutes_since, 1),
        "visits_in_window": 0,
    }


def entry_sessions_vs_unique_visitors(sessions) -> Dict[str, int]:
    """Document funnel vs metrics counting basis."""
    from .session_analytics import compute_funnel_counts, unique_visitors

    entry_sessions, _, _, _ = compute_funnel_counts(sessions)
    return {
        "entry_sessions": entry_sessions,
        "unique_visitors": unique_visitors(sessions),
    }
