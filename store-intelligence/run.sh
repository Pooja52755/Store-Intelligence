#!/bin/bash
# One command to process all clips -> events
# Usage: ./run.sh [clips_dir] [layout_file] [output_file] [store_id]

set -e

CLIPS_DIR="${1:-pipeline/input_clips}"
LAYOUT_FILE="${2:-events/store_layout.json}"
OUTPUT_FILE="${3:-events/events.jsonl}"
STORE_ID="${4:-STORE_BLR_002}"

echo "Starting pipeline..."
python pipeline/detect.py \
    --clips-dir "$CLIPS_DIR" \
    --layout "$LAYOUT_FILE" \
    --output "$OUTPUT_FILE" \
    --store-id "$STORE_ID"

echo "✓ Pipeline complete. Events written to $OUTPUT_FILE"
