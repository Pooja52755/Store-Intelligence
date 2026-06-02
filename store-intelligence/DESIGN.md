# Store Intelligence - System Design & Architecture

This document details the production architecture, components, and data pipelines of the Store Intelligence system.

---

## 1. System Architecture Overview

The system is designed as a decoupled, real-time retail analytics platform composed of four core tiers:

```
                  +--------------------------+
                  |     React Dashboard      |
                  |       (Port 3000)        |
                  +-------------+------------+
                                | REST / WebSockets
                                v
                  +--------------------------+
                  |       FastAPI API        | <---+ ML Pipeline Run (JSONL Output)
                  |       (Port 8000)        |
                  +----+-----------------+---+
                       |                 |
                       | SQLAlchemy ORM  | Redis Cache
                       v                 v
           +-------------------+   +-----------+
           |    PostgreSQL     |   |   Redis   |
           |    (Port 5432)    |   | (Port 6379|
           +-------------------+   +-----------+
```

1. **ML Detection Pipeline**: Headless batch frame analyzer using YOLOv8 + ByteTrack object tracking + custom Re-ID embedders. Processes raw `.mp4` video footage and generates structured JSONL event lines containing exact timestamps and confidence maps.
2. **FastAPI Backend (API)**: Asynchronous REST endpoint framework acting as the ingestion and query controller. Integrates with PostgreSQL via `SQLAlchemy` (asyncpg) and Redis for sub-millisecond hot-path caching.
3. **Storage Tier**:
   - **PostgreSQL**: Timezone-aware relational store containing strict indexes for events and sessions. Houses the single source of truth for all historical runs and customer events.
   - **Redis Cache**: Holds atomic counters for active daily visitors, real-time checkout queue sizes, and acts as the pub/sub engine for real-time WebSocket clients.
4. **React Dashboard**: Premium glassmorphic analytics interface. Queries the metrics, heatmaps, and funnel APIs, and streams live video analysis logs via real-time WebSocket connections.

---

## 2. Component Interactions & Data Flow

### A. Video Analysis & Event Ingestion Flow
1. The dashboard uploads a `.mp4` video file via the `POST /upload-video` endpoint.
2. The FastAPI controller creates a new unique `run_id`, saves the video to disk, and triggers `pipeline/detect.py` as an asynchronous background subprocess.
3. The YOLOv8 pipeline processes the video (using a CPU-friendly frame stride of 5), maps coordinates against `store_layout.json` zones, and appends validated `Event` structures into a localized JSONL file tagged with the `run_id`.
4. Upon pipeline completion, the events are read in batches and POSTed to `/events/ingest`.
5. The ingestion service performs database deduplication (`ON CONFLICT DO NOTHING`) and populates the PostgreSQL tables.

### B. Analytical Query Flow
1. When a user requests metrics for a specific `run_id` (via `/stores/{store_id}/metrics?run_id=...`), `MetricsService` fetches all events for that run from PostgreSQL.
2. The `build_sessions_from_events` engine parses individual customer actions, aggregates entry-to-exit zones, and compiles non-overlapping `VisitorSession` sequences.
3. Retail formulas are applied to compute unique visitors, drop-off rates, conversion rates, and zone dwell durations.

---

## 3. PostgreSQL Database Schema Design

The relational schema is highly indexed on critical query keys (`store_id`, `run_id`, `visitor_id`, `timestamp`) to ensure sub-second response times even for datasets containing millions of coordinates.

### `events` Table
| Column Name | Data Type | Nullable | Index | Description |
|---|---|---|---|---|
| `event_id` | `UUID` | No | Primary Key | Unique event identifier (UUID v4) |
| `store_id` | `VARCHAR(50)` | No | Yes | Associated store identifier |
| `camera_id` | `VARCHAR(50)` | No | No | Camera that recorded the event |
| `visitor_id` | `VARCHAR(50)` | No | Yes | Re-identified visitor ID (`VIS_` prefix) |
| `event_type` | `VARCHAR(50)` | No | Yes | e.g. `ENTRY`, `ZONE_ENTER`, `EXIT`, `ZONE_DWELL` |
| `timestamp` | `TIMESTAMPTZ` | No | Yes | Timezone-aware ISO-8601 timestamp |
| `zone_id` | `VARCHAR(100)` | Yes | Yes | Floor layout zone identifier |
| `dwell_ms` | `INTEGER` | No | No | Dwell duration in milliseconds |
| `is_staff` | `BOOLEAN` | No | Yes | Suppresses staff/employee movements |
| `confidence` | `DOUBLE PRECISION`| No | No | YOLOv8 tracking confidence score |
| `run_id` | `VARCHAR(50)` | Yes | Yes | Associated pipeline run identifier |

### `sessions` Table
| Column Name | Data Type | Nullable | Index | Description |
|---|---|---|---|---|
| `session_id` | `UUID` | No | Primary Key | Unique session identifier |
| `store_id` | `VARCHAR(50)` | No | Yes | Associated store identifier |
| `visitor_id` | `VARCHAR(50)` | No | Yes | Re-identified visitor ID |
| `started_at` | `TIMESTAMPTZ` | No | Yes | Session opening timestamp |
| `ended_at` | `TIMESTAMPTZ` | Yes | No | Session closing timestamp |
| `converted` | `BOOLEAN` | No | Yes | Flags whether session ended in checkout |
| `is_reentry` | `BOOLEAN` | No | No | Flags if customer returned during day |

---

## 4. State Estimation & Analytics Logic

### A. Session Reconstruction
To prevent visitor double-counting and preserve correct funnel counts:
- `ENTRY` or `REENTRY` starts a new session.
- Sub-event tracks (entering skincare, cosmetics, cashier queue) are grouped dynamically under the open session.
- An `EXIT` event (or sustained absence > 15 seconds) closes the active session and computes overall store dwell time.

### B. Conversion Funnel Stages
The funnel follows a strict monotonic drop-off logic to map clean conversion rates:
1. **Unique Visitors**: Unique customer IDs with at least one `ENTRY` event.
2. **Zone Visits**: Sessions that successfully traversed at least one product zone (e.g. `beauty_counter`).
3. **Queue Joined**: Sessions that registered a `BILLING_QUEUE_JOIN` event.
4. **Purchased (Converted)**: Sessions that completed a checkout (i.e. joined queue and exited without abandoning, or matched against POS Transaction within 5 minutes before invoice).

---

## 5. Advanced Challenge Features Implementation

### A. POS Transaction Correlation
- **Data Source**: Loaded automatically from the challenge-specific `pos_transactions.csv` at `events/pos_transactions.csv`.
- **Match Criteria**: A session is marked `converted=True` if the shopper was present in a billing zone (e.g., `cash_counter` or `beauty_counter`) within **5 minutes** (300 seconds) before a recorded transaction's timestamp.
- **Conversion Rate**: Calculated strictly as $\frac{\text{Converted Sessions}}{\text{Unique Visitor Sessions}}$ to ensure perfect business correlation.

### B. Heuristic Staff Classifier
- Automatically flags visitors as **is_staff=True** if they meet the following operational patterns:
  - Exceedingly long duration in store (e.g., $> 15$ minutes / $900,000$ milliseconds).
  - Traversal of an excessive number of zones ($> 8$ distinct zones), signifying routine stocking, auditing, or checkout assistance.
- Staff sessions are filtered out completely from unique visitors, conversion rate, funnel, heatmaps, and zone dwell durations.

### C. Re-entry Detection
- Tracks exits followed by entries of the same ReID identity.
- Deduplicates and merges visits happening within a 60-second cooldown window to prevent double-counting of entries in metrics and funnel stages.

### D. Mirror & Reflection Mitigation
- Suppression system integrated within the appearance matching phase. Adjacent or geometrically symmetric detections with a cosine similarity matching $> 0.65$ within active visitor frames are merged into the parent track. This completely suppresses reflective duplications.

### E. Confidence Calibration
- Surfaced all raw YOLO and Re-ID confidence scores in API response blocks, including dynamic `data_confidence` ratings (`HIGH`, `MEDIUM`, `LOW`) for heatmaps with low sample-sizes.

---

## 6. AI-Assisted Decisions

This section documents explicit engineering trade-offs regarding design paths suggested by AI vs. those built for the Purplle Retail analytics deployment.

### A. DeepSORT vs. ByteTrack for Shopper Tracking
- **What AI Suggested**: Implement DeepSORT utilizing a heavy convolutional feature extractor on every frame to maintain track IDs across multi-camera overlaps.
- **What was Accepted**: Bypassed native DeepSORT feature extractors inside containerized pipelines. Adopted **ByteTrack** for high-frame bounding box matching.
- **What was Rejected**: High CPU-overhead Re-ID tracking on every frame.
- **Why**: Running deep neural networks on CPU on every frame causes significant lag (under 1 FPS). ByteTrack is extremely lightweight, running standard Kalman-filter matching at 60+ FPS on CPU, while Re-ID embeddings are extracted selectively.

### B. Graph Database (Neo4j) Integration
- **What AI Suggested**: Save and query every single visitor's pathway node transition directly in Neo4j to compile store journey graphs.
- **What was Accepted**: A clean PostgreSQL timezone-aware relational event model index-optimized for query metrics.
- **What was Rejected**: Packaged active Neo4j container stack on start.
- **Why**: Neo4j cold-start boot delays API startup, occasionally causing resource starvation on Windows host environments. PostgreSQL satisfies the query metrics effortlessly with sub-second response times.

### C. Large Vision-Language Models (VLM) for Staff Classification
- **What AI Suggested**: Prompt a VLM to classify whether shoppers are staff members based on frame uniform appearance.
- **What was Accepted**: A deterministic HSV color-histogram torso torso-region analysis combined with behavioral long-duration presence.
- **What was Rejected**: Asynchronous VLM visual inference calls.
- **Why**: VLMs cannot be run locally on low-cost CPUs without significant inference delay (10-30 seconds per frame). Torso color histograms compile in microseconds and provide 100% reproducible staff classifications.
