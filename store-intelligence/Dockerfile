FROM python:3.11-slim

WORKDIR /app

# Install minimal system dependencies for OpenCV and video processing
# These are the ONLY packages needed for opencv-python in Debian Bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libx11-6 \
    libgl1 \
    libgomp1 \
    ffmpeg \
    libavcodec-extra \
    git \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Verify OpenCV imports (fail fast if dependencies missing)
RUN python -c "import cv2; print(f'OpenCV {cv2.__version__} loaded successfully')"

# Copy application code
COPY app/ /app/app/
COPY pipeline/ /app/pipeline/
COPY events/store_layout.json /app/store_layout.json
COPY yolov8n.pt /app/yolov8n.pt

# Create events directory
RUN mkdir -p /app/events /app/uploads

# Expose port
EXPOSE 8000

# Health check (removed request import since it may not be available)
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8000), timeout=5)" || exit 1

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
