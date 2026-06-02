import json
from pathlib import Path

print("Searching runs metadata:")
for p in Path('events/STORE_BLR_002').iterdir():
    meta = p / 'run_metadata.json'
    if meta.exists():
        try:
            data = json.loads(meta.read_text(encoding='utf-8'))
            print(f"Run: {p.name} | Video: {data.get('uploaded_file')} | Status: {data.get('status')} | Created: {data.get('created_at')}")
        except Exception as e:
            print(f"Error reading {meta}: {e}")
