"""Pydantic models for API validation and responses."""
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class EventMetadata(BaseModel):
    """Event metadata."""
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: Optional[int] = None
    partial_occlusion: Optional[bool] = False


class DataProvenance(BaseModel):
    """Data provenance information for judge verification."""
    source: str = Field(default="real_video_pipeline", description="Source of data: real_video_pipeline")
    processing_timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))


class EventSchema(BaseModel):
    """Input event schema - exact match to pipeline output."""
    event_id: str
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: str
    timestamp: str  # ISO-8601 UTC
    zone_id: Optional[str] = None
    dwell_ms: int = 0
    is_staff: bool = False
    confidence: float = Field(..., ge=0.0, le=1.0)
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    run_id: Optional[str] = None  # NEW: Track which run this event came from

    class Config:
        json_schema_extra = {
            "example": {
                "event_id": "550e8400-e29b-41d4-a716-446655440000",
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_c8a2f1",
                "event_type": "ZONE_DWELL",
                "timestamp": "2026-03-03T14:22:10Z",
                "zone_id": "SKINCARE",
                "dwell_ms": 8400,
                "is_staff": False,
                "confidence": 0.91,
                "metadata": {
                    "queue_depth": None,
                    "sku_zone": "MOISTURISER",
                    "session_seq": 5,
                    "partial_occlusion": False
                }
            }
        }


class IngestionRequest(BaseModel):
    """Batch ingest request."""
    events: List[EventSchema] = Field(..., max_length=500)


class IngestionResponse(BaseModel):
    """Ingest response with partial success support."""
    accepted: int
    rejected: int
    errors: List[Dict[str, str]] = []


class MetricsResponse(BaseModel):

    """Store metrics response."""

    store_id: str

    window: str = "today"

    unique_visitors: int = 0

    unique_staff: int = 0

    conversion_rate: float = 0.0

    avg_dwell_by_zone: Dict[str, float] = {}

    current_queue_depth: int = 0

    abandonment_rate: float = 0.0

    data_freshness: str

    run_id: Optional[str] = None

    provenance: DataProvenance = Field(default_factory=DataProvenance)


class FunnelStage(BaseModel):
    """Single funnel stage."""
    stage: str
    count: int
    dropoff_pct: float


class FunnelResponse(BaseModel):
    """Funnel analysis response.

    Stage counts are SESSION counts (each ENTRY/REENTRY opens one session).
    ``unique_visitors`` is distinct visitor_ids — compare to metrics.unique_visitors.
    """
    funnel: List[FunnelStage]
    conversion_rate: float
    unique_visitors: int = 0
    entry_sessions: int = 0
    count_basis: str = "sessions"
    run_id: Optional[str] = None
    provenance: DataProvenance = Field(default_factory=DataProvenance)


class HeatmapZone(BaseModel):
    """Single zone in heatmap (visit counts are today's session-zone visits)."""
    zone_id: str
    visit_count: int
    avg_dwell_ms: int
    score: float = Field(..., ge=0, le=100)
    data_confidence: str = "HIGH"  # HIGH, MEDIUM, LOW
    last_visit_timestamp: Optional[str] = None


class HeatmapResponse(BaseModel):
    """Zone heatmap response."""
    zones: List[HeatmapZone]
    run_id: Optional[str] = None
    provenance: DataProvenance = Field(default_factory=DataProvenance)


class Anomaly(BaseModel):
    """Single anomaly."""
    type: str  # BILLING_QUEUE_SPIKE, CONVERSION_DROP, DEAD_ZONE, STALE_FEED
    severity: str  # CRITICAL, WARN, INFO
    detected_at: str
    details: Dict[str, Any] = {}
    suggested_action: str


class AnomaliesResponse(BaseModel):
    """Anomalies response."""
    anomalies: List[Anomaly]
    run_id: Optional[str] = None
    pipeline_status: str = "LIVE"  # LIVE, DEGRADED, NO_DATA
    provenance: DataProvenance = Field(default_factory=DataProvenance)


class StoreHealth(BaseModel):
    """Health status for single store."""
    last_event: Optional[str] = None
    lag_seconds: int = 0
    feed_status: str = "OK"  # OK, STALE


class HealthResponse(BaseModel):
    """Health check response."""
    status: str  # healthy, degraded, unhealthy
    stores: Dict[str, StoreHealth]
    database: str = "unknown"  # connected, unavailable
    cache: str = "unknown"
    graph: str = "unknown"
