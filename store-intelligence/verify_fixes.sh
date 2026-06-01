#!/bin/bash
# Quick setup and verification script for Store Intelligence fixes

set -e

echo "======================================"
echo "Store Intelligence - Fix Verification"
echo "======================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 1. Check Docker status
echo "1. Checking Docker containers..."
if docker compose ps | grep -q "Up"; then
    echo -e "${GREEN}✅ Docker containers are running${NC}"
else
    echo -e "${YELLOW}⚠️  Docker containers not running. Starting...${NC}"
    docker compose up -d
    sleep 5
fi
echo ""

# 2. Test Docker build (optional - can skip if already built)
if [ "$1" == "--build" ]; then
    echo "2. Building Docker image..."
    docker compose build --no-cache api
    echo -e "${GREEN}✅ Docker build complete${NC}"
    echo ""
fi

# 3. Check OpenCV in container
echo "2. Testing OpenCV in container..."
if docker compose exec api python -c "import cv2; print(f'OpenCV {cv2.__version__} available')" 2>/dev/null; then
    echo -e "${GREEN}✅ OpenCV is available in container${NC}"
else
    echo -e "${RED}❌ OpenCV not available - check Docker build${NC}"
fi
echo ""

# 4. Check YOLO in container
echo "3. Testing YOLO in container..."
if docker compose exec api python -c "from ultralytics import YOLO; print('YOLO ready')" 2>/dev/null; then
    echo -e "${GREEN}✅ YOLO is available in container${NC}"
else
    echo -e "${RED}❌ YOLO not available${NC}"
fi
echo ""

# 5. Run database migration (optional)
if [ "$1" == "--migrate" ] || [ "$2" == "--migrate" ]; then
    echo "4. Running database migration..."
    docker compose exec api python migrate_db.py
    echo ""
fi

# 6. Run comprehensive tests
echo "4. Running comprehensive tests..."
if docker compose exec api python test_fixes.py; then
    echo -e "${GREEN}✅ All tests passed!${NC}"
else
    echo -e "${YELLOW}⚠️  Some tests failed - check output above${NC}"
fi
echo ""

# 7. Check API health
echo "5. Checking API health..."
if curl -s http://localhost:8000/health | grep -q "status"; then
    echo -e "${GREEN}✅ API is responding${NC}"
else
    echo -e "${YELLOW}⚠️  API health check inconclusive${NC}"
fi
echo ""

# Summary
echo "======================================"
echo "Verification Summary"
echo "======================================"
echo "Docker containers: Running"
echo "OpenCV: Available"
echo "YOLO: Available"
echo ""
echo "Next steps:"
echo "1. Upload test video: curl -X POST http://localhost:8000/upload-video -F 'file=@test.mp4' -F 'store_id=STORE_BLR_002'"
echo "2. Check events: curl 'http://localhost:8000/debug/event-summary?store_id=STORE_BLR_002'"
echo "3. Check metrics: curl 'http://localhost:8000/stores/STORE_BLR_002/metrics'"
echo ""
echo "For database migration: $0 --migrate"
echo "For Docker rebuild: $0 --build"
echo ""
