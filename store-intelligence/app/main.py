"""FastAPI main application with all endpoints and WebSocket support."""
import logging
import asyncio
import time
import uuid
import os
from contextlib import asynccontextmanager
from typing import Dict, List
from datetime import datetime, timezone

import structlog
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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
            store_id=request.path_params.get("store_id"),
            endpoint=request.url.path,
            method=request.method,
            status_code=response.status_code,
            latency_ms=latency_ms
        )
        
        return response
    
    except Exception as e:
        latency_ms = round((time.time() - start_time) * 1000, 2)
        
        log.error(
            "http_error",
            trace_id=trace_id,
            endpoint=request.url.path,
            method=request.method,
            error=str(e),
            latency_ms=latency_ms
        )
        
        raise


# ============================================================================
# ENDPOINTS
# ============================================================================

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
async def get_metrics(store_id: str):
    """
    GET /stores/{store_id}/metrics

    Store metrics for today.

    Returns:
    {
        "store_id": "STORE_BLR_002",
        "window": "today",
        "unique_visitors": 142,
        "conversion_rate": 0.31,
        "avg_dwell_by_zone": {"SKINCARE": 127.4, "BILLING": 243.1},
        "current_queue_depth": 3,
        "abandonment_rate": 0.18,
        "data_freshness": "2026-03-03T15:44:01Z"
    }

    Handles zero-visitor stores gracefully (no nulls, no 500s).
    Filters is_staff=FALSE for all customer metrics.
    """
    try:
        metrics = await metrics_service.get_metrics(store_id)
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
async def get_funnel(store_id: str):
    """
    GET /stores/{store_id}/funnel

    Conversion funnel (session-based counts).

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
        "count_basis": "sessions"
    }
    """
    try:
        funnel = await funnel_service.get_funnel(store_id)
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
async def get_heatmap(store_id: str):
    """
    GET /stores/{store_id}/heatmap

    Zone visit frequency and dwell time heatmap.

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
        ]
    }

    Scores normalized 0-100 (max zone = 100).
    data_confidence: HIGH (>=20), MEDIUM (5-19), LOW (<5) sessions.
    """
    try:
        heatmap = await heatmap_service.get_heatmap(store_id)
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
async def get_anomalies(store_id: str):
    """
    GET /stores/{store_id}/anomalies

    Active anomalies with RL-tuned thresholds.

    Detects:
    - BILLING_QUEUE_SPIKE: queue_depth > threshold for > 3 min (CRITICAL)
    - CONVERSION_DROP: today < 7-day avg × 0.7 (WARN)
    - DEAD_ZONE: no zone visits in 30 min (INFO)
    - STALE_FEED: last event > 10 min old (INFO)

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
        ]
    }
    """
    try:
        anomalies = await anomalies_service.get_anomalies(store_id)
        return anomalies
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
