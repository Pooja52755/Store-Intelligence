"""Validation tests for session analytics, funnel, heatmap, and anomalies logic."""
from datetime import datetime, timezone, timedelta

import pytest

from app.session_analytics import (
    build_sessions_from_events,
    compute_funnel_counts,
    conversion_rate,
    dropoff_pct,
    avg_dwell_by_zone,
    heatmap_zone_stats,
    normalize_heatmap_scores,
    unique_visitors,
)


def _ev(
    etype,
    visitor_id="V1",
    zone_id=None,
    dwell_ms=0,
    offset_sec=0,
    is_staff=False,
):
    base = datetime(2026, 5, 30, 10, 0, 0, tzinfo=timezone.utc)
    return {
        "event_id": f"{etype}_{visitor_id}_{offset_sec}",
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM1",
        "visitor_id": visitor_id,
        "event_type": etype,
        "timestamp": base + timedelta(seconds=offset_sec),
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": is_staff,
    }


class TestFunnelConsistency:
    def test_monotonic_funnel_stages(self):
        events = [
            _ev("ENTRY", "V1", "entry", offset_sec=0),
            _ev("ZONE_ENTER", "V1", "faces_zone", offset_sec=10),
            _ev("BILLING_QUEUE_JOIN", "V1", "cash_counter", offset_sec=60),
            _ev("EXIT", "V1", "entry", offset_sec=120),
            _ev("ENTRY", "V2", "entry", offset_sec=5),
            _ev("ZONE_ENTER", "V2", "maybelline_zone", offset_sec=15),
            _ev("EXIT", "V2", offset_sec=90),
        ]
        sessions = build_sessions_from_events(events)
        entry, zone, billing, purchase = compute_funnel_counts(sessions)

        assert entry >= zone >= billing >= purchase
        assert entry == 2
        assert zone == 2
        assert billing == 1
        assert purchase == 1

    def test_purchase_never_exceeds_billing(self):
        events = [
            _ev("ENTRY", "V1", offset_sec=0),
            _ev("ZONE_ENTER", "V1", "cash_counter", offset_sec=10),
            _ev("BILLING_QUEUE_JOIN", "V1", "cash_counter", offset_sec=20),
            _ev("BILLING_QUEUE_ABANDON", "V1", "cash_counter", offset_sec=40),
            _ev("EXIT", "V1", offset_sec=50),
        ]
        sessions = build_sessions_from_events(events)
        _, _, billing, purchase = compute_funnel_counts(sessions)
        assert purchase <= billing
        assert purchase == 0

    def test_staff_excluded(self):
        events = [
            _ev("ENTRY", "S1", is_staff=True, offset_sec=0),
            _ev("ZONE_ENTER", "S1", "faces_zone", is_staff=True, offset_sec=10),
        ]
        sessions = build_sessions_from_events(events)
        assert len(sessions) == 0
        assert unique_visitors(sessions) == 0


class TestConversionRate:
    def test_purchase_over_entry(self):
        events = [
            _ev("ENTRY", "V1", offset_sec=0),
            _ev("ZONE_ENTER", "V1", "cash_counter", offset_sec=10),
            _ev("BILLING_QUEUE_JOIN", "V1", "cash_counter", offset_sec=20),
            _ev("EXIT", "V1", offset_sec=60),
            _ev("ENTRY", "V2", offset_sec=1),
            _ev("EXIT", "V2", offset_sec=30),
        ]
        sessions = build_sessions_from_events(events)
        entry, _, _, purchase = compute_funnel_counts(sessions)
        rate = conversion_rate(entry, purchase)
        assert rate == 0.5
        assert 0.0 <= rate <= 1.0

    def test_zero_entry_sessions(self):
        assert conversion_rate(0, 0) == 0.0


class TestDwellTime:
    def test_dwell_from_zone_exit_timestamps(self):
        events = [
            _ev("ENTRY", "V1", offset_sec=0),
            _ev("ZONE_ENTER", "V1", "faces_zone", offset_sec=10),
            _ev("ZONE_EXIT", "V1", "faces_zone", dwell_ms=45000, offset_sec=55),
            _ev("EXIT", "V1", offset_sec=60),
        ]
        sessions = build_sessions_from_events(events)
        dwell = avg_dwell_by_zone(sessions)
        assert "faces_zone" in dwell
        assert dwell["faces_zone"] == 45000.0

    def test_store_dwell_exit_minus_entry(self):
        events = [
            _ev("ENTRY", "V1", offset_sec=0),
            _ev("EXIT", "V1", offset_sec=120),
        ]
        sessions = build_sessions_from_events(events)
        assert sessions[0].store_dwell_ms == 120000


class TestHeatmap:
    def test_normalized_scores(self):
        events = [
            _ev("ENTRY", "V1", offset_sec=0),
            _ev("ZONE_ENTER", "V1", "faces_zone", offset_sec=5),
            _ev("ENTRY", "V2", offset_sec=1),
            _ev("ZONE_ENTER", "V2", "faces_zone", offset_sec=6),
            _ev("ZONE_ENTER", "V2", "maybelline_zone", offset_sec=10),
        ]
        sessions = build_sessions_from_events(events)
        stats = heatmap_zone_stats(sessions)
        scores = normalize_heatmap_scores(stats)

        assert scores["faces_zone"] == 100.0
        assert scores["maybelline_zone"] == 50.0
        assert all(0 <= s <= 100 for s in scores.values())


class TestReentry:
    def test_reentry_creates_new_session(self):
        events = [
            _ev("ENTRY", "V1", offset_sec=0),
            _ev("EXIT", "V1", offset_sec=30),
            _ev("REENTRY", "V1", offset_sec=60),
            _ev("EXIT", "V1", offset_sec=90),
        ]
        sessions = build_sessions_from_events(events)
        assert len(sessions) == 2
        assert unique_visitors(sessions) == 1
        assert compute_funnel_counts(sessions)[0] == 2


class TestUniqueVisitorsVsSessions:
    def test_entry_sessions_exceed_unique_visitors_with_reentries(self):
        events = []
        for i in range(3):
            events.append(_ev("ENTRY", "V1", offset_sec=i * 100))
            events.append(_ev("EXIT", "V1", offset_sec=i * 100 + 50))
        sessions = build_sessions_from_events(events)
        assert compute_funnel_counts(sessions)[0] == 3
        assert unique_visitors(sessions) == 1


class TestDropoff:
    def test_dropoff_non_negative(self):
        assert dropoff_pct(10, 7) == 30.0
        assert dropoff_pct(10, 10) == 0.0
