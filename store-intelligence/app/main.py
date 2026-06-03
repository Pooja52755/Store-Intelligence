"""FastAPI main application with all endpoints and WebSocket support."""

import logging

import asyncio

import time

import uuid

import os

import shutil

from contextlib import asynccontextmanager

from typing import Dict, List, Optional

from datetime import datetime, timezone

from pathlib import Path



import structlog

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form

from fastapi.responses import JSONResponse

from fastapi.middleware.cors import CORSMiddleware

import redis.asyncio as redis



from app.models import (

    IngestionRequest,

    IngestionResponse,

    MetricsResponse,

    FunnelResponse,

    HeatmapResponse,

    AnomaliesResponse,

    HealthResponse

)

from app.db import db_manager

from app.graph import graph_manager

from app.ingestion import ingestion_service

from app.metrics import metrics_service

from app.funnel import funnel_service

from app.heatmap import heatmap_service

from app.anomalies import anomalies_service

from app.health import health_service

from app.rl_tuner import rl_tuner

from app.run_manager import run_manager



# Configure structured logging

structlog.configure(

    processors=[

        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,

    ],

    context_class=dict,

    logger_factory=structlog.stdlib.LoggerFactory(),

    cache_logger_on_first_use=True,

)



# Get logger

logger = logging.getLogger(__name__)

log = structlog.get_logger()



# WebSocket connection tracking

connected_clients: Dict[str, List[WebSocket]] = {}





@asynccontextmanager

async def lifespan(app: FastAPI):

    """Lifespan context manager for startup/shutdown."""

    # Startup

    logger.info("Starting up FastAPI application")

    await db_manager.init()

    await graph_manager.init()

    await ingestion_service.init_redis()

    await anomalies_service.init_redis()

    if not rl_tuner.load() and os.getenv("RL_TRAIN_ON_STARTUP", "true").lower() == "true":

        rl_tuner.train(timesteps=int(os.getenv("RL_TRAIN_TIMESTEPS", "1000")))

    yield

    # Shutdown

    logger.info("Shutting down")

    await db_manager.close()

    await graph_manager.close()





# Create FastAPI app

app = FastAPI(

    title="Store Intelligence API",

    description="Retail analytics and store intelligence",

    version="1.0.0",

    lifespan=lifespan

)



# Add CORS middleware

app.add_middleware(

    CORSMiddleware,

    allow_origins=["*"],

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"],

)





@app.middleware("http")

async def logging_middleware(request, call_next):

    """Add structured logging to all requests."""

    trace_id = str(uuid.uuid4())

    start_time = time.time()

    

    try:

        response = await call_next(request)

        

        latency_ms = round((time.time() - start_time) * 1000, 2)

        

        log.info(

            "http_request",

            trace_id=trace_id,

            endpoint=request.url.path,

            store_id=request.path_params.get("store_id") or "STORE_BLR_002",

            latency_ms=latency_ms,

            status_code=response.status_code

        )

        

        return response

    

    except Exception as e:

        latency_ms = round((time.time() - start_time) * 1000, 2)

        

        log.error(

            "http_error",

            trace_id=trace_id,

            endpoint=request.url.path,

            store_id=request.path_params.get("store_id") or "STORE_BLR_002",

            latency_ms=latency_ms,

        )

        raise





# ============================================================================

# ENDPOINTS

# ============================================================================



@app.post("/upload-video")

async def upload_video(

    file: UploadFile = File(...),

    store_id: str = Form(...),

    camera_id: str = Form(default="CAM_UPLOAD")

):

    """

    POST /upload-video

    

    Upload a video file and trigger pipeline processing with a new run_id.

    

    This endpoint:

    - Accepts a video file upload

    - Stores it in /clips/uploads/{run_id}/

    - Creates a new run with unique run_id

    - Triggers pipeline processing asynchronously

    - Returns run_id immediately for tracking

    

    Request (multipart/form-data):

        - file: Video file (mp4, avi, mov)

        - store_id: Store identifier

        - camera_id: Camera identifier (default: CAM_UPLOAD)

    

    Response:

        {

            "run_id": "uuid",

            "store_id": "STORE_BLR_002",

            "status": "PROCESSING",

            "message": "Video uploaded and pipeline started"

        }

    """

    try:

        # Validate file extension

        allowed_extensions = {".mp4", ".avi", ".mov", ".mkv"}

        file_ext = Path(file.filename).suffix.lower()

        if file_ext not in allowed_extensions:

            raise HTTPException(

                status_code=400,

                detail={

                    "error": "INVALID_FILE_TYPE",

                    "message": f"Allowed file types: {', '.join(allowed_extensions)}"

                }

            )

        

        # Create new run

        run_id = run_manager.create_run(store_id)

        

        # Try multiple possible upload directories (writable locations)

        upload_candidates = [

            Path("/app/uploads") / store_id / run_id,

            Path("/tmp/uploads") / store_id / run_id,

            Path("./uploads") / store_id / run_id,

        ]

        

        upload_dir = None

        for candidate in upload_candidates:

            try:

                candidate.mkdir(parents=True, exist_ok=True)

                # Test write permission

                test_file = candidate / ".write_test"

                test_file.touch()

                test_file.unlink()

                upload_dir = candidate

                break

            except (OSError, PermissionError):

                continue

        

        if upload_dir is None:

            logger.error("No writable upload directory found")

            raise HTTPException(

                status_code=503,

                detail={

                    "error": "SERVICE_UNAVAILABLE",

                    "message": "No writable storage available for uploads"

                }

            )

        

        # Save uploaded file

        file_path = upload_dir / file.filename

        try:

            with open(file_path, "wb") as buffer:

                shutil.copyfileobj(file.file, buffer)

        except (OSError, PermissionError) as e:

            logger.error(f"Failed to write file: {e}")

            raise HTTPException(

                status_code=503,

                detail={

                    "error": "SERVICE_UNAVAILABLE",

                    "message": "Failed to save uploaded file"

                }

            )

        

        logger.info(

            "Video uploaded: run_id=%s, store_id=%s, camera_id=%s, file=%s, size=%d, path=%s",

            run_id, store_id, camera_id, file.filename, file_path.stat().st_size, upload_dir

        )

        

        # Update run metadata

        run_manager.update_run_metadata(store_id, run_id, {

            "status": "PROCESSING",

            "uploaded_file": file.filename,

            "camera_id": camera_id,

            "upload_path": str(file_path)

        })

        

        # Trigger pipeline processing asynchronously

        asyncio.create_task(trigger_pipeline_processing(store_id, run_id, str(file_path), camera_id))

        

        return {

            "run_id": run_id,

            "store_id": store_id,

            "status": "PROCESSING",

            "message": "Video uploaded and pipeline started",

            "file_size_bytes": file_path.stat().st_size

        }

    

    except HTTPException:

        raise

    except Exception as e:

        log.error("upload_error", error=str(e))

        raise HTTPException(

            status_code=503,

            detail={

                "error": "SERVICE_UNAVAILABLE",

                "message": "Video upload failed",

                "trace_id": str(uuid.uuid4())

            }

        )





async def trigger_pipeline_processing(store_id: str, run_id: str, video_path: str, camera_id: str):

    """

    Trigger pipeline processing for uploaded video.

    

    This runs asynchronously after video upload.

    """

    try:

        import subprocess

        

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

        

        # Update run status to PROCESSING

        run_manager.update_run_metadata(store_id, run_id, {

            "status": "PROCESSING",

            "processing_started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        })

        

        # Construct pipeline command

        clips_dir = str(Path(video_path).parent)

        output_file = str(run_manager.get_events_file(store_id, run_id))

        

        cmd = [

            "python", "pipeline/detect.py",

            "--clips-dir", clips_dir,

            "--layout", "/app/store_layout.json",

            "--output", output_file,

            "--store-id", store_id,

            "--run-id", run_id,

            "--camera-id", camera_id

        ]

        

        logger.info("Pipeline command: %s", " ".join(cmd))

        

        # Run pipeline subprocess

        process = await asyncio.create_subprocess_exec(

            *cmd,

            stdout=asyncio.subprocess.PIPE,

            stderr=asyncio.subprocess.PIPE,

            cwd="/app"  # Ensure working directory is /app

        )

        

        logger.info("Pipeline subprocess started: PID %d", process.pid)

        

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

                "stderr": stderr_text[:500]  # Store first 500 chars of error

            })

        else:

            logger.info("=== PIPELINE PROCESSING SUCCEEDED ===")

            logger.info("Return code: %d", process.returncode)

            if stdout_text:

                logger.info("STDOUT:\n%s", stdout_text)

            

            # Count events generated

            events_file = run_manager.get_events_file(store_id, run_id)

            event_count = 0

            if events_file.exists():

                events_text = events_file.read_text().strip()

                event_count = len(events_text.split('\n')) if events_text else 0

                logger.info("Events file created: %s (%d events)", events_file, event_count)

            else:

                logger.warning("Events file not created: %s", events_file)

            

            # Ingest events into database first

            await ingest_run_events(store_id, run_id)



            run_manager.update_run_metadata(store_id, run_id, {

                "status": "COMPLETED",

                "processing_completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),

                "total_events": event_count

            })

            

    except Exception as e:

        logger.error("=== PIPELINE TRIGGER ERROR ===")

        logger.error("Error type: %s", type(e).__name__)

        logger.error("Error message: %s", str(e))

        logger.exception("Full traceback:")

        

        run_manager.update_run_metadata(store_id, run_id, {

            "status": "FAILED",

            "error": str(e)

        })

    





async def ingest_run_events(store_id: str, run_id: str):

    """

    Ingest events from a run into the database.

    """

    try:

        events_file = run_manager.get_events_file(store_id, run_id)

        if not events_file.exists():

            logger.warning("No events file found for run: run_id=%s", run_id)

            return

        

        # Read events from JSONL

        events = []

        with open(events_file, 'r') as f:

            for line in f:

                if line.strip():

                    import json

                    events.append(json.loads(line))

        

        logger.info("Ingesting events from run: run_id=%s, event_count=%d", run_id, len(events))

        

        # Batch ingest

        batch_size = 500

        for i in range(0, len(events), batch_size):

            batch = events[i:i+batch_size]

            # Convert to EventSchema and attach run_id

            from app.models import EventSchema

            event_schemas = []

            for e in batch:

                # Add run_id to event data before schema creation

                e['run_id'] = run_id

                event_schemas.append(EventSchema(**e))

            

            await ingestion_service.ingest_events(event_schemas)

        

        logger.info("Events ingested successfully: run_id=%s", run_id)

        

    except Exception as e:

        logger.error("ingest_run_events_error", run_id=run_id, error=str(e))









@app.get("/health", response_model=HealthResponse)

async def health():

    """

    Health check endpoint.

    

    Returns:

    - Overall system status

    - Per-store last event timestamp and feed status

    - Database, cache, graph connectivity

    """

    try:

        health_response = await health_service.check_health()

        return health_response

    except Exception as e:

        log.error("health_check_error", error=str(e))

        # Return 503 Service Unavailable with structured error

        raise HTTPException(

            status_code=503,

            detail={

                "error": "SERVICE_UNAVAILABLE",

                "message": "Health check failed",

                "trace_id": str(uuid.uuid4())

            }

        )





@app.post("/events/ingest", response_model=IngestionResponse)

async def ingest_events(request: IngestionRequest):

    """

    POST /events/ingest



    Ingest batch of events with deduplication.



    Features:

    - Accepts up to 500 events per batch

    - Validates each event against schema

    - Deduplicates by event_id (INSERT ... ON CONFLICT DO NOTHING)

    - Returns partial success on validation errors

    - Updates Redis live counters atomically

    - Publishes to WebSocket subscribers



    Request:

        {

            "events": [

                {

                    "event_id": "...",

                    "store_id": "STORE_BLR_002",

                    ...

                }

            ]

        }



    Response:

        {

            "accepted": 487,

            "rejected": 13,

            "errors": [{"event_id": "...", "reason": "..."}]

        }



    Idempotency:

        Calling twice with same payload produces same result (no duplicates).

    """

    try:

        if len(request.events) > 500:

            raise HTTPException(

                status_code=400,

                detail={

                    "error": "BATCH_TOO_LARGE",

                    "message": "Maximum 500 events per batch"

                }

            )

        

        response = await ingestion_service.ingest_events(request.events)

        return response

    

    except HTTPException:

        raise

    except Exception as e:

        log.error("ingest_error", error=str(e))

        raise HTTPException(

            status_code=503,

            detail={

                "error": "SERVICE_UNAVAILABLE",

                "message": "Event ingestion failed",

                "trace_id": str(uuid.uuid4())

            }

        )





@app.get("/stores/{store_id}/metrics", response_model=MetricsResponse)

async def get_metrics(store_id: str, run_id: Optional[str] = None):

    """

    GET /stores/{store_id}/metrics



    Store metrics for today or specific run.



    Query Parameters:

        run_id: Optional specific run_id to query (defaults to latest run)



    Returns:

    {

        "store_id": "STORE_BLR_002",

        "window": "today",

        "unique_visitors": 142,

        "conversion_rate": 0.31,

        "avg_dwell_by_zone": {"SKINCARE": 127.4, "BILLING": 243.1},

        "current_queue_depth": 3,

        "abandonment_rate": 0.18,

        "data_freshness": "2026-03-03T15:44:01Z",

        "run_id": "uuid"

    }



    Handles zero-visitor stores gracefully (no nulls, no 500s).

    Filters is_staff=FALSE for all customer metrics.

    """

    try:

        # Get latest run if not specified

        if run_id is None:

            run_id = run_manager.get_latest_run(store_id)

        

        metrics = await metrics_service.get_metrics(store_id, run_id=run_id)

        

        # Add run_id to response

        if run_id:

            metrics_dict = metrics.dict()

            metrics_dict["run_id"] = run_id

            return MetricsResponse(**metrics_dict)

        

        return metrics

    except Exception as e:

        log.error("metrics_error", store_id=store_id, error=str(e))

        raise HTTPException(

            status_code=503,

            detail={

                "error": "SERVICE_UNAVAILABLE",

                "message": "Could not retrieve metrics",

                "trace_id": str(uuid.uuid4())

            }

        )





@app.get("/stores/{store_id}/funnel", response_model=FunnelResponse)

async def get_funnel(store_id: str, run_id: Optional[str] = None):

    """

    GET /stores/{store_id}/funnel



    Conversion funnel (session-based counts).



    Query Parameters:

        run_id: Optional specific run_id to query (defaults to latest run)



    Stage counts = SESSIONS (each ENTRY/REENTRY opens one session).

    ``unique_visitors`` = distinct visitor_ids (matches metrics.unique_visitors).

    ``count_basis`` is always ``"sessions"``.



    Returns:

    {

        "funnel": [

            {"stage": "Entry Sessions", "count": 57, "dropoff_pct": 0},

            {"stage": "Zone Visit Sessions", "count": 57, "dropoff_pct": 0},

            ...

        ],

        "conversion_rate": 0.31,

        "unique_visitors": 14,

        "entry_sessions": 57,

        "count_basis": "sessions",

        "run_id": "uuid"

    }

    """

    try:

        # Get latest run if not specified

        if run_id is None:

            run_id = run_manager.get_latest_run(store_id)

        

        funnel = await funnel_service.get_funnel(store_id, run_id=run_id)

        

        # Add run_id to response

        if run_id:

            funnel_dict = funnel.dict()

            funnel_dict["run_id"] = run_id

            return FunnelResponse(**funnel_dict)

        

        return funnel

    except Exception as e:

        log.error("funnel_error", store_id=store_id, error=str(e))

        raise HTTPException(

            status_code=503,

            detail={

                "error": "SERVICE_UNAVAILABLE",

                "message": "Could not retrieve funnel",

                "trace_id": str(uuid.uuid4())

            }

        )





@app.get("/stores/{store_id}/journeys")

async def get_journeys(store_id: str, limit: int = 10):

    """

    GET /stores/{store_id}/journeys



    Top visitor journey paths from Neo4j knowledge graph.

    """

    try:

        paths = await graph_manager.get_visitor_journey_paths(store_id, limit=limit)

        return {"store_id": store_id, "journeys": paths}

    except Exception as e:

        log.error("journeys_error", store_id=store_id, error=str(e))

        raise HTTPException(status_code=503, detail={"error": str(e)})





@app.get("/stores/{store_id}/heatmap", response_model=HeatmapResponse)

async def get_heatmap(store_id: str, run_id: Optional[str] = None):

    """

    GET /stores/{store_id}/heatmap



    Zone visit frequency and dwell time heatmap.



    Query Parameters:

        run_id: Optional specific run_id to query (defaults to latest run)



    Returns:

    {

        "zones": [

            {

                "zone_id": "SKINCARE",

                "visit_count": 87,

                "avg_dwell_ms": 45200,

                "score": 100,

                "data_confidence": "HIGH"

            }

        ],

        "run_id": "uuid"

    }



    Scores normalized 0-100 (max zone = 100).

    data_confidence: HIGH (>=20), MEDIUM (5-19), LOW (<5) sessions.

    """

    try:

        # Get latest run if not specified

        if run_id is None:

            run_id = run_manager.get_latest_run(store_id)

        

        heatmap = await heatmap_service.get_heatmap(store_id, run_id=run_id)

        

        # Add run_id to response

        if run_id:

            heatmap_dict = heatmap.dict()

            heatmap_dict["run_id"] = run_id

            return HeatmapResponse(**heatmap_dict)

        

        return heatmap

    except Exception as e:

        log.error("heatmap_error", store_id=store_id, error=str(e))

        raise HTTPException(

            status_code=503,

            detail={

                "error": "SERVICE_UNAVAILABLE",

                "message": "Could not retrieve heatmap",

                "trace_id": str(uuid.uuid4())

            }

        )





@app.get("/stores/{store_id}/anomalies", response_model=AnomaliesResponse)

async def get_anomalies(store_id: str, run_id: Optional[str] = None):

    """

    GET /stores/{store_id}/anomalies



    Active anomalies with RL-tuned thresholds.



    Query Parameters:

        run_id: Optional specific run_id to query (defaults to latest run)



    Detects:

    - BILLING_QUEUE_SPIKE: queue_depth > threshold for > 3 min (CRITICAL)

    - CONVERSION_DROP: today < 7-day avg × 0.7 (WARN)

    - DEAD_ZONE: no zone visits in 30 min (INFO)



    Note: STALE_FEED is replaced with pipeline_status field.



    Returns:

    {

        "anomalies": [

            {

                "type": "BILLING_QUEUE_SPIKE",

                "severity": "CRITICAL",

                "detected_at": "2026-03-03T15:22:00Z",

                "details": {"queue_depth": 8, "duration_minutes": 4},

                "suggested_action": "Open additional billing counter immediately"

            }

        ],

        "pipeline_status": "LIVE",

        "run_id": "uuid"

    }

    """

    try:

        # Get latest run if not specified

        if run_id is None:

            run_id = run_manager.get_latest_run(store_id)

        

        # Get anomalies from service

        anomalies_response = await anomalies_service.get_anomalies(store_id, run_id=run_id)

        

        # Determine pipeline status based on run status

        pipeline_status = "LIVE"

        if run_id:

            run_metadata = run_manager.get_run_metadata(store_id, run_id)

            if run_metadata:

                status = run_metadata.get("status", "UNKNOWN")

                if status == "PROCESSING":

                    pipeline_status = "LIVE"

                elif status == "FAILED":

                    pipeline_status = "DEGRADED"

                elif status == "COMPLETED":

                    # Check if events exist

                    if run_metadata.get("total_events", 0) == 0:

                        pipeline_status = "NO_DATA"

                    else:

                        pipeline_status = "LIVE"

                else:

                    pipeline_status = "NO_DATA"

            else:

                pipeline_status = "NO_DATA"

        else:

            pipeline_status = "NO_DATA"

        

        # Filter out STALE_FEED anomalies (replaced with pipeline_status)

        filtered_anomalies = [a for a in anomalies_response.anomalies if a.type != "STALE_FEED"]

        

        # Add run_id and pipeline_status to response

        anomalies_dict = {

            "anomalies": filtered_anomalies,

            "run_id": run_id,

            "pipeline_status": pipeline_status,

            "provenance": anomalies_response.provenance

        }

        

        return AnomaliesResponse(**anomalies_dict)

    except Exception as e:

        log.error("anomalies_error", store_id=store_id, error=str(e))

        raise HTTPException(

            status_code=503,

            detail={

                "error": "SERVICE_UNAVAILABLE",

                "message": "Could not retrieve anomalies",

                "trace_id": str(uuid.uuid4())

            }

        )





@app.get("/debug/pipeline-status")

async def get_pipeline_status(store_id: str = "STORE_BLR_002"):

    """

    GET /debug/pipeline-status



    Debug endpoint for pipeline status and observability.



    Query Parameters:

        store_id: Store identifier (default: STORE_BLR_002)



    Returns:

    {

        "active_run_id": "uuid",

        "last_processed_timestamp": "2026-03-03T15:44:01Z",

        "events_count": 2238,

        "pipeline_status": "LIVE",

        "runs": [

            {

                "run_id": "uuid",

                "status": "COMPLETED",

                "created_at": "2026-03-03T15:44:01Z",

                "total_events": 2238,

                "total_frames": 5000,

                "processing_time_seconds": 120.5

            }

        ]

    }

    """

    try:

        latest_run_id = run_manager.get_latest_run(store_id)

        runs = run_manager.list_runs(store_id)

        

        # Get latest run metadata

        latest_metadata = None

        if latest_run_id:

            latest_metadata = run_manager.get_run_metadata(store_id, latest_run_id)

        

        return {

            "store_id": store_id,

            "active_run_id": latest_run_id,

            "last_processed_timestamp": latest_metadata.get("processing_completed_at") if latest_metadata else None,

            "events_count": latest_metadata.get("total_events", 0) if latest_metadata else 0,

            "pipeline_status": latest_metadata.get("status", "NO_DATA") if latest_metadata else "NO_DATA",

            "runs": runs

        }

    except Exception as e:

        log.error("pipeline_status_error", store_id=store_id, error=str(e))

        raise HTTPException(

            status_code=503,

            detail={

                "error": "SERVICE_UNAVAILABLE",

                "message": "Could not retrieve pipeline status",

                "trace_id": str(uuid.uuid4())

            }

        )





# ============================================================================

# DEBUG & RUN MANAGEMENT ENDPOINTS

# ============================================================================



@app.get("/runs")

async def list_runs(store_id: str = "STORE_BLR_002"):

    """

    GET /runs

    

    List all runs for a store.

    

    Query Parameters:

        store_id: Store identifier (default: STORE_BLR_002)

    

    Returns list of runs with metadata.

    """

    try:

        runs = run_manager.list_runs(store_id)

        return {"store_id": store_id, "runs": runs, "total": len(runs)}

    except Exception as e:

        log.error("list_runs_error", store_id=store_id, error=str(e))

        raise HTTPException(status_code=503, detail={"error": str(e)})





@app.get("/runs/{run_id}")

async def get_run(store_id: str, run_id: str):

    """

    GET /runs/{run_id}

    

    Get metadata for a specific run.

    """

    try:

        metadata = run_manager.get_run_metadata(store_id, run_id)

        if not metadata:

            raise HTTPException(status_code=404, detail={"error": "Run not found"})

        return metadata

    except HTTPException:

        raise

    except Exception as e:

        log.error("get_run_error", store_id=store_id, run_id=run_id, error=str(e))

        raise HTTPException(status_code=503, detail={"error": str(e)})





@app.get("/runs/{run_id}/metrics")

async def get_run_metrics(store_id: str, run_id: str):

    """

    GET /runs/{run_id}/metrics

    

    Get metrics for a specific run.

    """

    try:

        metadata = run_manager.get_run_metadata(store_id, run_id)

        if not metadata:

            raise HTTPException(status_code=404, detail={"error": "Run not found"})

        

        # Get metrics filtered by run_id

        metrics = await metrics_service.get_metrics(store_id, run_id=run_id)

        metrics_dict = metrics.dict()

        metrics_dict["run_id"] = run_id

        return MetricsResponse(**metrics_dict)

    except HTTPException:

        raise

    except Exception as e:

        log.error("get_run_metrics_error", store_id=store_id, run_id=run_id, error=str(e))

        raise HTTPException(status_code=503, detail={"error": str(e)})





@app.get("/runs/{run_id}/funnel")

async def get_run_funnel(store_id: str, run_id: str):

    """

    GET /runs/{run_id}/funnel

    

    Get funnel for a specific run.

    """

    try:

        metadata = run_manager.get_run_metadata(store_id, run_id)

        if not metadata:

            raise HTTPException(status_code=404, detail={"error": "Run not found"})

        

        # Get funnel filtered by run_id

        funnel = await funnel_service.get_funnel(store_id, run_id=run_id)

        funnel_dict = funnel.dict()

        funnel_dict["run_id"] = run_id

        return FunnelResponse(**funnel_dict)

    except HTTPException:

        raise

    except Exception as e:

        log.error("get_run_funnel_error", store_id=store_id, run_id=run_id, error=str(e))

        raise HTTPException(status_code=503, detail={"error": str(e)})





@app.get("/debug/run-status")

async def debug_run_status(store_id: str = "STORE_BLR_002"):

    """

    GET /debug/run-status

    

    Debug endpoint showing current run status and event counts.

    

    Returns:

    {

        "run_id": "uuid",

        "videos_processed": 1,

        "frames_processed": 5000,

        "events_generated": 2238,

        "visitors_detected": 14,

        "processing_time_sec": 45.2,

        "status": "COMPLETED"

    }

    """

    try:

        run_id = run_manager.get_latest_run(store_id)

        if not run_id:

            return {

                "run_id": None,

                "status": "NO_RUNS",

                "message": "No pipeline runs found for this store"

            }

        

        metadata = run_manager.get_run_metadata(store_id, run_id)

        if not metadata:

            return {"run_id": run_id, "status": "METADATA_ERROR"}

        

        # Get event count from metrics

        metrics = await metrics_service.get_metrics(store_id, run_id=run_id)

        

        return {

            "run_id": run_id,

            "store_id": store_id,

            "status": metadata.get("status", "UNKNOWN"),

            "created_at": metadata.get("created_at"),

            "processing_started_at": metadata.get("processing_started_at"),

            "processing_completed_at": metadata.get("processing_completed_at"),

            "videos_processed": len(metadata.get("videos_processed", [])),

            "total_events": metadata.get("total_events", 0),

            "total_frames": metadata.get("total_frames", 0),

            "processing_time_sec": metadata.get("processing_time_seconds", 0.0),

            "unique_visitors": metrics.unique_visitors,

            "entry_sessions": 0,

            "conversion_rate": metrics.conversion_rate

        }

    except Exception as e:

        log.error("debug_run_status_error", store_id=store_id, error=str(e))

        raise HTTPException(status_code=503, detail={"error": str(e)})





@app.get("/debug/event-summary")

async def debug_event_summary(store_id: str = "STORE_BLR_002", run_id: Optional[str] = None):

    """

    GET /debug/event-summary

    

    Debug endpoint showing event counts by type.

    

    Returns:

    {

        "run_id": "uuid",

        "total_events": 2238,

        "events_by_type": {

            "ENTRY": 14,

            "EXIT": 12,

            "ZONE_ENTER": 456,

            "ZONE_EXIT": 450,

            "ZONE_DWELL": 1200,

            "BILLING_QUEUE_JOIN": 50,

            "PURCHASE": 45,

            "BILLING_QUEUE_ABANDON": 5

        }

    }

    """

    try:

        session = await db_manager.get_session()

        try:

            # Build query

            q = select(DBEvent.event_type, func.count(DBEvent.event_id)).where(

                DBEvent.store_id == store_id

            )

            

            if run_id:

                q = q.where(DBEvent.run_id == run_id)

            else:

                # Default to latest run if not specified

                latest_run = run_manager.get_latest_run(store_id)

                if latest_run:

                    q = q.where(DBEvent.run_id == latest_run)

                    run_id = latest_run

            

            q = q.group_by(DBEvent.event_type)

            

            result = await session.execute(q)

            rows = result.all()

            

            events_by_type = {row[0]: row[1] for row in rows}

            total_events = sum(events_by_type.values())

            

            return {

                "run_id": run_id,

                "store_id": store_id,

                "total_events": total_events,

                "events_by_type": events_by_type

            }

        finally:

            await session.close()

    except Exception as e:

        log.error("debug_event_summary_error", store_id=store_id, error=str(e))

        raise HTTPException(status_code=503, detail={"error": str(e)})





# ============================================================================

# WebSocket ENDPOINT

# ============================================================================



@app.websocket("/ws/{store_id}")

async def websocket_endpoint(websocket: WebSocket, store_id: str):

    """

    WebSocket endpoint for live metrics streaming.



    Client connects: ws://localhost:8000/ws/STORE_BLR_002



    Server broadcasts:

    {

        "events_ingested": 5,

        "timestamp": "2026-03-03T15:44:01Z"

    }



    Every 30 seconds: keepalive ping

    """

    await websocket.accept()

    

    # Add client to connected list

    if store_id not in connected_clients:

        connected_clients[store_id] = []

    connected_clients[store_id].append(websocket)

    

    log.info("websocket_connect", store_id=store_id)

    

    try:

        while True:

            # Keep connection alive with periodic messages

            await asyncio.sleep(30)

            

            try:

                # Send keepalive

                await websocket.send_json({

                    "type": "keepalive",

                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

                })

            except Exception:

                break

    

    except WebSocketDisconnect:

        log.info("websocket_disconnect", store_id=store_id)

    

    finally:

        # Remove client

        if store_id in connected_clients:

            try:

                connected_clients[store_id].remove(websocket)

            except ValueError:

                pass





async def broadcast_update(store_id: str, message: dict):

    """Broadcast update to all connected clients for a store."""

    if store_id not in connected_clients:

        return

    

    disconnected = []

    

    for client in connected_clients[store_id]:

        try:

            await client.send_json(message)

        except Exception:

            disconnected.append(client)

    

    # Clean up disconnected clients

    for client in disconnected:

        try:

            connected_clients[store_id].remove(client)

        except ValueError:

            pass





# ============================================================================

# ERROR HANDLERS

# ============================================================================



@app.exception_handler(HTTPException)

async def http_exception_handler(request, exc):

    """Handle HTTP exceptions with structured response."""

    return JSONResponse(

        status_code=exc.status_code,

        content=exc.detail if isinstance(exc.detail, dict) else {

            "error": "HTTP_ERROR",

            "message": str(exc.detail),

            "trace_id": str(uuid.uuid4())

        }

    )





@app.exception_handler(Exception)

async def general_exception_handler(request, exc):

    """Handle unexpected exceptions gracefully."""

    log.error("unhandled_exception", error=str(exc))

    

    return JSONResponse(

        status_code=503,

        content={

            "error": "INTERNAL_SERVER_ERROR",

            "message": "An unexpected error occurred",

            "trace_id": str(uuid.uuid4())

        }

    )





# ============================================================================

# ROOT ENDPOINT

# ============================================================================



@app.get("/")

async def root():

    """Root endpoint with API info."""

    return {

        "name": "Store Intelligence API",

        "version": "1.0.0",

        "status": "operational",

        "docs": "/docs",

        "endpoints": {

            "health": "/health",

            "ingest": "POST /events/ingest",

            "metrics": "GET /stores/{store_id}/metrics",

            "funnel": "GET /stores/{store_id}/funnel",

            "heatmap": "GET /stores/{store_id}/heatmap",

            "anomalies": "GET /stores/{store_id}/anomalies",

            "websocket": "WS /ws/{store_id}"

        }

    }





if __name__ == "__main__":

    import uvicorn

    uvicorn.run(

        "main:app",

        host="0.0.0.0",

        port=8000,

        reload=False

    )

