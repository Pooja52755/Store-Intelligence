# DEPLOYMENT CHECKLIST - Store Intelligence Fixes

## Pre-Deployment Verification ✅

- [x] Root cause analysis completed
- [x] All 4 critical files identified
- [x] Code fixes applied to all locations
- [x] Syntax validation passed (0 errors)
- [x] Code patterns verified
- [x] Helper scripts created
- [x] Documentation complete

---

## Phase 1: Build & Container Setup

### Step 1.1: Build Docker Image
```bash
docker compose build --no-cache api
```

**Expected Output**:
- No errors about libGL.so.1
- No package not found errors
- Build completes successfully
- Final layer shows success

**Success Criteria**: ✅ Build completes without system library errors

**Troubleshooting**:
- If still seeing libGL errors: Check that Dockerfile has exactly these packages: libglib2.0-0, libsm6, libxext6, libxrender1, libx11-6, libgomp1, ffmpeg, libavcodec-extra, git, wget, ca-certificates

---

### Step 1.2: Start Services
```bash
docker compose up -d
```

**Expected Output**:
```
✅ Creating network...
✅ Creating database...
✅ Creating redis...
✅ Creating api...
✅ All services up
```

**Success Criteria**: ✅ All containers running without errors

```bash
# Verify containers are running
docker compose ps
```

---

## Phase 2: Dependency Verification

### Step 2.1: Test OpenCV Import
```bash
docker compose exec api python -c "import cv2; print(f'OpenCV {cv2.__version__} available')"
```

**Expected Output**:
```
OpenCV 4.9.0.80 available
```

**Success Criteria**: ✅ Import succeeds without errors

---

### Step 2.2: Test YOLO Import
```bash
docker compose exec api python -c "from ultralytics import YOLO; print('YOLO ready')"
```

**Expected Output**:
```
YOLO ready
```

**Success Criteria**: ✅ YOLO loads without errors

---

### Step 2.3: Test API Health
```bash
curl http://localhost:8000/health
```

**Expected Output**:
```json
{
  "status": "healthy",
  "timestamp": "2024-..."
}
```

**Success Criteria**: ✅ API responds to health check

---

## Phase 3: Database Setup

### Step 3.1: Run Database Migration (OPTIONAL - if starting fresh)
```bash
docker compose exec api python migrate_db.py
```

**Expected Output**:
```
✅ Column 'run_id' already exists
✅ Index 'idx_events_run_id' already exists
Current events table schema:
  event_id              UUID              nullable=NO
  store_id              VARCHAR(100)      nullable=NO
  ...
  run_id                VARCHAR(50)       nullable=YES
  ...
✅ Migration complete!
```

**Success Criteria**: ✅ run_id column exists, index exists

**Note**: Only needed if running fresh database. Skip if database already has these columns.

---

## Phase 4: Run Comprehensive Tests

### Step 4.1: Execute Test Suite
```bash
docker compose exec api python test_fixes.py
```

**Expected Output**:
```
========================================================================
COMPREHENSIVE SYSTEM VALIDATION TESTS
========================================================================

Testing Imports...
✅ Imports
Testing Event Generation...
✅ Event Generation
Testing Emit Module Structure...
✅ Emit Module Structure
Testing Metrics Service...
✅ Metrics Service
Testing Database Connection...
✅ Database Connection
Testing events.jsonl Structure...
✅ events.jsonl Structure

========================================================================
TEST SUMMARY
========================================================================
✅ PASS | Imports
✅ PASS | Event Generation
✅ PASS | Emit Module Structure
✅ PASS | Metrics Service
✅ PASS | Database Connection
✅ PASS | events.jsonl Structure
========================================================================
Results: 6/6 tests passed
🎉 ALL TESTS PASSED - System is ready!
```

**Success Criteria**: ✅ All 6 tests pass

**Troubleshooting**:
- If "Imports" fails: Check Docker build was successful
- If "Database Connection" fails: Verify PostgreSQL is running and accessible
- If "Event Generation" fails: Check Python environment has all dependencies

---

## Phase 5: Functional Testing

### Step 5.1: Upload Test Video
```bash
# Using curl (if you have a test video file)
curl -X POST http://localhost:8000/upload-video \
  -F "file=@/path/to/test_video.mp4" \
  -F "store_id=STORE_BLR_002"
```

**Expected Response**:
```json
{
  "run_id": "uuid-format-string",
  "store_id": "STORE_BLR_002",
  "status": "PROCESSING",
  "message": "Video queued for processing"
}
```

**Success Criteria**: ✅ Upload accepted, run_id generated

**Note**: Video processing can take several minutes

---

### Step 5.2: Check Event Generation
```bash
# After video finishes processing (check status endpoint)
curl "http://localhost:8000/stores/STORE_BLR_002/runs" | jq '.'
```

**Expected Output** (after processing completes):
```json
{
  "runs": [
    {
      "run_id": "uuid-format-string",
      "store_id": "STORE_BLR_002",
      "status": "COMPLETED",
      "event_count": 150,
      "created_at": "2024-...",
      "completed_at": "2024-..."
    }
  ]
}
```

**Success Criteria**: ✅ Run shows COMPLETED status with event_count > 0

---

### Step 5.3: Verify run_id in Events
```bash
# Check event summary
curl "http://localhost:8000/debug/event-summary?store_id=STORE_BLR_002&run_id=<RUN_ID>" | jq '.'
```

**Expected Output**:
```json
{
  "store_id": "STORE_BLR_002",
  "run_id": "uuid-format-string",
  "total_events": 150,
  "events_by_type": {
    "ENTRY": 45,
    "EXIT": 42,
    "ZONE_VISIT": 38,
    "BILLING_QUEUE_JOIN": 12,
    "BILLING_QUEUE_EXIT": 10,
    "CONVERSION": 3
  }
}
```

**Success Criteria**: ✅ Events grouped by type, run_id properly filtered

---

### Step 5.4: Check Metrics
```bash
curl "http://localhost:8000/stores/STORE_BLR_002/metrics?run_id=<RUN_ID>" | jq '.'
```

**Expected Output**:
```json
{
  "store_id": "STORE_BLR_002",
  "run_id": "uuid-format-string",
  "unique_visitors": 45,
  "conversion_rate": 0.067,
  "queue_depth": 5.3,
  "abandonment_rate": 0.24,
  "timestamp": "2024-..."
}
```

**Success Criteria**: 
- ✅ unique_visitors > 0
- ✅ conversion_rate between 0-1
- ✅ queue_depth > 0
- ✅ abandonment_rate between 0-1
- ⚠️ NOT all zeros

---

## Phase 6: End-to-End Validation

### Step 6.1: Multi-Run Test
Upload 2-3 different videos and verify each has:
- Unique run_id
- Independent event counts
- Metrics don't cross-contaminate

```bash
# Upload video 1
curl -X POST http://localhost:8000/upload-video \
  -F "file=@video1.mp4" \
  -F "store_id=STORE_BLR_002" | jq '.run_id' > run1.txt

# Upload video 2
curl -X POST http://localhost:8000/upload-video \
  -F "file=@video2.mp4" \
  -F "store_id=STORE_BLR_002" | jq '.run_id' > run2.txt

# Compare metrics for each run
RUN1=$(cat run1.txt | tr -d '"')
RUN2=$(cat run2.txt | tr -d '"')

echo "Run 1 ($RUN1):"
curl "http://localhost:8000/stores/STORE_BLR_002/metrics?run_id=$RUN1" | jq '.unique_visitors'

echo "Run 2 ($RUN2):"
curl "http://localhost:8000/stores/STORE_BLR_002/metrics?run_id=$RUN2" | jq '.unique_visitors'
```

**Success Criteria**: 
- ✅ run_ids are different
- ✅ Event counts different
- ✅ Metrics different (not aggregated)

---

## Phase 7: Monitoring

### Ongoing Validation
```bash
# Monitor logs for errors
docker compose logs -f api | grep -E "ERROR|Exception"

# Check database for NULL run_ids (shouldn't happen with new events)
docker compose exec db psql -U postgres -d storedb -c \
  "SELECT COUNT(*) FROM events WHERE run_id IS NULL AND created_at > NOW() - INTERVAL '1 hour';"
```

**Expected**:
- No ERROR logs
- New events should have run_id (not NULL)

---

## Rollback Plan

If something goes wrong:

### Quick Rollback
```bash
# Stop services without losing data
docker compose down

# Rebuild from clean state
docker compose build --no-cache api
docker compose up -d

# Run tests again
docker compose exec api python test_fixes.py
```

### Full Reset (if needed)
```bash
# This will delete all data - USE CAREFULLY
docker compose down -v
docker volume rm store-intelligence_pgdata
docker compose up -d
docker compose exec api python migrate_db.py
```

---

## Success Criteria Checklist

Phase 1 - Build:
- [ ] Docker build completes without errors
- [ ] All containers up and running

Phase 2 - Dependencies:
- [ ] OpenCV imports successfully
- [ ] YOLO imports successfully
- [ ] API health check passes

Phase 3 - Database:
- [ ] Migration completes (or skipped if not needed)
- [ ] run_id column exists

Phase 4 - Tests:
- [ ] All 6 tests pass

Phase 5 - Functional:
- [ ] Video upload succeeds
- [ ] Events generated with run_id
- [ ] Metrics show non-zero values
- [ ] run_id properly filters queries

Phase 6 - End-to-End:
- [ ] Multiple uploads have unique run_ids
- [ ] Metrics don't cross-contaminate

## Final Status

Once all phases complete:

```bash
# Final verification
docker compose exec api python test_fixes.py && echo "✅ SYSTEM READY FOR PRODUCTION"
```

🎉 **System is production-ready when all checkpoints pass!**

---

## Support & Debugging

### Common Issues

**Issue**: "libGL.so.1 not found"
- **Solution**: Verify Dockerfile has all 9 required packages, rebuild with --no-cache

**Issue**: "Metrics still showing zeros"
- **Solution**: Verify run_id is populated in events.jsonl, check metrics.py filtering logic

**Issue**: "Database column error"
- **Solution**: Run migrate_db.py to ensure schema is complete

**Issue**: "YOLO model download fails"
- **Solution**: Check internet connectivity in container, pre-download yolov8n.pt model

---

## Documentation Reference

- **FIXES_COMPLETED.md** - Detailed before/after comparisons
- **test_fixes.py** - Comprehensive test suite
- **migrate_db.py** - Database schema management
- **verify_fixes.sh** - Quick bash verification

---

**Deployment Status**: READY  
**Last Updated**: 2024  
**Target**: Production deployment with run-based event isolation working end-to-end
