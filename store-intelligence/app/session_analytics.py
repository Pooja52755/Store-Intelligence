"""Session-based visitor analytics — single source of truth for funnel, metrics, heatmap."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from .db import Event as DBEvent

BILLING_ZONES = frozenset({"cash_counter", "beauty_counter"})


@dataclass
class VisitorSession:
    """One store visit (ENTRY/REENTRY through EXIT)."""

    session_id: str
    visitor_id: str
    store_id: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    is_reentry: bool = False
    is_staff: bool = False
    zones_visited: Set[str] = field(default_factory=set)
    billing_queue_joined: bool = False
    billing_abandoned: bool = False
    zone_enter_at: Dict[str, datetime] = field(default_factory=dict)
    zone_dwell_ms: Dict[str, int] = field(default_factory=dict)

    @property
    def has_entry(self) -> bool:
        return self.started_at is not None

    @property
    def has_zone_visit(self) -> bool:
        return len(self.zones_visited) > 0

    @property
    def has_billing_queue(self) -> bool:
        return self.billing_queue_joined

    @property
    def is_purchase(self) -> bool:
        return (
            self.billing_queue_joined
            and not self.billing_abandoned
            and self.ended_at is not None
        )

    @property
    def store_dwell_ms(self) -> int:
        if self.started_at and self.ended_at:
            return max(0, int((self.ended_at - self.started_at).total_seconds() * 1000))
        return 0


def _parse_ts(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        ts = value
    else:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def build_sessions_from_events(events: List[dict]) -> List[VisitorSession]:
    """
    Build visitor sessions from ordered event dicts.

    Rules:
    - Staff excluded entirely
    - ENTRY / REENTRY opens a session
    - EXIT closes the active session
    - Re-entry creates a new session (not double-counted as same session)
    """
    sessions: List[VisitorSession] = []
    active: Dict[str, VisitorSession] = {}

    sorted_events = sorted(events, key=lambda e: _parse_ts(e["timestamp"]))

    for ev in sorted_events:
        if ev.get("is_staff"):
            continue

        visitor_id = ev["visitor_id"]
        store_id = ev["store_id"]
        ts = _parse_ts(ev["timestamp"])
        etype = ev["event_type"]
        zone_id = ev.get("zone_id")

        if etype in ("ENTRY", "REENTRY"):
            if visitor_id in active:
                prev = active.pop(visitor_id)
                if prev.started_at and prev.ended_at is None:
                    prev.ended_at = ts
                sessions.append(prev)

            sess = VisitorSession(
                session_id=str(ev.get("event_id", uuid.uuid4())),
                visitor_id=visitor_id,
                store_id=store_id,
                started_at=ts,
                is_reentry=(etype == "REENTRY"),
            )
            active[visitor_id] = sess
            if zone_id:
                sess.zones_visited.add(zone_id)
                sess.zone_enter_at[zone_id] = ts
            continue

        sess = active.get(visitor_id)
        if sess is None:
            continue

        if etype == "ZONE_ENTER" and zone_id:
            sess.zones_visited.add(zone_id)
            sess.zone_enter_at.setdefault(zone_id, ts)

        elif etype == "ZONE_EXIT" and zone_id:
            entered = sess.zone_enter_at.get(zone_id, ts)
            dwell_ms = max(0, int((ts - entered).total_seconds() * 1000))
            explicit = int(ev.get("dwell_ms") or 0)
            if explicit > 0:
                dwell_ms = explicit
            sess.zone_dwell_ms[zone_id] = sess.zone_dwell_ms.get(zone_id, 0) + dwell_ms
            sess.zone_enter_at.pop(zone_id, None)

        elif etype == "ZONE_DWELL" and zone_id:
            dwell = int(ev.get("dwell_ms") or 0)
            if dwell > sess.zone_dwell_ms.get(zone_id, 0):
                sess.zone_dwell_ms[zone_id] = dwell

        elif etype == "BILLING_QUEUE_JOIN":
            sess.billing_queue_joined = True

        elif etype == "BILLING_QUEUE_ABANDON":
            sess.billing_abandoned = True

        elif etype == "EXIT":
            sess.ended_at = ts
            for zid, entered in list(sess.zone_enter_at.items()):
                dwell_ms = max(0, int((ts - entered).total_seconds() * 1000))
                sess.zone_dwell_ms[zid] = sess.zone_dwell_ms.get(zid, 0) + dwell_ms
            sess.zone_enter_at.clear()
            sessions.append(active.pop(visitor_id))

    for sess in active.values():
        sessions.append(sess)

    return sessions


def compute_funnel_counts(sessions: List[VisitorSession]) -> Tuple[int, int, int, int]:
    """Return entry, zone_visit, billing_queue, purchase SESSION counts (monotonic).

    Each ENTRY or REENTRY opens one session. This is NOT unique visitor count;
    use ``unique_visitors(sessions)`` for distinct visitor_ids.
    """
    entry = sum(1 for s in sessions if s.has_entry)
    zone = sum(1 for s in sessions if s.has_entry and s.has_zone_visit)
    billing = sum(1 for s in sessions if s.has_entry and s.has_zone_visit and s.has_billing_queue)
    purchase = sum(
        1
        for s in sessions
        if s.has_entry and s.has_zone_visit and s.has_billing_queue and s.is_purchase
    )

    zone = min(zone, entry)
    billing = min(billing, zone)
    purchase = min(purchase, billing)
    return entry, zone, billing, purchase


def conversion_rate(entry_sessions: int, purchase_sessions: int) -> float:
    if entry_sessions <= 0:
        return 0.0
    return min(max(purchase_sessions / entry_sessions, 0.0), 1.0)


def dropoff_pct(from_count: int, to_count: int) -> float:
    if from_count <= 0:
        return 0.0
    return round(max(0.0, (from_count - to_count) / from_count * 100), 1)


def avg_dwell_by_zone(sessions: List[VisitorSession]) -> Dict[str, float]:
    """Average zone dwell (ms) from exit-enter pairs per session."""
    totals: Dict[str, List[int]] = {}
    for sess in sessions:
        for zone_id, dwell in sess.zone_dwell_ms.items():
            if dwell > 0:
                totals.setdefault(zone_id, []).append(dwell)
    return {z: sum(v) / len(v) for z, v in totals.items() if v}


def heatmap_zone_stats(sessions: List[VisitorSession]) -> Dict[str, dict]:
    """Per-zone visit counts and avg dwell for heatmap."""
    visit_counts: Dict[str, int] = {}
    dwell_lists: Dict[str, List[int]] = {}

    for sess in sessions:
        for zone_id in sess.zones_visited:
            visit_counts[zone_id] = visit_counts.get(zone_id, 0) + 1
            dwell = sess.zone_dwell_ms.get(zone_id, 0)
            if dwell > 0:
                dwell_lists.setdefault(zone_id, []).append(dwell)

    stats = {}
    for zone_id, count in visit_counts.items():
        dwells = dwell_lists.get(zone_id, [])
        stats[zone_id] = {
            "visit_count": count,
            "avg_dwell_ms": int(sum(dwells) / len(dwells)) if dwells else 0,
        }
    return stats


def normalize_heatmap_scores(zone_stats: Dict[str, dict]) -> Dict[str, float]:
    if not zone_stats:
        return {}
    max_visits = max(s["visit_count"] for s in zone_stats.values())
    max_visits = max(max_visits, 1)
    return {
        z: round((s["visit_count"] / max_visits) * 100, 1)
        for z, s in zone_stats.items()
    }


def unique_visitors(sessions: List[VisitorSession]) -> int:
    """Distinct non-staff visitors with at least one entry session."""
    return len({s.visitor_id for s in sessions if s.has_entry})


async def fetch_store_events(
    session: AsyncSession,
    store_id: str,
    since: Optional[datetime] = None,
    run_id: Optional[str] = None,
) -> List[dict]:
    """Load customer events from DB as dicts for session builder.
    
    Args:
        session: AsyncSession
        store_id: Store identifier
        since: Optional datetime filter (events after this time)
        run_id: Optional run_id filter (if provided, only events from this run)
    """
    q = select(DBEvent).where(
        and_(DBEvent.store_id == store_id, DBEvent.is_staff == False)
    )
    if run_id:
        q = q.where(DBEvent.run_id == run_id)
    if since:
        q = q.where(DBEvent.timestamp >= since)
    q = q.order_by(DBEvent.timestamp.asc())

    result = await session.execute(q)
    rows = result.scalars().all()
    return [
        {
            "event_id": str(r.event_id),
            "store_id": r.store_id,
            "camera_id": r.camera_id,
            "visitor_id": r.visitor_id,
            "event_type": r.event_type,
            "timestamp": r.timestamp,
            "zone_id": r.zone_id,
            "dwell_ms": r.dwell_ms or 0,
            "is_staff": r.is_staff,
        }
        for r in rows
    ]


def load_layout_zone_ids(store_id: str) -> List[str]:
    """Load zone ids from store_layout.json for dead-zone checks."""
    layout_path = Path(os.getenv("LAYOUT_FILE", "events/store_layout.json"))
    if not layout_path.is_absolute():
        layout_path = Path(__file__).resolve().parent.parent / layout_path
    if not layout_path.exists():
        return []
    try:
        data = json.loads(layout_path.read_text(encoding="utf-8"))
        if data.get("store_id") != store_id and store_id:
            pass
        return list(data.get("zones", {}).keys())
    except Exception:
        return []
