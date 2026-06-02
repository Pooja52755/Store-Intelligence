import json
from collections import defaultdict

events_file = 'events/STORE_BLR_002/5dfb6818-c85e-4541-9be9-f8815ab80b00/events.jsonl'

unique_visitors = set()
event_types = defaultdict(int)
zone_visits = defaultdict(int)
timestamps = set()

# Since we don't have track_id in events.jsonl directly, let's look at the events structure.
with open(events_file, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        unique_visitors.add(data['visitor_id'])
        event_types[data['event_type']] += 1
        zone_visits[data['zone_id']] += 1
        timestamps.add(data['timestamp'])

print(f"Total events: {sum(event_types.values())}")
print(f"Unique visitors: {list(unique_visitors)}")
print("\nEvent types distribution:")
for k, v in sorted(event_types.items(), key=lambda x: x[1], reverse=True):
    print(f"  {k}: {v}")

print("\nZone visits distribution:")
for k, v in sorted(zone_visits.items(), key=lambda x: x[1], reverse=True):
    print(f"  {k}: {v}")

print(f"\nUnique timestamps count: {len(timestamps)}")
sorted_ts = sorted(list(timestamps))
if sorted_ts:
    print(f"Time range: {sorted_ts[0]} to {sorted_ts[-1]}")
