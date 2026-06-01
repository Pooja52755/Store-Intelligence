# Production Deployment & Debugging Guide

## Overview
This guide provides step-by-step instructions to make the Store Intelligence system production-ready and pass Purplle evaluation criteria (target: 85+/100).

## Critical Fixes Applied

### 1. Docker System Dependencies (FIXED)
**Issue**: `ImportError: libGL.so.1: cannot open shared object file`
**Root Cause**: Missing OpenGL and video codec libraries in Docker container

**Files Modified**: 
- `Dockerfile` - Added 27 system library dependencies

**Key Libraries Added**:
- `libgl1-mesa-glx` - OpenGL runtime (fixes libGL.so.1 error)
- `libavcodec-extra`, `libavformat-dev`, `libswscale-dev` - FFmpeg video codecs
- `libx11-6`, `libxext6`, `libsm6`, `libxrender-dev` - X11 display libraries
- `libjpeg-dev`, `libpng-dev`, `libtiff-dev` - Image format support
- `libhdf5-dev` - HDF5 support for deep learning models

### 2. Event Isolation Architecture (FIXED)
**Issue**: Metrics showed static values (always 14 visitors, 57 sessions)
**Root Cause**: All analytics reading entire historical event database instead of per-run events

**Files Modified**:
- `app/db.py` - Added `run_id` column to Event table
- `app/session_analytics.py` - Added run_id filtering in `fetch_store_events()`
- `app/models.py` - Added `run_id` to EventSchema
- `app/metrics.py` - Pass run_id to all metric calculations
- `app/funnel.py` - Pass run_id to funnel analysis
- `app/heatmap.py` - Pass run_id to heatmap generation
- `app/ingestion.py` - Attach run_id to events before database insertion

### 3. Upload Directory Reliability (FIXED)
**Issue**: Upload endpoint returned 503 due to read-only mount
**Root Cause**: Tried to write to `/app/clips` which is mounted read-only

**Files Modified**:
- `app/main.py` - Implemented writable directory fallback: `/app/uploads` → `/tmp/uploads` → `./uploads`
- `docker-compose.yml` - Added `./uploads:/app/uploads` volume mount

### 4. Pipeline Error Logging (FIXED)
**Issue**: Subprocess errors not captured, no visibility into pipeline failures
**Root Cause**: Minimal logging in detect.py and trigger_pipeline_processing()

**Files Modified**:
- `pipeline/detect.py` - Added comprehensive validation logging:
  - Video file existence verification
  - Video open success confirmation
  - Frames processed count
  - Events generated count
  - Output file creation verification
- `app/main.py` - Enhanced subprocess error capturing:
  - Captured stdout and stderr
  - Detailed error logging with return codes
  - Error storage in run metadata

### 5. Video Processing Validation (FIXED)
**Issue**: No verification that videos were processed or events generated
**Root Cause**: Missing validation steps in pipeline

**Added Checks**:
- Verify video file exists before processing
- Log video properties (resolution, fps, frame count)
- Log frame processing progress
- Verify output file exists and contains events
- Log event count written to disk

---

## Pre-Deployment Checklist

### Database Migration
Execute this SQL in your PostgreSQL database:

```sql
-- Add run_id column to events table
ALTER TABLE events ADD COLUMN run_id VARCHAR(50) NULL;

-- Create index for run_id filtering
CREATE INDEX idx_events_run_id ON events(run_id);

-- Verify changes
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'events' 
ORDER BY ordinal_position;
```

### Verify PostgreSQL Connection
```bash
# Inside Docker container
python -c "
import asyncpg
import asyncio

async def test():
    conn = await asyncpg.connect(
        user='postgres',
        password='postgres',
        database='storedb',
        host='db'
    )
    print('✓ Database connected')
    await conn.close()

asyncio.run(test())
"
```

---

## Deployment Steps

### Step 1: Build New Docker Image
```bash
# Rebuild with new Dockerfile containing all system dependencies
docker-compose build api

# Verify build completed successfully (check for libgl1-mesa-glx in final layer)
docker-compose build api --no-cache
```

### Step 2: Start Services
```bash
# Start all services (db, cache, graph, api)
docker-compose up -d

# Wait 10 seconds for services to start
sleep 10

# Verify all services are running
docker-compose ps

# Expected output:
# NAME                           STATUS
# store-intelligence-api         Up 10 seconds
# store-intelligence-cache       Up 10 seconds
# store-intelligence-db          Up 10 seconds
# store-intelligence-graph       Up 10 seconds
```

### Step 3: Execute Database Migration
```bash
# Connect to PostgreSQL container
docker exec -it store-intelligence-db psql -U postgres -d storedb

# Run migration SQL (paste the commands from "Database Migration" section above)
# Then exit: \q
```

### Step 4: Verify System Health
```bash
# Check API is responding
curl -s http://localhost:8000/health | python -m json.tool

# Expected output:
# {
#   "status": "healthy",
#   "timestamp": "2024-01-15T10:30:00Z"
# }

# Verify store layout is loaded
curl -s http://localhost:8000/stores | python -m json.tool
```

### Step 5: Create Test Upload Directory
```bash
# Ensure uploads directory exists and has correct permissions
mkdir -p uploads
chmod 777 uploads

# Verify directory is mounted in Docker container
docker exec store-intelligence-api ls -la /app/uploads
```

---

## Testing & Debugging

### Test 1: Upload Video and Check Processing
```bash
# Upload a test video
curl -X POST http://localhost:8000/upload-video \
  -F "file=@test_video.mp4" \
  -F "store_id=STORE_BLR_002"

# Expected response:
# {
#   "run_id": "550e8400-e29b-41d4-a716-446655440000",
#   "store_id": "STORE_BLR_002",
#   "status": "PENDING"
# }
```

### Test 2: Check Pipeline Status
```bash
# Get current run status (including processing logs)
curl -s http://localhost:8000/debug/run-status?store_id=STORE_BLR_002 | python -m json.tool

# Expected output (during processing):
# {
#   "current_run_id": "550e8400-e29b-41d4-a716-446655440000",
#   "status": "PROCESSING",
#   "videos_processed": 1,
#   "frames_processed": 2400,
#   "events_generated": 127,
#   "visitors_detected": 15,
#   "processing_time_sec": 45.2
# }

# Expected output (after completion):
# {
#   "current_run_id": "550e8400-e29b-41d4-a716-446655440000",
#   "status": "COMPLETED",
#   "videos_processed": 1,
#   "frames_processed": 2400,
#   "events_generated": 127,
#   "visitors_detected": 15,
#   "processing_time_sec": 62.8
# }
```

### Test 3: Verify Metrics Are Dynamic
```bash
# Get metrics for specific run
curl -s 'http://localhost:8000/stores/STORE_BLR_002/metrics?run_id=550e8400-e29b-41d4-a716-446655440000' | python -m json.tool

# Expected output (should reflect actual video data, NOT static):
# {
#   "store_id": "STORE_BLR_002",
#   "run_id": "550e8400-e29b-41d4-a716-446655440000",
#   "unique_visitors": 15,
#   "entry_sessions": 15,
#   "conversion_rate": 0.333,
#   "avg_dwell_by_zone": {"ENTRY": 8.2, "CHECKOUT": 45.3},
#   "queue_depth": 2,
#   "abandonment_rate": 0.2
# }
```

### Test 4: Check Event Summary
```bash
# Get event counts by type for verification
curl -s http://localhost:8000/debug/event-summary?store_id=STORE_BLR_002 | python -m json.tool

# Expected output:
# {
#   "store_id": "STORE_BLR_002",
#   "total_events": 127,
#   "events_by_type": {
#     "ENTRY": 15,
#     "EXIT": 12,
#     "ZONE_ENTER": 38,
#     "ZONE_EXIT": 35,
#     "PURCHASE": 5,
#     "QUEUE_JOIN": 10,
#     "QUEUE_LEAVE": 12
#   },
#   "by_run": {
#     "550e8400-e29b-41d4-a716-446655440000": {
#       "total": 127,
#       "events": {...}
#     }
#   }
# }
```

### Test 5: View Docker Logs for Debugging
```bash
# View API logs (follow mode, shows real-time)
docker logs -f store-intelligence-api

# Search for specific errors
docker logs store-intelligence-api | grep -i "error\|failed\|exception"

# View pipeline logs (check for video processing details)
docker logs store-intelligence-api | grep "VIDEO PROCESSING\|PIPELINE"

# View database logs (check for connection issues)
docker logs store-intelligence-db | grep -i "error"
```

### Test 6: Verify Files Exist in Container
```bash
# Check if store_layout.json exists
docker exec store-intelligence-api ls -la /app/store_layout.json

# Check if events directory is writable
docker exec store-intelligence-api touch /app/events/test.txt && echo "✓ Writable" || echo "✗ Not writable"

# Check uploaded video
docker exec store-intelligence-api ls -la /app/uploads/

# Check generated events file
docker exec store-intelligence-api ls -la /app/events/STORE_BLR_002/*/events.jsonl

# Verify run metadata tracking
docker exec store-intelligence-api find /app/events -name "run_metadata.json" -exec cat {} \;
```

---

## Common Issues & Solutions

### Issue 1: "libGL.so.1: cannot open shared object file"
**Diagnosis**: 
```bash
docker logs store-intelligence-api | grep "libGL"
```

**Solution**: 
- Rebuilt Dockerfile with `libgl1-mesa-glx` package
- Rebuild image: `docker-compose build api --no-cache`
- Restart: `docker-compose restart api`

### Issue 2: "Pipeline processing failed with return code 1"
**Diagnosis**:
- Check logs: `docker logs store-intelligence-api | grep "PIPELINE PROCESSING FAILED"`
- Check stderr output in run metadata
- Verify video file exists: `docker exec store-intelligence-api ls -la /app/uploads/`

**Solutions**:
- Check video format/codec support: `ffprobe -v error -show_format -show_streams video.mp4`
- Verify YOLO model loaded: `docker logs store-intelligence-api | grep "Loading YOLO"`
- Check frame processing: `docker logs store-intelligence-api | grep "frames processed"`

### Issue 3: "Cannot open video: /app/uploads/..."
**Diagnosis**:
- Video file not found or can't be read by OpenCV
- Check: `docker exec store-intelligence-api ls -la /app/uploads/`

**Solutions**:
- Verify video was uploaded to correct path
- Check file permissions in container
- Ensure video format is supported (MP4 preferred)

### Issue 4: "Events file not created"
**Diagnosis**:
```bash
# Check if pipeline completed successfully
docker logs store-intelligence-api | grep "PIPELINE.*COMPLETE"

# Check for events file
docker exec store-intelligence-api find /app/events -name "events.jsonl"
```

**Solutions**:
- Verify pipeline subprocess completed without errors
- Check if video contains detectable persons
- Review frame processing logs for detection count

### Issue 5: Database connection errors
**Diagnosis**:
```bash
docker logs store-intelligence-db | grep -i error
docker logs store-intelligence-api | grep "DATABASE\|asyncpg"
```

**Solutions**:
- Wait 15 seconds after `docker-compose up` for DB to initialize
- Verify PostgreSQL is running: `docker-compose ps`
- Check DB credentials in environment variables
- Ensure migration was executed

---

## Performance Optimization

### Frame Processing Speed
```python
# Current setting in detect.py (line ~15)
PIPELINE_FRAME_STRIDE = 5  # Process every 5th frame (reduces processing time)

# For faster processing, increase stride:
# PIPELINE_FRAME_STRIDE = 10  # Process every 10th frame (2x faster, less accuracy)

# For higher accuracy, decrease stride:
# PIPELINE_FRAME_STRIDE = 2   # Process every 2nd frame (2x slower, more accuracy)
```

### GPU Acceleration (if available)
```python
# In pipeline/detect.py, YOLO model loading:
self.yolo_model = YOLO('yolov8n.pt').to('cuda')  # Use GPU if available
```

### Batch Processing Multiple Videos
```bash
# Upload multiple videos (they'll be queued)
for video in video1.mp4 video2.mp4 video3.mp4; do
  curl -X POST http://localhost:8000/upload-video \
    -F "file=@$video" \
    -F "store_id=STORE_BLR_002"
done

# Monitor processing status
watch -n 2 'curl -s http://localhost:8000/debug/run-status?store_id=STORE_BLR_002 | grep processing_time'
```

---

## Monitoring & Observability

### Key Metrics to Monitor
1. **Processing Time**: Should complete within 60-120 seconds for 5-minute video
2. **Event Generation**: Should have 15-50 events per minute of video
3. **Detection Confidence**: Should be 0.3-0.9 for persons
4. **Memory Usage**: Should stay under 2GB for typical videos

### Logging Strategy
All important operations log with three levels:
- `logger.info()` - Major operations (startup, completion, key events)
- `logger.warning()` - Non-critical issues (missing optional data)
- `logger.error()` - Failures (with full stack trace for debugging)

### Verification Commands
```bash
# Show all INFO logs (important operations)
docker logs store-intelligence-api | grep "\[INFO\]"

# Show all ERRORS for debugging
docker logs store-intelligence-api | grep "\[ERROR\]"

# Count video processing attempts
docker logs store-intelligence-api | grep "VIDEO PROCESSING" | wc -l

# Monitor real-time processing
watch -n 1 'docker logs store-intelligence-api | tail -20'
```

---

## Purplle Evaluation Criteria Checklist

- [ ] **Metrics Accuracy** (20 pts)
  - [ ] Metrics change when videos are uploaded
  - [ ] Conversion rate calculated correctly
  - [ ] Dwell time measured accurately
  - [ ] Queue depth tracked

- [ ] **Video Processing** (25 pts)
  - [ ] Videos upload without errors
  - [ ] Processing completes successfully
  - [ ] Events generated from video
  - [ ] Person detection works (>80% accuracy)

- [ ] **API Endpoints** (20 pts)
  - [ ] Upload endpoint returns 200
  - [ ] Metrics endpoint includes run_id
  - [ ] Funnel data returns correct stage counts
  - [ ] Heatmap returns zone visitation

- [ ] **System Reliability** (20 pts)
  - [ ] No crashes after video upload
  - [ ] Database persists events correctly
  - [ ] Error messages are descriptive
  - [ ] Logs show processing progress

- [ ] **Code Quality** (15 pts)
  - [ ] Code follows Python best practices
  - [ ] Error handling is comprehensive
  - [ ] Logging is informative
  - [ ] Documentation is complete

---

## Success Indicators

✅ **System is production-ready when:**
1. All tests pass (Upload → Processing → Metrics)
2. Processing time < 2 minutes per 5-min video
3. Event detection accuracy > 80%
4. Zero unhandled exceptions in logs
5. Metrics show different values for different videos
6. All debug endpoints return valid JSON
7. Docker logs show structured, helpful messages

---

## Support & Next Steps

If you encounter issues:
1. Check Docker logs: `docker logs store-intelligence-api`
2. Run diagnostic: `curl http://localhost:8000/debug/run-status?store_id=STORE_BLR_002`
3. Verify files exist in container: `docker exec store-intelligence-api ls -la /app/`
4. Review IMPLEMENTATION_SUMMARY.md for architecture details
5. Check VERIFICATION_CHECKLIST.md for comprehensive testing

For production deployment:
- Enable proper authentication on API endpoints
- Configure SSL/TLS for HTTPS
- Set up monitoring and alerting
- Implement data retention policies
- Configure database backups
- Set resource limits on containers
