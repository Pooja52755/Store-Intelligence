#!/usr/bin/env python3
"""
Comprehensive testing script to verify all fixes are working.
Run this after deployment to validate the system.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from datetime import datetime, timezone

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_imports():
    """Test that all critical imports work."""
    logger.info("\n=== Testing Imports ===")
    try:
        import cv2
        logger.info(f"✅ OpenCV {cv2.__version__} imported successfully")
    except ImportError as e:
        logger.error(f"❌ OpenCV import failed: {e}")
        return False
    
    try:
        from ultralytics import YOLO
        logger.info("✅ YOLO imported successfully")
    except ImportError as e:
        logger.error(f"❌ YOLO import failed: {e}")
        return False
    
    try:
        from pipeline.emit import Event, build_event
        logger.info("✅ Pipeline emit module imported successfully")
    except ImportError as e:
        logger.error(f"❌ Pipeline emit import failed: {e}")
        return False
    
    return True

async def test_event_generation():
    """Test that events are generated with run_id."""
    logger.info("\n=== Testing Event Generation ===")
    try:
        from pipeline.emit import build_event
        from datetime import datetime, timezone
        
        # Create a test event
        event = build_event(
            store_id="STORE_BLR_002",
            camera_id="CAM1",
            visitor_id="VIS_TEST",
            event_type="ENTRY",
            timestamp_dt=datetime.now(timezone.utc),
            confidence=0.9,
            is_staff=False,
            zone_id="entry",
            run_id="test-run-uuid"
        )
        
        # Verify run_id is set
        if event.run_id == "test-run-uuid":
            logger.info(f"✅ Event generated with run_id: {event.run_id}")
            logger.info(f"   Event data: {event.model_dump()}")
            return True
        else:
            logger.error(f"❌ Event run_id not set correctly: {event.run_id}")
            return False
    except Exception as e:
        logger.error(f"❌ Event generation failed: {e}", exc_info=True)
        return False

async def test_database_connection():
    """Test database connection and schema."""
    logger.info("\n=== Testing Database Connection ===")
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text
        
        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/storedb"
        )
        
        engine = create_async_engine(database_url, echo=False)
        
        async with engine.begin() as conn:
            # Test connection
            result = await conn.execute(text("SELECT 1"))
            logger.info("✅ Database connection successful")
            
            # Check run_id column exists
            result = await conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'events' AND column_name = 'run_id'
            """))
            if result.scalar() is not None:
                logger.info("✅ Column 'run_id' exists in events table")
            else:
                logger.warning("⚠️  Column 'run_id' does NOT exist - migration needed")
                return False
            
            # Get event count
            result = await conn.execute(text("SELECT COUNT(*) FROM events"))
            count = result.scalar()
            logger.info(f"✅ Total events in database: {count}")
        
        await engine.dispose()
        return True
    except Exception as e:
        logger.error(f"❌ Database test failed: {e}", exc_info=True)
        return False

async def test_metrics_service():
    """Test metrics service accepts run_id parameter."""
    logger.info("\n=== Testing Metrics Service ===")
    try:
        from app.metrics import MetricsService
        import inspect
        
        service = MetricsService()
        sig = inspect.signature(service.get_metrics)
        params = list(sig.parameters.keys())
        
        if 'run_id' in params:
            logger.info(f"✅ MetricsService.get_metrics has run_id parameter: {params}")
            return True
        else:
            logger.error(f"❌ MetricsService.get_metrics missing run_id parameter: {params}")
            return False
    except Exception as e:
        logger.error(f"❌ Metrics service test failed: {e}", exc_info=True)
        return False

async def test_emit_module():
    """Test emit module has run_id field and parameter."""
    logger.info("\n=== Testing Emit Module ===")
    try:
        from pipeline.emit import Event, build_event
        import inspect
        
        # Check Event class has run_id field
        event_fields = Event.model_fields.keys()
        if 'run_id' in event_fields:
            logger.info(f"✅ Event class has run_id field")
        else:
            logger.error(f"❌ Event class missing run_id field. Fields: {list(event_fields)}")
            return False
        
        # Check build_event has run_id parameter
        sig = inspect.signature(build_event)
        params = list(sig.parameters.keys())
        if 'run_id' in params:
            logger.info(f"✅ build_event function has run_id parameter: {params}")
            return True
        else:
            logger.error(f"❌ build_event missing run_id parameter: {params}")
            return False
    except Exception as e:
        logger.error(f"❌ Emit module test failed: {e}", exc_info=True)
        return False

async def test_events_jsonl_structure():
    """Test that events.jsonl has correct structure."""
    logger.info("\n=== Testing events.jsonl Structure ===")
    try:
        events_file = Path("events/events.jsonl")
        if not events_file.exists():
            logger.warning(f"⚠️  {events_file} does not exist yet (expected for new deployment)")
            return True
        
        with open(events_file, 'r') as f:
            lines = f.readlines()
        
        if len(lines) == 0:
            logger.warning("⚠️  events.jsonl is empty")
            return True
        
        # Check first event
        first_event = json.loads(lines[0])
        required_fields = ['event_id', 'store_id', 'visitor_id', 'event_type', 'timestamp']
        missing_fields = [f for f in required_fields if f not in first_event]
        
        if missing_fields:
            logger.error(f"❌ First event missing required fields: {missing_fields}")
            return False
        
        logger.info(f"✅ events.jsonl has {len(lines)} events")
        logger.info(f"   First event keys: {list(first_event.keys())}")
        
        # Check if any events have run_id
        has_run_id = 0
        for line in lines[:min(100, len(lines))]:
            event = json.loads(line)
            if 'run_id' in event and event['run_id'] is not None:
                has_run_id += 1
        
        if has_run_id > 0:
            logger.info(f"✅ {has_run_id} events have run_id set (out of {min(100, len(lines))} checked)")
        else:
            logger.warning(f"⚠️  No events have run_id set in first {min(100, len(lines))} events")
        
        return True
    except Exception as e:
        logger.error(f"❌ events.jsonl test failed: {e}", exc_info=True)
        return False

async def run_all_tests():
    """Run all tests and report results."""
    logger.info("=" * 70)
    logger.info("COMPREHENSIVE SYSTEM VALIDATION TESTS")
    logger.info("=" * 70)
    
    tests = [
        ("Imports", test_imports),
        ("Event Generation", test_event_generation),
        ("Emit Module Structure", test_emit_module),
        ("Metrics Service", test_metrics_service),
        ("Database Connection", test_database_connection),
        ("events.jsonl Structure", test_events_jsonl_structure),
    ]
    
    results = {}
    for test_name, test_func in tests:
        try:
            result = await test_func()
            results[test_name] = result
        except Exception as e:
            logger.error(f"Unexpected error in {test_name}: {e}", exc_info=True)
            results[test_name] = False
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status:8} | {test_name}")
    
    logger.info("=" * 70)
    logger.info(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 ALL TESTS PASSED - System is ready!")
    else:
        logger.warning(f"⚠️  {total - passed} test(s) failed - Review logs above")
    
    return passed == total

if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1)
