import json
from pathlib import Path

uploads_dir = Path("uploads/STORE_BLR_002")
if uploads_dir.exists():
    for run_dir in uploads_dir.iterdir():
        if run_dir.is_dir():
            print(f"Run ID: {run_dir.name}")
            metadata_file = run_dir / "run_metadata.json"
            if metadata_file.exists():
                try:
                    metadata = json.loads(metadata_file.read_text())
                    print(f"  Status: {metadata.get('status')}")
                    print(f"  Total Events: {metadata.get('total_events')}")
                    print(f"  Error: {metadata.get('error')}")
                except Exception as e:
                    print(f"  Error reading metadata: {e}")
            else:
                print("  No run_metadata.json found!")
            
            events_file = run_dir / "events.jsonl"
            if events_file.exists():
                print(f"  events.jsonl exists. Size: {events_file.stat().st_size} bytes")
            else:
                print("  No events.jsonl found!")
else:
    print("uploads/STORE_BLR_002 does not exist")
