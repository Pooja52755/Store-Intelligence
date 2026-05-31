#!/bin/bash
# Pipeline execution script
# Usage: bash run.sh /path/to/clips /path/to/store_layout.json [output_file] [store_id]

set -e

CLIPS_DIR="${1:-.}"
LAYOUT_FILE="${2:-.}"
OUTPUT_FILE="${3:-events/events.jsonl}"
STORE_ID="${4:-STORE_BLR_002}"

if [ ! -d "$CLIPS_DIR" ]; then
    echo "Error: clips directory '$CLIPS_DIR' not found"
    exit 1
fi

if [ ! -f "$LAYOUT_FILE" ]; then
    echo "Error: layout file '$LAYOUT_FILE' not found"
    exit 1
fi

# Create output directory
mkdir -p "$(dirname "$OUTPUT_FILE")"

# Run detection pipeline
python pipeline/detect.py \
    --clips-dir "$CLIPS_DIR" \
    --layout "$LAYOUT_FILE" \
    --output "$OUTPUT_FILE" \
    --store-id "$STORE_ID"

echo "✓ Pipeline complete. Events written to $OUTPUT_FILE"
