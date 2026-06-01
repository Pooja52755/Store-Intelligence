# Exact Code Changes - Reference Guide

## Files Modified: 5
1. ✅ Dockerfile
2. ✅ docker-compose.yml  
3. ✅ pipeline/detect.py
4. ✅ app/main.py
5. ✅ PRODUCTION_DEPLOYMENT.md (new)
6. ✅ QUICK_START.md (new)

---

## 1. DOCKERFILE - System Dependencies Fix

**Location**: `./Dockerfile`

**What was changed**:
- Extended RUN apt-get install line from 4 packages to 27 packages
- Added all OpenGL, video codec, X11, and image format libraries

**Key packages added**:
- `libgl1-mesa-glx` ← Fixes: libGL.so.1 error
- `libgl1-mesa-dev`
- `libglu1-mesa`
- `libavcodec-extra`
- `libavformat-dev`
- `libswscale-dev`
- `libjpeg-dev`
- `libpng-dev`
- `libtiff-dev`
- `libxext6`
- `libsm6`
- `libxrender-dev`
- `libgomp1`
- `libopenblas-dev`
- `build-essential`
- `libhdf5-dev`
- And 11 more...

**Command to apply**:
```bash
docker-compose build api --no-cache
```

---

## 2. DOCKER-COMPOSE.YML - Upload Volume Mount

**Location**: `./docker-compose.yml`

**What was changed**:
Added one line to the `api` service volumes section:
```yaml
- ./uploads:/app/uploads    # NEW LINE
```

**Before** (services.api.volumes):
```yaml
volumes:
  - ./events:/app/events
  - ./pipeline/input_clips:/app/clips:ro
  - ./events/store_layout.json:/app/store_layout.json:ro
```

**After** (services.api.volumes):
```yaml
volumes:
  - ./events:/app/events
  - ./pipeline/input_clips:/app/clips:ro
  - ./uploads:/app/uploads                              # ← NEW
  - ./events/store_layout.json:/app/store_layout.json:ro
```

**Also added to pipeline service** (for consistency):
```yaml
volumes:
  - ./pipeline/input_clips:/app/clips:ro
  - ./events:/app/events
  - ./uploads:/app/uploads                              # ← NEW
  - ./events/store_layout.json:/app/store_layout.json:ro
```

---

## 3. PIPELINE/DETECT.PY - Enhanced Validation Logging

**Location**: `./pipeline/detect.py`

### Change 3a: Enhanced start of process_video() method (line ~349)

**Added**: Validation logging at video processing start
```python
logger.info("=== VIDEO PROCESSING START ===")
logger.info("Video file: %s", video_path)
logger.info("Resolved camera: %s", camera_id)
logger.info("Output path: %s", self.writer.output_path)

# Verify file exists
video_file = Path(video_path)
if not video_file.exists():
    logger.error("VIDEO FILE NOT FOUND: %s (absolute: %s)", video_path, video_file.resolve())
    raise FileNotFoundError(f"Video file not found: {video_path}")
logger.info("Video file exists, size: %d bytes", video_file.stat().st_size)

# Log opening attempt
logger.info("Opening video with cv2.VideoCapture...")
cap = cv2.VideoCapture(video_path)
if not cap.isOpened():
    logger.error("FAILED TO OPEN VIDEO: %s (check format/codec/permissions)", video_path)
    return 0
logger.info("Video opened successfully")

# Log video properties
logger.info("Video properties: %dx%d, %d frames, %.2f fps", frame_w, frame_h, total_frames, video_fps)
```

### Change 3b: Enhanced end of process_video() method (line ~789-810)

**Added**: Verification logging at video processing end
```python
logger.info("=== VIDEO PROCESSING COMPLETE ===")
logger.info("Video: %s", video_name)
logger.info("Events generated: %d", event_count)
logger.info("Frames processed: %d / %d", processed_frames, total_frames)
logger.info("Output file: %s", self.writer.output_path)

# Verify output file was written
output_file = Path(self.writer.output_path)
if output_file.exists():
    file_size = output_file.stat().st_size
    line_count = len(output_file.read_text().strip().split('\n')) if output_file.read_text().strip() else 0
    logger.info("Output file size: %d bytes, event lines: %d", file_size, line_count)
else:
    logger.error("OUTPUT FILE NOT CREATED: %s", self.writer.output_path)
```

**Verification**:
```bash
docker logs store-intelligence-api | grep "VIDEO PROCESSING"
```

---

## 4. APP/MAIN.PY - Enhanced Subprocess Error Logging

**Location**: `./app/main.py`

**Function**: `async def trigger_pipeline_processing(store_id: str, run_id: str, video_path: str, camera_id: str)`
**Line**: ~529

### Change 4a: Enhanced logging at start of processing

**Added**:
```python
logger.info("=== PIPELINE PROCESSING START ===")
logger.info("Run ID: %s", run_id)
logger.info("Store ID: %s", store_id)
logger.info("Video path: %s", video_path)
logger.info("Camera ID: %s", camera_id)

# Verify video file exists
video_file = Path(video_path)
if not video_file.exists():
    raise FileNotFoundError(f"Video file not found: {video_path}")
logger.info("Video file verified: %d bytes", video_file.stat().st_size)

# Log command being executed
logger.info("Pipeline command: %s", " ".join(cmd))

# Log subprocess start
process = await asyncio.create_subprocess_exec(...)
logger.info("Pipeline subprocess started: PID %d", process.pid)
```

### Change 4b: Enhanced error capturing and logging

**Changed from**:
```python
stdout, stderr = await process.communicate()

if process.returncode != 0:
    logger.error("Pipeline processing failed: ...")
```

**Changed to**:
```python
stdout, stderr = await process.communicate()

stdout_text = stdout.decode(errors='ignore')
stderr_text = stderr.decode(errors='ignore')

if process.returncode != 0:
    logger.error("=== PIPELINE PROCESSING FAILED ===")
    logger.error("Return code: %d", process.returncode)
    logger.error("STDOUT:\n%s", stdout_text)
    logger.error("STDERR:\n%s", stderr_text)
    
    run_manager.update_run_metadata(store_id, run_id, {
        "status": "FAILED",
        "error": f"Pipeline failed with code {process.returncode}. Check logs for details.",
        "stderr": stderr_text[:500]  # Store first 500 chars
    })
else:
    logger.info("=== PIPELINE PROCESSING SUCCEEDED ===")
    logger.info("Return code: %d", process.returncode)
    if stdout_text:
        logger.info("STDOUT:\n%s", stdout_text)
    
    # Enhanced event counting and logging
    events_file = run_manager.get_events_file(store_id, run_id)
    event_count = 0
    if events_file.exists():
        events_text = events_file.read_text().strip()
        event_count = len(events_text.split('\n')) if events_text else 0
        logger.info("Events file created: %s (%d events)", events_file, event_count)
    else:
        logger.warning("Events file not created: %s", events_file)
```

### Change 4c: Enhanced exception handling

**Changed from**:
```python
except Exception as e:
    logger.error("pipeline_trigger_error", run_id=run_id, error=str(e))
```

**Changed to**:
```python
except Exception as e:
    logger.error("=== PIPELINE TRIGGER ERROR ===")
    logger.error("Error type: %s", type(e).__name__)
    logger.error("Error message: %s", str(e))
    logger.exception("Full traceback:")
```

**Verification**:
```bash
docker logs store-intelligence-api | grep "PIPELINE PROCESSING"
```

---

## Database Migration (REQUIRED)

**Execute this SQL** in PostgreSQL:

```sql
-- Add run_id column to events table
ALTER TABLE events ADD COLUMN run_id VARCHAR(50) NULL;

-- Create index for run_id filtering (important for performance)
CREATE INDEX idx_events_run_id ON events(run_id);

-- Verify migration
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'events' 
AND column_name = 'run_id';
```

**How to execute**:
```bash
docker exec -it store-intelligence-db psql -U postgres -d storedb << 'EOF'
ALTER TABLE events ADD COLUMN run_id VARCHAR(50) NULL;
CREATE INDEX idx_events_run_id ON events(run_id);
EOF
```

---

## Summary of Changes

| File | Change | Impact | Verification |
|------|--------|--------|--------------|
| Dockerfile | +27 system packages | Fixes libGL.so.1 error | `docker logs \| grep "import cv2"` ✓ |
| docker-compose.yml | +1 volume mount | Enables writable uploads | `docker exec api touch /app/uploads/test` ✓ |
| pipeline/detect.py | +45 lines logging | Shows processing steps | `docker logs \| grep "VIDEO PROCESSING"` ✓ |
| app/main.py | +80 lines logging | Shows subprocess errors | `docker logs \| grep "PIPELINE PROCESSING"` ✓ |
| app/db.py | (pre-existing changes) | run_id column support | See prior conversation |
| app/models.py | (pre-existing changes) | run_id in API schema | See prior conversation |
| 6 analytics files | (pre-existing changes) | run_id filtering | See prior conversation |
| Database | New column + index | Per-run event filtering | `psql -c "SELECT column_name FROM information_schema.columns WHERE table_name='events'"` |

---

## Deployment Command (One-Liner)

```bash
# Full deployment in sequence
docker-compose down && docker-compose build api --no-cache && docker-compose up -d && sleep 15 && docker exec -it store-intelligence-db psql -U postgres -d storedb -c "ALTER TABLE events ADD COLUMN run_id VARCHAR(50) NULL; CREATE INDEX idx_events_run_id ON events(run_id);" && echo "✓ Deployment complete"
```

---

## Verification Checklist

After deployment, run these to verify all changes applied:

```bash
# 1. Check Dockerfile system dependencies
docker exec store-intelligence-api dpkg -l | grep libgl1-mesa-glx
# Expected: ii  libgl1-mesa-glx:amd64 ... (installed)

# 2. Check uploads volume mounted
docker exec store-intelligence-api ls -la /app/uploads
# Expected: total 0 (directory exists)

# 3. Check logging appears in container
docker logs store-intelligence-api | grep "VIDEO PROCESSING"
# Expected: "=== VIDEO PROCESSING START ===" (from detect.py)

# 4. Check pipeline logging appears
docker logs store-intelligence-api | grep "PIPELINE PROCESSING"
# Expected: "=== PIPELINE PROCESSING START ===" (from main.py)

# 5. Check database migration applied
docker exec store-intelligence-db psql -U postgres -d storedb \
  -c "SELECT COUNT(*) as run_id_column_exists FROM information_schema.columns WHERE table_name='events' AND column_name='run_id';"
# Expected: run_id_column_exists = 1

# 6. Check index created
docker exec store-intelligence-db psql -U postgres -d storedb \
  -c "SELECT indexname FROM pg_indexes WHERE tablename='events' AND indexname LIKE '%run_id%';"
# Expected: idx_events_run_id (exists)
```

All checks passing = ✅ Production-ready
