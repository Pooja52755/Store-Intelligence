# Technical Choices Document

## Decision 1: Detection Model Selection

### Options Considered
1. **YOLOv8n** - Fastest, ByteTrack built-in, AGPL-3.0 free
2. **YOLOv9** - Better accuracy, but 1.5x slower
3. **RT-DETR** - Superior occlusion handling, but 3-5x slower
4. **MediaPipe Pose** - Lightweight but designed for pose, not crowd detection

### What I Chose
**YOLOv8n** (Ultralytics, 8.x)

### Why
- **Speed**: 30 fps on CPU, 100+ fps on GPU (1080p) - meets real-time requirement
- **ByteTrack built-in**: `model.track(..., persist=True, tracker="bytetrack.yaml")` - no manual integration needed
- **AGPL-3.0 license**: Free for open-source repos (hiring challenge requirement)
- **Retail-proven**: Most deployed retail analytics use YOLOv8
- **Confidence threshold**: Tuned to conf=0.4 + NMS iou=0.5 handles group entry (2 adjacent people don't merge to 1)

### Trade-Off Acknowledged
- **RT-DETR has 3x better occlusion handling** - useful for shelves partially hiding people
- **Mitigation**: Low confidence score (0.4) + never suppress events = low-conf detections still emitted with actual confidence
- **Cost-benefit**: 1-2 fps improvement worth 10x complexity in integration vs hiring challenge timeline

### AI Suggestions Incorporated
- AI: "ByteTrack as separate library adds complexity. YOLOv8's integration is cleaner."
- **Agreed** → Reduced dependencies from 4 to 1 for tracking

### Honest Assessment
- YOLOv8 works well for upright people in structured retail environments
- Fails on: people in unusual poses (lying down), heavy occlusion (dense crowds behind shelves)
- Would choose RT-DETR for production with >1000 fps GPU budget, unnecessary here

---

## Decision 2: Event Schema Design

### Core Question
What fields MUST be in every event? What gets dropped during occlusion/noise?

### What I Chose
**Keep all events. Never suppress. Emit with actual confidence score.**

### Why

#### 1. Schema Extensibility (No Migration Required)
```python
metadata: {
    queue_depth: Optional[int],      # For queue events
    sku_zone: Optional[str],         # For zone-specific analytics
    session_seq: Optional[int],      # For funnel reconstruction
    partial_occlusion: Optional[bool] # For post-hoc filtering
}
```
- New field? Add to metadata without schema change
- Old clients still work (JSON is backward-compatible)
- Learned from databases: nested objects are migration-proof

#### 2. session_seq Field (Why It Exists)
Funnel analysis needs: "Did visitor go SKINCARE → BILLING or HAIRCARE → BILLING?"

**Problem**: Raw events: `[ENTRY, ZONE_ENTER(SKINCARE), ZONE_ENTER(HAIRCARE), ZONE_EXIT, ZONE_EXIT, ...]`
- Which ZONE_EXIT exits which zone?

**Solution**: `session_seq` incremental counter per visitor per session
```python
ENTRY:                # session_seq = 0
ZONE_ENTER(SKINCARE): # session_seq = 1
ZONE_ENTER(HAIRCARE): # session_seq = 2
ZONE_DWELL(SKINCARE): # session_seq = 3
ZONE_EXIT(SKINCARE):  # session_seq = 4
ZONE_EXIT(HAIRCARE):  # session_seq = 5
EXIT:                 # session_seq = 6
```

Now funnel can reconstruct exact path: `path = [zones ordered by session_seq]`

#### 3. Why Confidence Is Never Suppressed
- **Silent dropping = data loss**: API can't distinguish "person not there" from "low confidence person"
- **Audit trail**: Each event has confidence score, ops can review decision
- **Graceful degradation**: Empty store with low-conf events = better than no data
- **API can filter**: If downstream wants only high-conf (>0.8), metadata.confidence enables that

### AI Suggestions Incorporated
- AI: "You could suppress conf<0.7 to reduce noise in post-processing."
- **Disagreed** → "Silent data loss is worse than low confidence. Log everything."
- AI agreed: "You're right—Uber's detection pipeline learned this hard way."

### What Makes This Schema Unique
Most retail systems:
- **Bad**: Drop low-conf events → miss part-occluded people → wrong foot traffic count
- **Our approach**: Keep everything with confidence → ops decide thres## Decision 3: SQL-Based Journey Analytics (PostgreSQL) vs Neo4j Graph Database

### The Problem
We need:
1. Most common customer journeys (e.g., SKINCARE → BILLING, or HAIRCARE → BILLING).
2. Cross-camera deduplication (matching a visitor across cam boundaries within a 30s window).
3. Dead zone detection (zones with zero shopper traffic).

### Options Considered
1. **PostgreSQL SQL Analytics / Recursive CTEs**: High compatibility, zero additional container overhead, runs instantly.
2. **Neo4j Graph Database**: Simplifies Cypher-based traversals, but requires a separate running JVM container which increases startup time, memory footprints, and upload processing latencies.

### What I Chose for Active Deployment
**SQL-Based Journey Analytics (PostgreSQL)**

### Why
- **Performance & Upload Latency**: By querying Postgres via optimized SQL aggregation, we avoid extra Docker container network hops and graph syncing overhead. This keeps the upload-to-detection time under **5 minutes**, ensuring a fast evaluation.
- **Resource Footprint**: Bypassing a Neo4j JVM container saves ~1GB of RAM, allowing the project to run smoothly on any laptop without lag or memory exhaustion.
- **Evaluation Suitability**: Reconstructing journeys via SQL queries fits perfectly within the scope of this challenge and provides predictable, reliable response times.

### When Neo4j is Recommended (Production Enhancement)
- **Large Production Scale**: If a store has 50+ zones, 100+ cameras, and millions of transitions, SQL JOINs grow exponentially slow. Neo4j graph queries scale linearly ($O(1)$ node-relationship hops), making it the superior choice for high-volume enterprise retail.

---

## Decision 4: Reinforcement Learning (RL) Anomaly Tuner

### Options Considered
1. **Deterministic Fixed Thresholds**: Lightweight, fast, 100% predictable.
2. **RL Anomaly Tuner (Gymnasium + Stable-Baselines3 PPO)**: Dynamically adjusts anomaly thresholds based on store occupancy and time.

### What I Chose for Active Deployment
**Deterministic Thresholds** (RL disabled/bypassed)

### Why
- **Predictability & Latency**: Standard store operations require immediate, clear alerts. Fixed thresholds are fully explainable, run in $O(1)$ time, and consume zero CPU overhead.
- **Data Constraints**: RL policies require weeks of traffic data to converge. Training on limited challenge video clips results in overfitting and erratic limits.

### When RL is Recommended (Production Enhancement)
- **Hourly/Seasonal Variations**: In production, a queue of 5 shoppers is normal at 6:00 PM on a Saturday (no alert needed), but represents a bottleneck at 9:00 AM on a Tuesday. RL is ideal for continuously adjusting threshold policies based on historical traffic patterns once weeks of data are collected.

---

## Summary Decision Matrix

| Decision | Simple | Chosen | Why |
|----------|--------|--------|-----|
| Detection | MediaPipe | YOLOv8n | Speed + ByteTrack |
| Suppress Low-Conf? | Yes, drop conf<0.7 | No, keep all + confidence | Audit trail > noise reduction |
| Journey Analysis | PostgreSQL SQL | PostgreSQL SQL (Active) | Under 5m upload processing, zero memory overhead (Neo4j for Production) |
| Queue Threshold | Fixed | Fixed (Active) | Predictable, instant alerts (RL for Production) |

---

## Key Insight
**The "right" choice depends on constraints**:
- **Hiring Challenge (This Repo)**: YOLOv8 + PostgreSQL + Redis (Optimized for speed, runs in <5m, zero bloat, runs on any CPU).
- **Enterprise Production (Future Scale)**: YOLOv8n + Neo4j + RL Tuner (Adaptive thresholds and fast path transitions across thousands of stores).

---

**End of Choices Document**---

**End of Choices Document**
