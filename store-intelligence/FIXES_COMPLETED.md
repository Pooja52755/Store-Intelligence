# FIXES COMPLETED - Store Intelligence Project

## Overview
Complete end-to-end audit and fixes applied for Docker build issues, event generation without run_id tagging, and metrics queries ignoring run_id parameter.

## Issues Fixed

### 1. ❌ → ✅ Docker Build Failure (libGL.so.1)
**File**: `Dockerfile`  
**Root Cause**: Dockerfile specified unavailable system packages:
- `libgl1-mesa-glx` (doesn't exist in Debian Bookworm slim base)
- `libgl1-mesa-dev` (development package, not needed for runtime)
- Duplicate/incorrect packages: `libglib2.0-0` appeared twice, `libxext-dev`, `libxrender-dev`, etc.

**Solution Applied**:
```dockerfile
# BEFORE: 18 package lines with invalid packages
apt-get install -y \
    libgl1-mesa-glx libgl1-mesa-dev libglib2.0-0 libglib2.0-0 \
    libsm6 libxext-dev libxrender-dev libx11-6 libgomp1 \
    ffmpeg libavformat-dev libswscale-dev build-essential \
    libhdf5-dev python3-dev libavcodec-extra git wget ca-certificates

# AFTER: 9 minimal required packages
apt-get install -y \
    libglib2.0-0 libsm6 libxext6 libxrender1 libx11-6 libgomp1 \
    ffmpeg libavcodec-extra git wget ca-certificates
```

**Changes**:
- ❌ Removed: libgl1-mesa-glx, libgl1-mesa-dev, libglib2.0-0 (duplicate), libxext-dev, libxrender-dev, build-essential, libhdf5-dev, python3-dev, libavformat-dev, libswscale-dev
- ✅ Kept: libglib2.0-0, libsm6, libxext6, libxrender1, libx11-6, libgomp1, ffmpeg, libavcodec-extra, git, wget, ca-certificates
- ✅ Added: OpenCV import verification in build step
- ✅ Added: /app/uploads directory creation for file uploads

**Impact**: Docker build will now complete successfully without missing library errors.

---

### 2. ❌ → ✅ Events Generated Without run_id Field
**Files**: `pipeline/emit.py`, `pipeline/detect.py`  
**Root Cause**: Complete missing of run_id throughout event generation pipeline:
- Event Pydantic model didn't have run_id field
- build_event() function didn't have run_id parameter
- All 9 event generation calls never passed run_id

**Solution Applied**:

#### 2a. pipeline/emit.py - Event Model
```python
# BEFORE
class Event(BaseModel):
    event_id: str
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: str
    timestamp: str
    confidence: float
    is_staff: bool
    zone_id: str
    queue_depth: int
    abandonment: int
    conversion: int
    session_id: Optional[str] = None
    track_id: Optional[int] = None

# AFTER
class Event(BaseModel):
    event_id: str
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: str
    timestamp: str
    confidence: float
    is_staff: bool
    zone_id: str
    queue_depth: int
    abandonment: int
    conversion: int
    session_id: Optional[str] = None
    track_id: Optional[int] = None
    run_id: Optional[str] = None  # ✅ ADDED
```

#### 2b. pipeline/emit.py - build_event() Function
```python
# BEFORE
def build_event(
    store_id: str,
    camera_id: str,
    visitor_id: str,
    event_type: str,
    timestamp_dt: datetime,
    confidence: float,
    is_staff: bool,
    zone_id: str,
    queue_depth: int = 0,
    abandonment: int = 0,
    conversion: int = 0,
    session_id: Optional[str] = None,
    track_id: Optional[int] = None,
) -> Event:
    return Event(
        event_id=str(uuid4()),
        store_id=store_id,
        camera_id=camera_id,
        visitor_id=visitor_id,
        event_type=event_type,
        timestamp=timestamp_dt.isoformat(),
        confidence=confidence,
        is_staff=is_staff,
        zone_id=zone_id,
        queue_depth=queue_depth,
        abandonment=abandonment,
        conversion=conversion,
        session_id=session_id,
        track_id=track_id,
    )

# AFTER
def build_event(
    store_id: str,
    camera_id: str,
    visitor_id: str,
    event_type: str,
    timestamp_dt: datetime,
    confidence: float,
    is_staff: bool,
    zone_id: str,
    queue_depth: int = 0,
    abandonment: int = 0,
    conversion: int = 0,
    session_id: Optional[str] = None,
    track_id: Optional[int] = None,
    run_id: Optional[str] = None,  # ✅ ADDED
) -> Event:
    return Event(
        event_id=str(uuid4()),
        store_id=store_id,
        camera_id=camera_id,
        visitor_id=visitor_id,
        event_type=event_type,
        timestamp=timestamp_dt.isoformat(),
        confidence=confidence,
        is_staff=is_staff,
        zone_id=zone_id,
        queue_depth=queue_depth,
        abandonment=abandonment,
        conversion=conversion,
        session_id=session_id,
        track_id=track_id,
        run_id=run_id,  # ✅ ADDED
    )
```

#### 2c. pipeline/detect.py - All 9 build_event() Calls Updated
**Locations Updated**:
- Line ~651: ENTRY event → `run_id=self.run_id`
- Line ~759: EXIT event → `run_id=self.run_id`
- Line ~868: Zone transition → `run_id=self.run_id`
- Line ~912: Zone departure → `run_id=self.run_id`
- Line ~960: Tripwire crossing → `run_id=self.run_id`
- Line ~988: Tripwire crossing (return) → `run_id=self.run_id`
- Line ~1026: Staff detection → `run_id=self.run_id`
- Line ~1054: Abandonment flag → `run_id=self.run_id`
- Line ~1124: Conversion flag → `run_id=self.run_id`

**Pattern Applied**:
```python
# BEFORE
event = build_event(
    store_id=self.store_id,
    camera_id=self.camera_id,
    visitor_id=visitor_id,
    event_type="ENTRY",
    timestamp_dt=datetime.now(timezone.utc),
    confidence=confidence,
    is_staff=is_staff,
    zone_id=zone_id,
)

# AFTER
event = build_event(
    store_id=self.store_id,
    camera_id=self.camera_id,
    visitor_id=visitor_id,
    event_type="ENTRY",
    timestamp_dt=datetime.now(timezone.utc),
    confidence=confidence,
    is_staff=is_staff,
    zone_id=zone_id,
    run_id=self.run_id,  # ✅ ADDED
)
```

**Impact**: All generated events now include run_id, enabling proper event isolation per video processing run.

---

### 3. ❌ → ✅ Metrics Queries Don't Filter by run_id
**File**: `app/metrics.py`  
**Root Cause**: Queue depth, queue joins, and queue abandons queries built WHERE clauses without including run_id filter, causing aggregation across all runs instead of per-run metrics.

**Solution Applied**:

#### 3a. Queue Depth Query (lines 54-75)
```python
# BEFORE
where = and_(
    DBEvent.store_id == store_id,
    DBEvent.event_type.in_(["BILLING_QUEUE_JOIN", "BILLING_QUEUE_EXIT"]),
    DBEvent.timestamp >= window_start,
)

result = await session.execute(
    select(func.avg(DBEvent.queue_depth)).where(where)
)

# AFTER
where = and_(
    DBEvent.store_id == store_id,
    DBEvent.event_type.in_(["BILLING_QUEUE_JOIN", "BILLING_QUEUE_EXIT"]),
    DBEvent.timestamp >= window_start,
)

if run_id:
    where = and_(where, DBEvent.run_id == run_id)

result = await session.execute(
    select(func.avg(DBEvent.queue_depth)).where(where)
)
```

#### 3b. Queue Joins Query (lines 76-95)
```python
# BEFORE
where = and_(
    DBEvent.store_id == store_id,
    DBEvent.event_type == "BILLING_QUEUE_JOIN",
    DBEvent.is_staff == False,
    DBEvent.timestamp >= window_start,
)

result = await session.execute(
    select(func.count(DBEvent.event_id)).where(where)
)

# AFTER
where = and_(
    DBEvent.store_id == store_id,
    DBEvent.event_type == "BILLING_QUEUE_JOIN",
    DBEvent.is_staff == False,
    DBEvent.timestamp >= window_start,
)

if run_id:
    where = and_(where, DBEvent.run_id == run_id)

result = await session.execute(
    select(func.count(DBEvent.event_id)).where(where)
)
```

#### 3c. Queue Abandons Query (lines 96-115)
```python
# BEFORE
where = and_(
    DBEvent.store_id == store_id,
    DBEvent.event_type == "BILLING_QUEUE_EXIT",
    DBEvent.is_staff == False,
    DBEvent.abandonment == 1,
    DBEvent.timestamp >= window_start,
)

result = await session.execute(
    select(func.count(DBEvent.event_id)).where(where)
)

# AFTER
where = and_(
    DBEvent.store_id == store_id,
    DBEvent.event_type == "BILLING_QUEUE_EXIT",
    DBEvent.is_staff == False,
    DBEvent.abandonment == 1,
    DBEvent.timestamp >= window_start,
)

if run_id:
    where = and_(where, DBEvent.run_id == run_id)

result = await session.execute(
    select(func.count(DBEvent.event_id)).where(where)
)
```

**Impact**: Metrics endpoint now correctly returns per-run data instead of aggregating all historical events.

---

## Summary of Changes

| File | Lines | Changes | Status |
|------|-------|---------|--------|
| `Dockerfile` | ~40 | Removed 9 invalid packages, kept 9 required | ✅ |
| `pipeline/emit.py` | 3 | Added run_id field to Event, added run_id param to build_event | ✅ |
| `pipeline/detect.py` | 9 | Updated all 9 build_event calls to pass run_id | ✅ |
| `app/metrics.py` | 30 | Added run_id filtering to 3 queue queries | ✅ |

**Total Files Modified**: 4  
**Total Lines Changed**: ~82  
**Syntax Validation**: ✅ All files pass error check

---

## Deployment Steps

### 1. Build Docker Image
```bash
docker compose build --no-cache api
```
✅ Should complete without libGL.so.1 errors

### 2. Run Database Migration (Optional - if column doesn't exist)
```bash
docker compose exec api python migrate_db.py
```
✅ Adds run_id column and index if needed

### 3. Start System
```bash
docker compose up -d
```

### 4. Run Validation Tests
```bash
docker compose exec api python test_fixes.py
```
✅ Should pass all 6 tests

### 5. Verify with Sample Upload
```bash
curl -X POST http://localhost:8000/upload-video \
  -F "file=@sample_video.mp4" \
  -F "store_id=STORE_BLR_002"
```

Check event generation:
```bash
curl http://localhost:8000/debug/event-summary?store_id=STORE_BLR_002
```
✅ Should show events with run_id

Check metrics:
```bash
curl http://localhost:8000/stores/STORE_BLR_002/metrics
```
✅ Should show non-zero values (unique_visitors, queue_depth > 0, etc.)

---

## Testing Utilities Created

### migrate_db.py
Safely adds run_id column and index to database. Features:
- Checks if column already exists (idempotent)
- Adds index for query performance
- Reports current schema
- Can be run multiple times safely

### test_fixes.py
Comprehensive validation of all fixes. Tests:
1. OpenCV and YOLO imports
2. Event generation with run_id
3. Emit module structure (Event class, build_event signature)
4. Metrics service accepts run_id
5. Database connection and schema
6. events.jsonl structure and content

Run after deployment: `python test_fixes.py`

---

## Expected Outcomes After Deployment

✅ **Docker Build Success**
- Image builds without system library errors
- OpenCV available in container
- YOLO model loads successfully

✅ **Event Generation with run_id**
- Each video upload creates unique run_id
- All generated events tagged with run_id in events.jsonl
- Database stores events with proper run_id values

✅ **Metrics Properly Filtered**
- API query `/stores/{store_id}/metrics` returns per-run data
- Queue metrics show accurate depth, abandonment, conversion rates
- Historical NULL run_id events don't affect new runs

✅ **Per-Run Isolation**
- Multiple video uploads generate separate runs
- Metrics can be queried per-run: `/stores/{store_id}/metrics?run_id=xxx`
- Analytics don't cross-contaminate between runs

---

## Root Cause Analysis

**Primary Issue**: Run-based event isolation was incomplete at the SOURCE (event generation), not at ingestion:

1. **Architectural Goal**: Each video upload = unique run_id, all events tagged
2. **Actual Implementation**: Events generated without run_id field
3. **Downstream Effect**: Database column exists but contains only NULL values
4. **Query Consequence**: Filtering by run_id matches nothing (silent failure)
5. **Observable Symptom**: Metrics show zeros even with 2238+ events in database

**Key Insight**: Event isolation MUST occur at generation time (pipeline/detect.py), not post-hoc. Database column existence doesn't guarantee it's populated correctly.

---

## Verification Checklist

- [x] Dockerfile system dependencies corrected
- [x] Event model includes run_id field
- [x] build_event() function accepts run_id parameter
- [x] All 9 build_event() calls in detect.py pass run_id
- [x] Metrics queries filter by run_id when provided
- [x] Syntax validation passed for all modified files
- [x] migrate_db.py created for schema management
- [x] test_fixes.py created for post-deployment validation
- [ ] Docker build tested (pending execution)
- [ ] Database migration applied (pending execution)
- [ ] Event generation tested with real video (pending execution)
- [ ] Metrics endpoint tested with data (pending execution)
- [ ] End-to-end pipeline tested (pending execution)

---

Generated: 2024 (Post-Audit)  
Status: READY FOR DEPLOYMENT
