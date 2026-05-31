# Store Intelligence System

End-to-end retail analytics platform: **Detection Pipeline → JSON Event Stream → FastAPI Intelligence API → Live Dashboard**

## 📋 Quick Start (5 Commands)

```bash
# 1. Clone and setup
git clone <repo>
cd store-intelligence

# 2. Start all services (database, API, dashboard)
docker compose up -d

# 3. Run detection pipeline on video clips
bash pipeline/run.sh /path/to/clips store_layout.json

# 4. Stream events to API
curl -X POST http://localhost:8000/events/ingest \
  -H "Content-Type: application/json" \
  -d @events/events.jsonl

# 5. View dashboard
# Dashboard live at: http://localhost:3000
# API docs at:      http://localhost:8000/docs
```

## 🏗️ Architecture

### Detection Pipeline
Raw CCTV video → YOLOv8 person detection → ByteTrack multi-object tracking → OSNet Re-ID embeddings → Event emission

- **Input**: 5 stores × 3 cameras × 20-min clips (15 video files, 1080p, 15fps)
- **Output**: JSONL event stream (one JSON per line)
- **Events**: All 8 required types (ENTRY, EXIT, ZONE_ENTER, ZONE_EXIT, ZONE_DWELL, BILLING_QUEUE_JOIN, BILLING_QUEUE_ABANDON, REENTRY)

### API Layer (FastAPI + PostgreSQL + Redis + Neo4j)
- **POST /events/ingest** - Batch ingest with deduplication (up to 500 events)
- **GET /stores/{id}/metrics** - Real-time store metrics (visitors, conversion, dwell by zone)
- **GET /stores/{id}/funnel** - Conversion funnel analysis (Entry → Zone → Billing → Purchase)
- **GET /stores/{id}/heatmap** - Zone visit frequency + dwell heatmap with confidence levels
- **GET /stores/{id}/anomalies** - Active anomaly detection (queue spike, conversion drop, dead zone, stale feed)
- **GET /health** - System health check (database, cache, graph connectivity)
- **WS /ws/{store_id}** - WebSocket for live metric streaming

### Knowledge Graph (Neo4j)
- **Visitor journey paths** - Most common sequences of zone visits
- **Cross-camera deduplication** - Graph edges model camera field-of-view overlaps
- **Dead zone detection** - Zones with no recent traffic

### RL Anomaly Tuner (Gymnasium + Stable-Baselines3)
- Dynamic threshold learning for queue spike detection
- Train offline on historical data, deploy to production
- State space: queue depth, conversion rate, time of day, visitor count

### Live Dashboard (React + WebSocket + Recharts)
- Real-time visitor count, conversion rate, queue depth
- Zone heatmap grid visualization
- Updates every 30 seconds from API

## 📁 Project Structure

```
store-intelligence/
├── pipeline/                 # Detection pipeline
│   ├── detect.py            # Main YOLOv8 + ByteTrack orchestrator
│   ├── tracker.py           # Re-ID with OSNet embeddings
│   ├── staff_classifier.py  # HSV histogram staff detection
│   ├── tripwire.py          # Entry/exit tripwire logic
│   ├── emit.py              # Event schema + JSONL writer
│   └── run.sh               # One-command pipeline execution
│
├── app/                      # FastAPI intelligence API
│   ├── main.py              # FastAPI app, routers, WebSocket
│   ├── models.py            # Pydantic event schema
│   ├── db.py                # SQLAlchemy async setup
│   ├── ingestion.py         # POST /events/ingest
│   ├── metrics.py           # GET /stores/{id}/metrics
│   ├── funnel.py            # GET /stores/{id}/funnel
│   ├── heatmap.py           # GET /stores/{id}/heatmap
│   ├── anomalies.py         # GET /stores/{id}/anomalies
│   ├── health.py            # GET /health
│   ├── graph.py             # Neo4j queries
│   └── rl_tuner.py          # RL threshold tuning
│
├── dashboard/               # React live dashboard
│   ├── src/App.jsx
│   ├── src/Heatmap.jsx      # Zone heatmap component
│   └── package.json
│
├── tests/                   # Pytest test suite
│   ├── test_ingestion.py    # PROMPT block required
│   ├── test_metrics.py      # PROMPT block required
│   ├── test_anomalies.py    # PROMPT block required
│   └── test_pipeline.py     # PROMPT block required
│
├── docs/
│   ├── DESIGN.md            # Architecture + AI decisions
│   └── CHOICES.md           # 3 key technical decisions
│
├── docker-compose.yml       # Services: api, db, cache, graph, dashboard
├── requirements.txt         # Python dependencies
├── .env.example              # Environment variables
└── README.md                # This file
```

## 🚀 Running Tests

```bash
# All tests with coverage report
docker compose exec api pytest tests/ --cov=app --cov-report=term-missing

# Specific test file
docker compose exec api pytest tests/test_metrics.py -v

# Run with live database
# (Services must be running: docker compose up -d)
```

## 🔧 Configuration

### Environment Variables (.env)
```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/storedb
REDIS_URL=redis://cache:6379
NEO4J_URI=bolt://graph:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

STORE_ID=STORE_BLR_002
LOG_LEVEL=INFO
```

### Store Layout (store_layout.json)
```json
{
  "zones": {
    "SKINCARE": {"bounds": [x1, y1, x2, y2]},
    "BILLING": {"bounds": [x1, y1, x2, y2]}
  },
  "tripwire_line": {"x1": 0, "y1": 540, "x2": 1920, "y2": 540},
  "store_hours": {"open": "09:00", "close": "21:00"}
}
```

## 📊 Data Schema

### Event Output (Exact Match Required)
```json
{
  "event_id": "uuid-v4",
  "store_id": "STORE_BLR_002",
  "camera_id": "CAM_ENTRY_01",
  "visitor_id": "VIS_c8a2f1",
  "event_type": "ZONE_DWELL",
  "timestamp": "2026-03-03T14:22:10Z",
  "zone_id": "SKINCARE",
  "dwell_ms": 8400,
  "is_staff": false,
  "confidence": 0.91,
  "metadata": {
    "queue_depth": null,
    "sku_zone": "MOISTURISER",
    "session_seq": 5,
    "partial_occlusion": false
  }
}
```

## 🎯 Edge Cases Handled

1. **GROUP ENTRY**: Multiple people entering simultaneously emit N individual ENTRY events (NMS iou=0.5, conf=0.4)
2. **STAFF EXCLUSION**: Staff detected by HSV histogram, marked is_staff=true, filtered from metrics
3. **RE-ENTRY**: Same visitor re-entering after EXIT emits REENTRY (cosine similarity > 0.75)
4. **PARTIAL OCCLUSION**: Low-confidence detections never dropped, emitted with actual confidence + partial_occlusion flag
5. **QUEUE BUILDUP**: Queue depth tracked as integer, BILLING_QUEUE_JOIN includes queue_depth in metadata
6. **EMPTY STORE**: Zero-visitor periods return 0s not nulls, no 500 errors
7. **CAMERA OVERLAP**: Cross-camera dedup via Re-ID embeddings + 30s time window + Neo4j graph edges

## 🔗 Tech Stack (All AGPL-3.0 / MIT / Free)

| Component | Tool | Version | License |
|-----------|------|---------|---------|
| Detection | YOLOv8 + ByteTrack | 8.x | AGPL-3.0 |
| Re-ID | torchreid OSNet | latest | MIT |
| Tracking | Ultralytics | 8.x | AGPL-3.0 |
| API | FastAPI | 0.111+ | MIT |
| Database | PostgreSQL | 15 | Free |
| Cache | Redis | 7 | Free |
| Graph | Neo4j Community | 5 | Free |
| RL Training | Gymnasium + SB3 | latest | MIT |
| Dashboard | React + Recharts | 18 | MIT |

## 📈 Performance

- **Detection**: YOLOv8n processes ~30 fps on CPU, ~100 fps on GPU (1080p)
- **API**: Handles 500 events/batch, sub-100ms per endpoint (PostgreSQL indexed queries)
- **Re-ID**: 128-dim OSNet embeddings, cosine similarity matching in ~1ms per visitor
- **Anomalies**: RL threshold lookup is O(1), detection queries run in <100ms

## ✅ Quality Assurance

- **Test Coverage**: >70% (pytest + pytest-cov)
- **Linting**: Validated event schema (Pydantic)
- **Database**: ACID transactions, migrations via SQLAlchemy
- **Logging**: Structured JSON logs with trace_id, latency_ms per request
- **Error Handling**: All exceptions caught, 503 responses with structured error bodies (no raw stack traces)

## 🚨 Critical Rules

✅ **NEVER** return null from endpoints → always 0 or empty list  
✅ **NEVER** expose raw stack traces → structured 503 errors  
✅ **NEVER** suppress low-confidence events → emit with actual confidence  
✅ **NEVER** double-count re-entrants in funnel → one session per visitor  
✅ **ALWAYS** deduplicate by event_id → INSERT ... ON CONFLICT DO NOTHING  
✅ **ALWAYS** filter is_staff=true from customer metrics  
✅ **ALWAYS** validate events vs Pydantic schema before JSONL write  
✅ **ALWAYS** use UTC ISO-8601 timestamps  
✅ **ALWAYS** handle empty-store queries gracefully  

## 🤝 Contributing

1. Keep PROMPT blocks in all test files
2. Validate all events against exact schema before writing
3. Filter is_staff=true from customer metrics (store but don't count)
4. Return structured 503 errors on database failure (never 500)
5. Run tests before pushing: `pytest tests/ --cov=app`

## 📞 Support

- API docs: `http://localhost:8000/docs` (auto-generated OpenAPI)
- Neo4j browser: `http://localhost:7474`
- Redis CLI: `docker compose exec cache redis-cli`
- PostgreSQL: `docker compose exec db psql -U postgres storedb`

---

**Building retail intelligence one event at a time.** 🛍️📊
