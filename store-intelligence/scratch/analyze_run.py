import json
from collections import defaultdict

stats = defaultdict(lambda: {'total': 0, 'hsv': 0, 'is_staff_last': None, 'is_staff_first': None})
events_file = 'events/STORE_BLR_002/5dfb6818-c85e-4541-9be9-f8815ab80b00/events.jsonl'

with open(events_file, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        v_id = data['visitor_id']
        stats[v_id]['total'] += 1
        # Check if this specific event has is_staff = True
        if data.get('is_staff'):
            stats[v_id]['hsv'] += 1
        if stats[v_id]['is_staff_first'] is None:
            stats[v_id]['is_staff_first'] = data.get('is_staff')
        stats[v_id]['is_staff_last'] = data.get('is_staff')

print("Summary of events in run 5dfb6818:")
for v_id, s in stats.items():
    print(f"Visitor: {v_id} | Total Events: {s['total']} | Events with is_staff=True: {s['hsv']} | First event is_staff: {s['is_staff_first']} | Last event is_staff: {s['is_staff_last']}")
