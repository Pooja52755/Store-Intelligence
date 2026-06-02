import json
from collections import defaultdict

run_id = "f3cfba03-5948-41d4-a818-64936262775a"
events_file = f"events/STORE_BLR_002/{run_id}/events.jsonl"

stats = defaultdict(lambda: {'total': 0, 'event_types': defaultdict(int), 'zones': defaultdict(int), 'is_staff_votes': []})

with open(events_file, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        v_id = data['visitor_id']
        stats[v_id]['total'] += 1
        stats[v_id]['event_types'][data['event_type']] += 1
        stats[v_id]['zones'][data.get('zone_id')] += 1
        stats[v_id]['is_staff_votes'].append(data.get('is_staff'))

print(f"Analysis of events for CAM 3 run {run_id}:")
for v_id, s in stats.items():
    is_staff_ratio = sum(1 for v in s['is_staff_votes'] if v) / len(s['is_staff_votes'])
    print(f"\nVisitor: {v_id} | Total Events: {s['total']} | Staff Ratio: {is_staff_ratio:.2f}")
    print("  Event types:")
    for et, count in s['event_types'].items():
        print(f"    {et}: {count}")
    print("  Zones:")
    for z, count in s['zones'].items():
        print(f"    {z}: {count}")
