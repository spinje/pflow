#!/bin/bash
# Script to generate all test workflow files for Task 85 v3 manual testing
# Version 3: Fixed shell commands, added partial resolution tests

echo "Generating test workflow files for Task 85 Manual Testing v3..."
echo "This version fixes all shell command issues and includes partial resolution tests."
echo ""

# Clean up any existing test files
rm -f test-*.json 2>/dev/null

# Test 1.1: Basic Success Path
cat > test-success.json << 'EOF'
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "producer",
      "type": "shell",
      "params": {"command": "echo", "args": ["Hello World"]}
    },
    {
      "id": "consumer",
      "type": "shell",
      "params": {"command": "echo", "args": ["Got: ${producer.stdout}"]}
    }
  ],
  "edges": [{"from": "producer", "to": "consumer", "action": "default"}]
}
EOF

# Test 1.2: Strict Mode Failure
cat > test-strict-fail.json << 'EOF'
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "will-fail",
      "type": "shell",
      "params": {"command": "echo", "args": ["Value: ${missing}"]}
    }
  ],
  "edges": []
}
EOF

# Test 1.3: Permissive Mode Warning
cat > test-permissive.json << 'EOF'
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "permissive",
  "nodes": [
    {
      "id": "will-warn",
      "type": "shell",
      "params": {"command": "echo", "args": ["Value: ${missing}"]}
    }
  ],
  "edges": []
}
EOF

# Test 2.1: Partial Resolution Detection (Issue #96)
cat > test-partial.json << 'EOF'
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "name-provider",
      "type": "shell",
      "params": {"command": "echo", "args": ["Alice"]}
    },
    {
      "id": "builder",
      "type": "shell",
      "params": {
        "command": "echo",
        "args": ["User ${name-provider.stdout} has ${missing_count} items"]
      }
    }
  ],
  "edges": [{"from": "name-provider", "to": "builder", "action": "default"}]
}
EOF

# Test 2.2: Complete Multi-Variable Resolution
cat > test-multi-complete.json << 'EOF'
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "name",
      "type": "shell",
      "params": {"command": "echo", "args": ["Alice"]}
    },
    {
      "id": "count",
      "type": "shell",
      "params": {"command": "echo", "args": ["5"]}
    },
    {
      "id": "builder",
      "type": "shell",
      "params": {
        "command": "echo",
        "args": ["User ${name.stdout} has ${count.stdout} items"]
      }
    }
  ],
  "edges": [
    {"from": "name", "to": "count", "action": "default"},
    {"from": "count", "to": "builder", "action": "default"}
  ]
}
EOF

# Test 2.3: Three Variable Partial Resolution
cat > test-three-partial.json << 'EOF'
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "greeting",
      "type": "shell",
      "params": {"command": "echo", "args": ["Hello"]}
    },
    {
      "id": "name",
      "type": "shell",
      "params": {"command": "echo", "args": ["Alice"]}
    },
    {
      "id": "message",
      "type": "shell",
      "params": {
        "command": "echo",
        "args": ["${greeting.stdout} ${name.stdout}, you have ${count.stdout} items"]
      }
    }
  ],
  "edges": [
    {"from": "greeting", "to": "name", "action": "default"},
    {"from": "name", "to": "message", "action": "default"}
  ]
}
EOF

# Test 3.1: Issue #95 - Empty stdout
cat > test-issue-95.json << 'EOF'
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "produce-nothing",
      "type": "shell",
      "params": {"command": "true"}
    },
    {
      "id": "use-stdout",
      "type": "shell",
      "params": {
        "command": "echo",
        "args": ["Sending to API: ${produce-nothing.stdout}"]
      }
    }
  ],
  "edges": [{"from": "produce-nothing", "to": "use-stdout", "action": "default"}]
}
EOF

# Test 4.1: Configuration Override
cat > test-override.json << 'EOF'
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "test",
      "type": "shell",
      "params": {"command": "echo", "args": ["${missing}"]}
    }
  ]
}
EOF

# Test 6.1: MCP False Positive Prevention (Fixed Design)
cat > test-mcp-false-positive.json << 'EOF'
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "mcp-sim",
      "type": "shell",
      "params": {
        "command": "echo",
        "args": ["The old format used $OLD_VAR in templates"]
      }
    },
    {
      "id": "processor",
      "type": "shell",
      "params": {
        "command": "echo",
        "args": ["MCP said: ${mcp-sim.stdout}"]
      }
    }
  ],
  "edges": [{"from": "mcp-sim", "to": "processor", "action": "default"}]
}
EOF

# Test 6.2: Empty Value Resolution
cat > test-empty.json << 'EOF'
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "empty",
      "type": "shell",
      "params": {"command": "echo", "args": [""]}
    },
    {
      "id": "consumer",
      "type": "shell",
      "params": {"command": "echo", "args": ["[${empty.stdout}]"]}
    }
  ],
  "edges": [{"from": "empty", "to": "consumer", "action": "default"}]
}
EOF

# Test 6.3: Similar Variable Names
cat > test-similar-names.json << 'EOF'
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "user",
      "type": "shell",
      "params": {"command": "echo", "args": ["Alice"]}
    },
    {
      "id": "display",
      "type": "shell",
      "params": {
        "command": "echo",
        "args": ["User: ${user.stdout}, Username: ${username.stdout}"]
      }
    }
  ],
  "edges": [{"from": "user", "to": "display", "action": "default"}]
}
EOF

# Test 7.1: Helpful Suggestions
cat > test-suggestions.json << 'EOF'
{
  "ir_version": "0.1.0",
  "template_resolution_mode": "strict",
  "nodes": [
    {
      "id": "data-producer",
      "type": "shell",
      "params": {"command": "echo", "args": ["test"]}
    },
    {
      "id": "consumer",
      "type": "shell",
      "params": {
        "command": "echo",
        "args": ["${data-producer.output}"]
      }
    }
  ],
  "edges": [{"from": "data-producer", "to": "consumer", "action": "default"}]
}
EOF

echo ""
echo "✅ Generated 12 test workflow files:"
echo ""
ls -1 test-*.json | sort
echo ""
echo "Ready for manual testing! Follow instructions in MANUAL-TESTING-PLAN-v3.md"
echo ""
echo "Quick test commands:"
echo "  uv run pflow test-success.json        # Should succeed"
echo "  uv run pflow test-strict-fail.json    # Should fail with clean error"
echo "  uv run pflow test-partial.json        # Should fail (Issue #96 fix)"
echo "  uv run pflow test-issue-95.json       # Should fail (Issue #95 fix)"
echo ""
echo "To run all critical tests:"
echo "  for test in test-success.json test-strict-fail.json test-partial.json test-issue-95.json; do"
echo "    echo \"Testing: \$test\""
echo "    uv run pflow \$test"
echo "    echo \"---\""
echo "  done"
