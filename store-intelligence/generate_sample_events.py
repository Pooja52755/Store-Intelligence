#!/usr/bin/env python3
"""
DEPRECATED — do not use for evaluation submissions.

Generates synthetic random events (not from CCTV). Use the real pipeline instead:

  python run_pipeline.py --clips-dir "<CCTV folder>" --skip-copy
  python ingest_events.py --events-file ./events/events.jsonl

"""
import sys

if __name__ == "__main__":
    print(
        "ERROR: generate_sample_events.py produces synthetic data and is disabled.\n"
        "Run: python run_pipeline.py --clips-dir <path-to-CCTV> --skip-copy",
        file=sys.stderr,
    )
    sys.exit(1)

# --- legacy code below (unreachable when run as script) ---
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


def generate_sample_events(output_file="./events/events.jsonl", store_id="STORE_BLR_002", num_visitors=150):
    """Generate realistic visitor events for the store."""
    
    # Store zones with realistic visit patterns
    zones = {
        "entry": {"dwell_min": 5, "dwell_max": 15, "visits_pct": 100},
        "premium_skincare_zone": {"dwell_min": 120, "dwell_max": 600, "visits_pct": 85},
        "specialty_skincare": {"dwell_min": 60, "dwell_max": 300, "visits_pct": 60},
        "makeup_unit_center": {"dwell_min": 180, "dwell_max": 900, "visits_pct": 75},
        "beauty_counter": {"dwell_min": 300, "dwell_max": 1200, "visits_pct": 65},
        "maybelline_zone": {"dwell_min": 60, "dwell_max": 300, "visits_pct": 70},
        "faces_zone": {"dwell_min": 90, "dwell_max": 400, "visits_pct": 75},
        "lakme_zone": {"dwell_min": 75, "dwell_max": 350, "visits_pct": 70},
        "mens_care_zone": {"dwell_min": 45, "dwell_max": 200, "visits_pct": 35},
        "alps_loreal_zone": {"dwell_min": 60, "dwell_max": 250, "visits_pct": 60},
        "central_aisle": {"dwell_min": 10, "dwell_max": 30, "visits_pct": 90},
    }
    
    # Visitor journey patterns (typical shopping sequence)
    typical_journeys = [
        ["entry", "central_aisle", "premium_skincare_zone", "makeup_unit_center", "faces_zone", "beauty_counter"],
        ["entry", "central_aisle", "faces_zone", "lakme_zone", "beauty_counter"],
        ["entry", "central_aisle", "maybelline_zone", "faces_zone", "beauty_counter"],
        ["entry", "central_aisle", "specialty_skincare", "premium_skincare_zone", "makeup_unit_center", "beauty_counter"],
        ["entry", "central_aisle", "mens_care_zone", "alps_loreal_zone", "beauty_counter"],
        ["entry", "beauty_counter"],  # Quick checkout
    ]
    
    events = []
    base_time = datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc)  # April 10, 2026, 12:00
    
    for visitor_id in range(1, num_visitors + 1):
        # Choose a journey
        journey = random.choice(typical_journeys)
        
        # Generate entry time (spread across peak hours)
        entry_offset = random.randint(0, 8 * 3600)  # 8 hour peak window
        entry_time = base_time + timedelta(seconds=entry_offset)
        
        # Staff detection (20% chance someone is staff)
        is_staff = random.random() < 0.2
        
        current_time = entry_time
        
        for zone_idx, zone_id in enumerate(journey):
            zone_config = zones[zone_id]
            
            # Dwell time in zone
            dwell_ms = random.randint(
                zone_config["dwell_min"] * 1000,
                zone_config["dwell_max"] * 1000
            )
            
            # Multiple events per zone (every 5 seconds)
            events_in_zone = max(1, dwell_ms // 5000)
            
            for event_num in range(events_in_zone):
                event_time = current_time + timedelta(milliseconds=event_num * 5000)
                
                # Queue depth (realistic for checkout zones)
                queue_depth = 0
                if zone_id == "beauty_counter":
                    queue_depth = random.randint(0, 5)
                elif zone_id in ["faces_zone", "makeup_unit_center"]:
                    queue_depth = random.randint(0, 3)
                
                event = {
                    "event_id": f"{visitor_id}_{zone_idx}_{event_num}",
                    "store_id": store_id,
                    "camera_id": f"CAM{(visitor_id % 5) + 1}",
                    "visitor_id": f"V{visitor_id:06d}",
                    "event_type": "ZONE_ENTER" if event_num == 0 else "ZONE_PULSE",
                    "timestamp": event_time.isoformat(),
                    "zone_id": zone_id,
                    "dwell_ms": max(dwell_ms, 30000) if event_num == 0 else 5000,
                    "is_staff": is_staff,
                    "confidence": round(0.85 + random.random() * 0.15, 2),
                    "queue_depth": queue_depth,
                    "sku_zone": zone_id,
                    "session_seq": visitor_id * 100 + zone_idx,
                    "partial_occlusion": random.random() < 0.1
                }
                
                events.append(event)
            
            # Move to next zone after dwell time
            current_time += timedelta(milliseconds=dwell_ms)
        
        # Exit event
        events.append({
            "event_id": f"{visitor_id}_exit",
            "store_id": store_id,
            "camera_id": f"CAM{(visitor_id % 5) + 1}",
            "visitor_id": f"V{visitor_id:06d}",
            "event_type": "ZONE_EXIT",
            "timestamp": current_time.isoformat(),
            "zone_id": "entry",
            "dwell_ms": 5000,
            "is_staff": is_staff,
            "confidence": 0.95,
            "queue_depth": 0,
            "sku_zone": "entry",
            "session_seq": visitor_id * 100 + len(journey),
            "partial_occlusion": False
        })
    
    # Write events to JSONL
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        for event in events:
            f.write(json.dumps(event) + '\n')
    
    print(f"✓ Generated {len(events)} events for {num_visitors} visitors")
    print(f"✓ Events written to: {output_path}")
    print(f"\nEvent statistics:")
    print(f"  - Unique visitors: {num_visitors}")
    print(f"  - Total events: {len(events)}")
    print(f"  - Avg events per visitor: {len(events) // num_visitors}")
    print(f"  - Date: 2026-04-10 (April 10)")
    print(f"  - Store: {store_id}")
    
    # Show sample events
    print(f"\nSample events:")
    for event in events[:3]:
        print(f"  {event}")


if __name__ == "__main__":
    generate_sample_events(num_visitors=150)
