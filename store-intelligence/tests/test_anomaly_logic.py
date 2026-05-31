"""Unit tests for anomaly_logic and counting semantics."""
from datetime import datetime, timezone, timedelta

import pytest

from app.anomaly_logic import check_stale_feed, check_dead_zone, DEAD_ZONE_SEMANTICS
from app.session_analytics import (
    build_sessions_from_events,
    compute_funnel_counts,
    unique_visitors,
)


NOW = datetime(2026, 5, 30, 15, 0, 0, tzinfo=timezone.utc)


def _ev(etype, visitor_id="V1", zone_id=None, offset_sec=0):
    base = datetime(2026, 5, 30, 10, 0, 0, tzinfo=timezone.utc)
    return {
        "event_id": f"{etype}_{visitor_id}_{offset_sec}",
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM1",
        "visitor_id": visitor_id,
        "event_type": etype,
        "timestamp": base + timedelta(seconds=offset_sec),
        "zone_id": zone_id,
        "dwell_ms": 0,
        "is_staff": False,
    }


class TestStaleFeed:
    def test_triggers_when_lag_exceeds_threshold(self):
        last = NOW - timedelta(minutes=15)
        detail = check_stale_feed(NOW, last, threshold_minutes=10)
        assert detail is not None
        assert detail["lag_minutes"] == 15.0
        assert detail["last_event_timestamp"].endswith("Z")

    def test_no_trigger_within_threshold(self):
        last = NOW - timedelta(minutes=5)
        assert check_stale_feed(NOW, last, threshold_minutes=10) is None

    def test_no_trigger_without_events(self):
        assert check_stale_feed(NOW, None, threshold_minutes=10) is None


class TestDeadZone:
    def test_semantics_no_visits_in_window_with_last_visit(self):
        last = NOW - timedelta(minutes=45)
        detail = check_dead_zone(
            zone_id="entry",
            last_visit_at=last,
            now=NOW,
            window_minutes=30,
            visits_in_window=0,
        )
        assert detail is not None
        assert detail["semantics"] == DEAD_ZONE_SEMANTICS
        assert detail["last_visit_timestamp"] == last.isoformat().replace("+00:00", "Z")
        assert detail["minutes_since_last_visit"] == 45.0
        assert detail["visits_in_window"] == 0

    def test_no_trigger_when_recent_visit_in_window(self):
        last = NOW - timedelta(minutes=45)
        assert (
            check_dead_zone("entry", last, NOW, 30, visits_in_window=3) is None
        )

    def test_no_trigger_for_never_visited_zone(self):
        """Never-visited zones must NOT raise DEAD_ZONE (fixes heatmap contradiction)."""
        assert check_dead_zone("unused_zone", None, NOW, 30, 0) is None

    def test_no_trigger_when_last_visit_within_window(self):
        last = NOW - timedelta(minutes=10)
        assert check_dead_zone("entry", last, NOW, 30, 0) is None


class TestUniqueVisitorsVsEntrySessions:
    def test_reentry_inflates_sessions_not_unique_visitors(self):
        events = []
        for i in range(4):
            events.append(_ev("ENTRY", "V1", offset_sec=i * 200))
            events.append(_ev("ZONE_ENTER", "V1", "entry", offset_sec=i * 200 + 5))
            events.append(_ev("EXIT", "V1", offset_sec=i * 200 + 100))
        sessions = build_sessions_from_events(events)
        entry_sessions, _, _, _ = compute_funnel_counts(sessions)
        assert entry_sessions == 4
        assert unique_visitors(sessions) == 1

    def test_multiple_visitors(self):
        events = [
            _ev("ENTRY", "V1", offset_sec=0),
            _ev("ENTRY", "V2", offset_sec=1),
            _ev("ENTRY", "V3", offset_sec=2),
        ]
        sessions = build_sessions_from_events(events)
        assert compute_funnel_counts(sessions)[0] == 3
        assert unique_visitors(sessions) == 3


class TestFunnelConsistency:
    def test_monotonic_stages(self):
        events = [
            _ev("ENTRY", "V1", offset_sec=0),
            _ev("ZONE_ENTER", "V1", "entry", offset_sec=5),
            _ev("ENTRY", "V2", offset_sec=10),
        ]
        sessions = build_sessions_from_events(events)
        e, z, b, p = compute_funnel_counts(sessions)
        assert e >= z >= b >= p
