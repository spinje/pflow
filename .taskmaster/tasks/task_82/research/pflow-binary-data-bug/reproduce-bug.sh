#!/bin/bash

# Script to reproduce the binary data crash bug in pflow

echo "=== Reproducing pflow Binary Data Crash Bug ==="
echo ""
echo "This will attempt to download an image using HTTP node and crash"
echo "Expected error: AttributeError: 'str' object has no attribute 'get'"
echo ""
echo "Running test case..."
echo ""

# Run the test workflow
cd /Users/andfal/projects/pflow
uv run pflow scratchpads/pflow-binary-data-bug/test-case.json

echo ""
echo "=== Bug Reproduction Complete ==="
echo ""
echo "If you saw 'AttributeError: 'str' object has no attribute 'get'', the bug is confirmed."
echo "The crash occurs in src/pflow/runtime/instrumented_wrapper.py:867"
echo ""
echo "To fix, add type check in _extract_error_code() method:"
echo "    if not isinstance(output, dict):"
echo "        return None"
