"""Event schema definition and JSONL writer."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class EventMetadata(BaseModel):
    """Event metadata (extensible without schema migration)."""
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: Optional[int] = None
    partial_occlusion: Optional[bool] = False
    x: Optional[float] = None
    y: Optional[float] = None


class Event(BaseModel):
    """Exact required output schema."""
    event_id: str = Field(..., description="UUID v4")
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: str  # ENTRY, EXIT, ZONE_ENTER, ZONE_EXIT, ZONE_DWELL, BILLING_QUEUE_JOIN, BILLING_QUEUE_ABANDON, REENTRY
    timestamp: str  # ISO-8601 UTC
    zone_id: Optional[str] = None
    dwell_ms: int = 0
    is_staff: bool = False
    confidence: float
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    run_id: Optional[str] = None  # Tracks which pipeline run generated this event

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


class EventWriter:
    """JSONL event writer with validation."""

    def __init__(self, output_path: str):
        """Initialize writer."""
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.touch(exist_ok=True)

    def write_event(self, event: Event) -> bool:
        """
        Write validated event to JSONL.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Validate against schema
            event_dict = event.model_dump(exclude_none=False)
            
            # Write as JSON line
            with open(self.output_path, 'a') as f:
                f.write(json.dumps(event_dict) + '\n')
            return True
        except Exception as e:
            print(f"Error writing event: {e}")
            return False

    def read_events(self) -> list:
        """Read all events from JSONL file."""
        events = []
        try:
            with open(self.output_path, 'r') as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line))
        except FileNotFoundError:
            pass
        return events
def build_event(
    store_id: str,
    camera_id: str,
    visitor_id: str,
    event_type: str,
    timestamp_dt: datetime,
    confidence: float,
    zone_id: Optional[str] = None,
    is_staff: bool = False,
    dwell_ms: int = 0,
    queue_depth: Optional[int] = None,
    sku_zone: Optional[str] = None,
    session_seq: Optional[int] = None,
    partial_occlusion: bool = False,
    run_id: Optional[str] = None,
    x: Optional[float] = None,
    y: Optional[float] = None,
) -> Event:
    """Build event object with coordinates."""
    if timestamp_dt.tzinfo is None:
        timestamp_dt = timestamp_dt.replace(tzinfo=timezone.utc)
    
    iso_timestamp = timestamp_dt.isoformat(timespec='seconds').replace('+00:00', 'Z')
    
    metadata = EventMetadata(
        queue_depth=queue_depth,
        sku_zone=sku_zone,
        session_seq=session_seq,
        partial_occlusion=partial_occlusion,
        x=x,
        y=y
    )
    
    event = Event(
        event_id=str(uuid.uuid4()),
        store_id=store_id,
        camera_id=camera_id,
        visitor_id=visitor_id,
        event_type=event_type,
        timestamp=iso_timestamp,
        zone_id=zone_id,
        dwell_ms=dwell_ms,
        is_staff=is_staff,
        confidence=confidence,
        metadata=metadata,
        run_id=run_id
    )
    
    return event

