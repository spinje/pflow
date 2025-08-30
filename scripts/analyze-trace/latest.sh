#!/bin/bash
# Analyze the most recent trace file
# Run with: bash scripts/analyze-trace/latest.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Find the most recent trace file (planner or workflow)
LATEST_TRACE=$(ls -t ~/.pflow/debug/planner-trace-*.json ~/.pflow/debug/workflow-trace-*.json 2>/dev/null | head -1)

if [ -z "$LATEST_TRACE" ]; then
    echo "❌ No trace files found in ~/.pflow/debug/"
    echo ""
    echo "Looking for: planner-trace-*.json or workflow-trace-*.json"
    exit 1
fi

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
