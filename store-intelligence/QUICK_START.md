# QUICK START - Production Deployment Commands

## 🚀 Fastest Path to Deployment (5 minutes)

### 1. Stop existing services (if running)
```bash
docker-compose down
```

### 2. Rebuild Docker image with ALL system dependencies
```bash
docker-compose build api --no-cache
```

### 3. Start all services
```bash
docker-compose up -d
sleep 15  # Wait for database to initialize
```

### 4. Execute database migration
```bash
docker exec -it store-intelligence-db psql -U postgres -d storedb << 'EOF'
ALTER TABLE events ADD COLUMN run_id VARCHAR(50) NULL;
CREATE INDEX idx_events_run_id ON events(run_id);
SELECT 'Migration complete' as status;
EOF
```

### 5. Verify deployment
```bash
# Check all services are running
docker-compose ps

# Test API health
curl -s http://localhost:8000/health | python -m json.tool

# Verify database migration
docker exec store-intelligence-db psql -U postgres -d storedb \
  -c "SELECT column_name FROM information_schema.columns WHERE table_name='events' AND column_name='run_id';"
```

---

## 📋 Code Changes Summary

### File 1: Dockerfile (CRITICAL FIX)
**What Changed**: Added 27 system library dependencies for OpenCV and video processing

**Key Addition**:
```dockerfile
libgl1-mesa-glx          # Fixes: ImportError: libGL.so.1
libavcodec-extra         # FFmpeg video codec support
libswscale-dev           # Video frame scaling
libhdf5-dev              # Deep learning model loading
# ... and 23 more packages
```

**Verification**:
```bash
docker exec store-intelligence-api ldconfig -p | grep "libGL"  # Should show libGL.so.1
```

---

### File 2: docker-compose.yml
**What Changed**: Added `/app/uploads` volume mount for writable upload directory

**Before**:
```yaml
volumes:
  - ./events:/app/events
  - ./pipeline/input_clips:/app/clips:ro
  - ./events/store_layout.json:/app/store_layout.json:ro
```

**After**:
```yaml
volumes:
  - ./events:/app/events
  - ./pipeline/input_clips:/app/clips:ro
  - ./uploads:/app/uploads           # ← NEW: Writable uploads directory
  - ./events/store_layout.json:/app/store_layout.json:ro
```

---

### File 3: pipeline/detect.py
**What Changed**: Enhanced logging for debugging video processing

**Added to process_video() start**:
```python
logger.info("=== VIDEO PROCESSING START ===")
logger.info("Video file: %s", video_path)
logger.info("Output path: %s", self.writer.output_path)

# Verify file exists
if not video_file.exists():
    logger.error("VIDEO FILE NOT FOUND: %s", video_path)
    raise FileNotFoundError(...)

# Log video properties
logger.info("Video opened successfully")
logger.info("Video properties: %dx%d, %d frames, %.2f fps", frame_w, frame_h, total_frames, video_fps)
```

**Added to process_video() end**:
```python
logger.info("=== VIDEO PROCESSING COMPLETE ===")
logger.info("Events generated: %d", event_count)
logger.info("Frames processed: %d / %d", processed_frames, total_frames)

# Verify output file created
if output_file.exists():
    logger.info("Output file size: %d bytes, event lines: %d", file_size, line_count)
else:
    logger.error("OUTPUT FILE NOT CREATED: %s", self.writer.output_path)
```

---

### File 4: app/main.py (trigger_pipeline_processing function)
**What Changed**: Enhanced subprocess error capturing and logging

**Key Additions**:
```python
logger.info("=== PIPELINE PROCESSING START ===")
logger.info("Run ID: %s", run_id)

# Verify video exists
if not video_file.exists():
    raise FileNotFoundError(f"Video file not found: {video_path}")

# Capture subprocess output
stdout, stderr = await process.communicate()
stdout_text = stdout.decode(errors='ignore')
stderr_text = stderr.decode(errors='ignore')

# Log results
if process.returncode != 0:
    logger.error("=== PIPELINE PROCESSING FAILED ===")
    logger.error("Return code: %d", process.returncode)
    logger.error("STDERR:\n%s", stderr_text)
else:
    logger.info("=== PIPELINE PROCESSING SUCCEEDED ===")
    # Count events generated
    event_count = len(events_text.split('\n')) if events_text else 0
    logger.info("Events generated: %d", event_count)
```

---

## 🔍 How to Verify Each Fix

### Fix 1: System Dependencies Installed
```bash
docker exec store-intelligence-api apt-get update && apt-cache search --names-only "^libgl1-mesa-glx$"

# Should show: libgl1-mesa-glx - ...
```

### Fix 2: OpenCV Can Load Videos
```bash
docker exec store-intelligence-api python -c "
import cv2
import numpy as np
print('✓ OpenCV imported successfully')
print(f'✓ OpenCV version: {cv2.__version__}')
"
```

### Fix 3: Uploads Directory Writable
```bash
docker exec store-intelligence-api touch /app/uploads/test.txt && echo "✓ Writable" && rm /app/uploads/test.txt
```

### Fix 4: YOLO Model Loads
```bash
docker exec store-intelligence-api python -c "
from ultralytics import YOLO
model = YOLO('yolov8n.pt')
print('✓ YOLO model loaded successfully')
"
```

### Fix 5: Logging Works
```bash
docker logs store-intelligence-api | grep "VIDEO PROCESSING\|PIPELINE PROCESSING" | head -20
```

---

## ✅ Complete Test Sequence

### Test 1: Upload and Process Video
```bash
# Prepare a short test video (can be any MP4 with people)
# Upload it
curl -X POST http://localhost:8000/upload-video \
  -F "file=@test_video.mp4" \
  -F "store_id=STORE_BLR_002"

# Extract run_id from response
# Expected: {"run_id": "550e8400-e29b-41d4-a716-446655440000", ...}

RUNID="550e8400-e29b-41d4-a716-446655440000"
```

### Test 2: Monitor Processing (30 seconds)
```bash
RUNID="550e8400-e29b-41d4-a716-446655440000"

# Check status repeatedly
for i in {1..6}; do
  echo "Check $i: $(date)"
  curl -s http://localhost:8000/debug/run-status?store_id=STORE_BLR_002 | \
    python -c "import sys, json; d=json.load(sys.stdin); print(f\"Status: {d.get('status')}, Events: {d.get('events_generated', 0)}\")"
  sleep 5
done
```

### Test 3: Verify Metrics Changed
```bash
RUNID="550e8400-e29b-41d4-a716-446655440000"

# Get metrics for this run
curl -s http://localhost:8000/stores/STORE_BLR_002/metrics?run_id=$RUNID | python -m json.tool

# Expected: unique_visitors > 0, conversion_rate > 0, different from previous run
```

### Test 4: Check Event Summary
```bash
curl -s http://localhost:8000/debug/event-summary?store_id=STORE_BLR_002 | python -m json.tool

# Expected: Events by type (ENTRY, EXIT, ZONE_ENTER, etc.) with counts > 0
```

---

## 🔧 Configuration Tuning

### Increase Processing Speed (less accurate)
**File**: `pipeline/detect.py` (line ~15)
```python
PIPELINE_FRAME_STRIDE = 10  # Process every 10th frame instead of 5
```

### Increase Processing Accuracy (slower)
**File**: `pipeline/detect.py` (line ~15)
```python
PIPELINE_FRAME_STRIDE = 2   # Process every 2nd frame instead of 5
```

### Adjust YOLO Confidence Threshold
**File**: `pipeline/detect.py` (line ~14)
```python
CONF_THRESHOLD = 0.25  # Lower = more detections but more false positives (was 0.35)
```

---

## 📊 Expected Performance Numbers

| Metric | Target | Acceptable Range |
|--------|--------|------------------|
| Processing time (5-min video) | 60 sec | 45-120 sec |
| Events per minute of video | 25 | 15-40 |
| Person detection accuracy | 85% | 75-95% |
| Memory usage | 1.5 GB | 1-2 GB |
| CPU usage (peak) | 80% | 60-100% |
| Metrics response time | <100ms | <500ms |

---

## 🐛 Troubleshooting Quick Links

**Problem**: libGL.so.1 error
→ Run: `docker-compose build api --no-cache && docker-compose restart api`

**Problem**: Video file not found
→ Check: `docker exec store-intelligence-api ls -la /app/uploads/`

**Problem**: No events generated
→ Check: `docker logs store-intelligence-api | grep "PIPELINE PROCESSING"`

**Problem**: Database migration failed
→ Run: `docker exec store-intelligence-db psql -U postgres -d storedb -c "\d events"`

**Problem**: Metrics still showing old values
→ Check: `curl http://localhost:8000/debug/event-summary | grep run_id`

---

## 📝 Checklist Before Submitting to Purplle

- [ ] Dockerfile rebuilt with all system dependencies
- [ ] Database migration applied (run_id column added)
- [ ] Docker services started and healthy
- [ ] Video upload works (returns 200 with run_id)
- [ ] Video processing completes (status = COMPLETED)
- [ ] Events generated (count > 0)
- [ ] Metrics changed from baseline
- [ ] Logs show detailed processing steps
- [ ] All endpoints return proper JSON
- [ ] No Python errors in logs
- [ ] Tested with at least 2 different videos

---

## 📞 Support

If deployment fails:
1. Run: `docker-compose logs -f` to see real-time logs
2. Run: `docker-compose ps` to check service status
3. Run: `docker exec store-intelligence-api python -c "import cv2; print(cv2.__version__)"` to verify imports
4. Check: PRODUCTION_DEPLOYMENT.md for detailed troubleshooting
