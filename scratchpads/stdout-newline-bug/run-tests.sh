#!/bin/bash
# Run all test cases and show results
# Requires: pflow in PATH (or run with `uv run pflow` substituted)

set -e
cd "$(dirname "$0")"

# Use uv run pflow if pflow not directly available
if command -v pflow &> /dev/null; then
    PFLOW="pflow"
else
    PFLOW="uv run pflow"
fi

echo "=========================================="
echo "STDOUT NEWLINE BUG - REPRODUCTION TESTS"
echo "=========================================="
echo ""

# Cleanup
rm -f bugdemo*.txt testfile*.txt myfile*.txt 2>/dev/null || true

echo "TEST 1: Raw stdout contains trailing newline"
echo "----------------------------------------------"
$PFLOW test-raw-stdout.json 2>&1 | tail -5
echo ""
echo "Look for '0a' at the end - that's the newline byte (0x0a)"
echo ""

echo "TEST 2: JSON path traversal strips newline (WORKS)"
echo "---------------------------------------------------"
$PFLOW test-json-path.json 2>&1 | grep -E "✓|completed"
echo ""
echo "Checking created file:"
python3 -c "import os; files = [f for f in os.listdir('.') if 'testfile' in f]; print('  Files:', [repr(f) for f in files])"
echo "  ^ No newline in filename - JSON path traversal works!"
echo ""

echo "TEST 3: Raw stdout corrupts filename (THE BUG)"
echo "-----------------------------------------------"
$PFLOW test-filename-corruption.json 2>&1 | grep -E "✓|completed"
echo ""
echo "Checking created file:"
python3 -c "import os; files = [f for f in os.listdir('.') if 'bugdemo' in f]; print('  Files:', [repr(f) for f in files])"
echo "  ^ Notice the \\n in the filename - THIS IS THE BUG"
echo ""
echo "Try to access normally:"
cat bugdemo.txt 2>&1 | sed 's/^/  /' || true
echo ""

echo "TEST 4: Inline object escapes then jq un-escapes"
echo "-------------------------------------------------"
$PFLOW test-inline-object.json 2>&1 | tail -10
echo ""

echo "=========================================="
echo "SUMMARY"
echo "=========================================="
echo "- Raw \${node.stdout} preserves trailing newline"
echo "- \${node.stdout.field} strips newline (JSON parsing)"
echo "- Using raw stdout in file_path creates corrupted filenames"
echo "- Workaround: Use JSON output + path traversal, or add 'tr -d \\n'"
echo ""

# Cleanup
rm -f bugdemo*.txt testfile*.txt myfile*.txt 2>/dev/null || true
