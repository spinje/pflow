#!/bin/bash
# Compare the two most recent trace files
# Run with: bash scripts/analyze-trace/compare-latest.sh

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Find the two most recent trace files
TRACE1=$(ls -t ~/.pflow/debug/pflow-trace-*.json 2>/dev/null | sed -n '2p')
TRACE2=$(ls -t ~/.pflow/debug/pflow-trace-*.json 2>/dev/null | sed -n '1p')

if [ -z "$TRACE1" ] || [ -z "$TRACE2" ]; then
    echo "❌ Need at least 2 trace files in ~/.pflow/debug/"
    echo ""
    echo "Available traces:"
    ls -t ~/.pflow/debug/pflow-trace-*.json 2>/dev/null | head -5
    exit 1
fi

echo "🔍 Comparing traces:"
echo "  Older: $(basename $TRACE1)"
echo "  Newer: $(basename $TRACE2)"
echo ""

# Run the comparison
uv run python "$SCRIPT_DIR/compare.py" "$TRACE1" "$TRACE2"
