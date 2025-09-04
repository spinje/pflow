# Manual Test Commands for Progress Indicators

Please run these commands in your **real terminal** (not through any automation) to verify progress indicators are working correctly.

## Quick Setup

First, create test workflows:

```bash
# 1. Create a simple multi-node workflow
cat > /tmp/test_progress.json << 'EOF'
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "step1", "type": "shell", "params": {"command": "echo 'Step 1 output'"}},
    {"id": "step2", "type": "shell", "params": {"command": "sleep 0.5 && echo 'Step 2 output'"}},
    {"id": "step3", "type": "shell", "params": {"command": "echo 'Step 3 output'"}}
  ],
  "edges": [
    {"from": "step1", "to": "step2"},
    {"from": "step2", "to": "step3"}
  ]
}
EOF

# 2. Create a single-node workflow
cat > /tmp/test_single.json << 'EOF'
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "hello", "type": "shell", "params": {"command": "echo 'Hello from workflow'"}}
  ],
  "edges": []
}
EOF
```

## Tests to Run

### Test 1: Basic Progress Display (Should Show Progress)
```bash
uv run pflow /tmp/test_progress.json
```

**✅ EXPECTED OUTPUT:**
```
Executing workflow (3 nodes):
  step1... ✓ 0.0s
  step2... ✓ 0.5s
  step3... ✓ 0.0s
Step 1 output
Step 2 output
Step 3 output
```

### Test 2: Single Node (Should Show Progress)
```bash
uv run pflow /tmp/test_single.json
```

**✅ EXPECTED OUTPUT:**
```
Executing workflow (1 nodes):
  hello... ✓ 0.0s
Hello from workflow
```

### Test 3: Natural Language (Should Show Planner + Execution Progress)
```bash
uv run pflow "echo hello world"
```

**✅ EXPECTED OUTPUT:**
```
workflow-discovery... ✓ X.Xs
generator... ✓ X.Xs
✅ Validation... ✓ X.Xs
Executing workflow (1 nodes):
  shell_XXX... ✓ 0.0s
hello world
```

### Test 4: Piped Input (Should NOT Show Progress)
```bash
echo "test" | uv run pflow /tmp/test_single.json
```

**✅ EXPECTED OUTPUT:**
```
Hello from workflow
```
(No progress indicators!)

### Test 5: Piped Output (Should NOT Show Progress)
```bash
uv run pflow /tmp/test_single.json | cat
```

**✅ EXPECTED OUTPUT:**
```
Hello from workflow
```
(No progress indicators!)

### Test 6: Force Non-Interactive with -p Flag (Should NOT Show Progress)
```bash
uv run pflow -p /tmp/test_single.json
```

**✅ EXPECTED OUTPUT:**
```
Hello from workflow
```
(No progress indicators even in terminal!)

### Test 7: JSON Mode (Should NOT Show Progress)
```bash
uv run pflow --output-format json /tmp/test_single.json | jq .
```

**✅ EXPECTED:** Valid JSON with no progress contamination

### Test 8: Verify Your Terminal is TTY
```bash
python3 -c "import sys; print('stdin TTY:', sys.stdin.isatty()); print('stdout TTY:', sys.stdout.isatty())"
```

**✅ EXPECTED IN REAL TERMINAL:**
```
stdin TTY: True
stdout TTY: True
```

### Test 9: Side-by-Side Comparison
```bash
echo "=== Test A: Direct execution (SHOULD show progress) ==="
uv run pflow /tmp/test_single.json

echo -e "\n=== Test B: With pipe (should NOT show progress) ==="
uv run pflow /tmp/test_single.json | cat

echo -e "\n=== Test C: With -p flag (should NOT show progress) ==="
uv run pflow -p /tmp/test_single.json
```

## Summary Table

| Scenario | Command | Progress Expected? |
|----------|---------|-------------------|
| Direct terminal | `uv run pflow workflow.json` | ✅ YES |
| Natural language | `uv run pflow "echo test"` | ✅ YES (planner + execution) |
| Piped stdin | `echo "x" \| uv run pflow workflow.json` | ❌ NO |
| Piped stdout | `uv run pflow workflow.json \| cat` | ❌ NO |
| -p flag | `uv run pflow -p workflow.json` | ❌ NO |
| JSON mode | `uv run pflow --output-format json workflow.json` | ❌ NO |

## What Success Looks Like

When it's working correctly:
1. Progress appears as `  node_name... ✓ X.Xs` format
2. Progress goes to stderr (may appear in red in some terminals)
3. Actual output goes to stdout
4. Header shows `Executing workflow (N nodes):`
5. Progress is suppressed when piped or with flags

## How to Report Results

Please run these tests and report back:
- Do you see progress indicators in Tests 1-3?
- Are progress indicators absent in Tests 4-7?
- What does Test 8 show for TTY status?

If you see progress in Tests 1-3 but NOT in Tests 4-7, then everything is working as designed!