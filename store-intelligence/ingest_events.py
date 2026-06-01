#!/usr/bin/env python3
"""
Ingest events from generated JSONL files into the API.
Usage: python ingest_events.py --events-file ./events/events.jsonl
"""
import json
import argparse
import httpx
import asyncio
from pathlib import Path
from typing import List, Dict, Any


async def ingest_events(events_file: str, api_url: str = "http://localhost:8000", batch_size: int = 500, run_id: str = None):
    """Ingest events from JSONL file into the API."""
    
    events_path = Path(events_file)
    if not events_path.exists():
        print(f"Error: Events file not found: {events_file}")
        return False
    
    # Read events
    events = []
    with open(events_path, 'r') as f:
        for line in f:
            if line.strip():
                raw_event = json.loads(line)
                # Reformat event to match API schema
                formatted_event = {
                    "event_id": raw_event.get("event_id"),
                    "store_id": raw_event.get("store_id"),
                    "camera_id": raw_event.get("camera_id"),
                    "visitor_id": raw_event.get("visitor_id"),
                    "event_type": raw_event.get("event_type"),
                    "timestamp": raw_event.get("timestamp"),
                    "zone_id": raw_event.get("zone_id"),
                    "dwell_ms": raw_event.get("dwell_ms", 0),
                    "is_staff": raw_event.get("is_staff", False),
                    "confidence": raw_event.get("confidence", 0.9),
                    "metadata": {
                        "queue_depth": raw_event.get("queue_depth"),
                        "sku_zone": raw_event.get("sku_zone"),
                        "session_seq": raw_event.get("session_seq"),
                        "partial_occlusion": raw_event.get("partial_occlusion", False)
                    },
                    "run_id": run_id or raw_event.get("run_id")
                }
                events.append(formatted_event)
    
    if not events:
        print("No events to ingest")
        return True
    
    print(f"Read {len(events)} events from {events_file}")
    
    # Ingest in batches
    total_accepted = 0
    total_rejected = 0
    
    async with httpx.AsyncClient(timeout=60) as client:
        for batch_start in range(0, len(events), batch_size):
            batch_end = min(batch_start + batch_size, len(events))
            batch = events[batch_start:batch_end]
            
            print(f"\nIngesting batch {batch_start//batch_size + 1} ({len(batch)} events)...")
            
            try:
                response = await client.post(
                    f"{api_url}/events/ingest",
                    json={"events": batch},
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code in [200, 201]:
                    result = response.json()
                    accepted = result.get('accepted', 0)
                    rejected = result.get('rejected', 0)
                    total_accepted += accepted
                    total_rejected += rejected
                    print(f"  [OK] Accepted: {accepted}, Rejected: {rejected}")
                else:
                    print(f"  [FAILED] {response.status_code}")
                    print(f"  Response: {response.text[:200]}")
                    return False
                    
            except Exception as e:
                print(f"  [ERROR] {e}")
                return False
    
    print(f"\n[SUCCESS] All events ingested successfully")
    print(f"  Total Accepted: {total_accepted}")
    print(f"  Total Rejected: {total_rejected}")
    return True


def main():
    parser = argparse.ArgumentParser(description='Ingest events into the API')
    parser.add_argument(
        '--events-file',
        default='./events/events.jsonl',
        help='Path to JSONL events file (default: ./events/events.jsonl)'
    )
    parser.add_argument(
        '--run-id',
        default=None,
        help='Optional run_id to tag the ingested events with'
    )
    parser.add_argument(
        '--api-url',
        default='http://localhost:8000',
        help='API base URL (default: http://localhost:8000)'
    )
    
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("INGESTING EVENTS INTO STORE INTELLIGENCE")
    print("="*60)
    print(f"Events file: {args.events_file}")
    print(f"API URL: {args.api_url}")
    if args.run_id:
        print(f"Run ID: {args.run_id}")
    
    success = asyncio.run(ingest_events(args.events_file, args.api_url, run_id=args.run_id))
    
    if success:
        print("\n" + "="*60)
        print("[OK] INGESTION COMPLETE")
        print("="*60)
        print("\nView dashboard at: http://localhost:3000")
        return 0
    else:
        print("\n[FAILED] Ingestion failed")
        return 1


if __name__ == '__main__':
    exit(main())
