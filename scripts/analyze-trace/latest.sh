#!/bin/bash
# Analyze the most recent trace file
# Run with: bash scripts/analyze-trace/latest.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Find the most recent trace file
LATEST_TRACE=$(ls -t ~/.pflow/debug/pflow-trace-*.json 2>/dev/null | head -1)

if [ -z "$LATEST_TRACE" ]; then
    echo "❌ No trace files found in ~/.pflow/debug/"
    exit 1
fi

echo "📋 Analyzing latest trace: $(basename $LATEST_TRACE)"

# Run the analyzer
uv run python "$SCRIPT_DIR/analyze.py" "$LATEST_TRACE"

# Get the output directory name
OUTPUT_DIR="$SCRIPT_DIR/output/$(basename $LATEST_TRACE .json)"

# Open in Cursor if available
if command -v cursor &> /dev/null; then
    echo "📂 Opening in Cursor..."
    cursor "$OUTPUT_DIR"
else
    echo "📁 View results at: $OUTPUT_DIR"
fi
