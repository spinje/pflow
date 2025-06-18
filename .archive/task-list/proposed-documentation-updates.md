# Proposed Documentation Updates

After thorough examination of current documentation, here are the specific updates needed following the single-source-of-truth principle:

## 1. Execution Tracing Details (UPDATE: runtime.md)

**Location**: `docs/core-concepts/runtime.md` - Add new section "7. Execution Tracing"

**Missing Content**:
- LLM token usage per node and total
- Cost estimation for LLM operations
- Shared store deltas (what keys were added/modified)
- Clear differentiation from conversation logs

User note: (before writing our own llm usage and cost tracking, we should try to leverage simon w llm, and claude codes output first (cli or python api))

**Proposed Addition**:
```markdown
## 7. Execution Tracing

### 7.1 Comprehensive Trace Output

When using `--trace`, pflow captures detailed execution information:

```
[1] github-get-issue (0.3s)
    Input: {"issue": 1234}
    Output: {"title": "Bug: Login fails", "body": "..."}
    Shared Store Δ: +issue, +issue_title

[2] claude-code (45.2s, 1523 tokens, $0.0234)
    Input: {"prompt": "Implement fix for: Bug: Login fails..."}
    Output: {"code_report": "Modified auth.py, added tests..."}
    Shared Store Δ: +code_report, +files_modified
    Cache: MISS

[3] git-commit (0.1s)
    Input: {"message": "Fix login bug (#1234)"}
    Output: {"commit_hash": "abc123"}
    Shared Store Δ: +commit_hash
```

### 7.2 Trace vs Conversation Logs

Unlike conversation logs (e.g., Claude's interactive dialogue), execution traces:
- Show deterministic step-by-step execution
- Track resource usage (tokens, costs, time)
- Capture data flow through shared store
- Enable performance optimization
```

## 2. Shell Pipe Advanced Features (UPDATE: shell-pipes.md)

**Location**: `docs/features/shell-pipes.md` - Expand section "Detailed Functionality and Workflow"

**Missing Content**:
- Streaming support for large files
- Exit code propagation
- Signal handling (Ctrl+C)
- stdout chaining capabilities

**Proposed Addition** (after line 70):
```markdown
### Advanced Unix Integration

Beyond basic stdin detection, pflow provides full Unix citizenship:

1. **Streaming Support**: Large files are processed in chunks without loading entirely into memory
   ```bash
   cat 1GB-log.txt | pflow analyze-errors  # Streams, doesn't load 1GB
   ```

2. **Exit Code Propagation**: Enables shell scripting integration
   ```bash
   pflow analyze || echo "Analysis failed"  # Proper exit codes
   ```

3. **Signal Handling**: Graceful interruption support
   ```bash
   # Ctrl+C during execution cleanly stops workflow
   ```

4. **stdout Chaining**: Output to next command
   ```bash
   pflow extract-errors | grep CRITICAL | wc -l
   ```
```

## 3. Natural Interface Pattern (NEW SECTION in simple-nodes.md)

**Location**: `docs/features/simple-nodes.md` - Add new section "4. Natural Interface Pattern"

**Missing Content**:
- Explicit documentation of consistent key naming conventions
- Why this pattern reduces cognitive load

**Proposed Addition**:
```markdown
## 4. Natural Interface Pattern

### 4.1 Consistent Key Naming

All pflow nodes follow predictable shared store key patterns:

**File Operations**:
- `shared["file_path"]` - Path to file
- `shared["content"]` - File contents
- `shared["encoding"]` - File encoding

**GitHub Operations**:
- `shared["issue"]` - Issue object/details
- `shared["repo"]` - Repository name
- `shared["pr"]` - Pull request details

**Git Operations**:
- `shared["commit_message"]` - Commit message
- `shared["branch"]` - Branch name
- `shared["commit_hash"]` - Result of commit

**LLM Operations**:
- `shared["prompt"]` - Input prompt
- `shared["response"]` - LLM response

### 4.2 Benefits

This consistency:
- Reduces cognitive load when composing workflows
- Makes workflows self-documenting
- Enables node composition without checking documentation
- Provides intuitive data flow between nodes
```

## 4. Workflow Storage Details (UPDATE: planner.md)

**Location**: `docs/features/planner.md` - Expand section 11 "User Verification & Approval"

**Missing Content**:
- Workflow naming prompts
- Pattern recognition for reuse
- Parameter extraction details

**Proposed Addition** (after line 490):
```markdown
### 11.3 Workflow Storage & Reuse

After approval, the system prompts for workflow storage:

```bash
# First execution
pflow "fix github issue 1234"
# System: "Save this workflow as 'fix-issue'? [Y/n]"

# Subsequent uses with different parameters
pflow fix-issue --issue=5678
pflow fix-issue --issue=9012 --priority=high
```

The system recognizes patterns:
- Common parameter variations
- Frequently used node combinations
- Team-specific workflow idioms

This enables the "Plan Once, Run Forever" philosophy where orchestration logic is captured once and reused indefinitely.
```

## 5. Integration Guide Principle (UPDATE: pflow-pocketflow-integration-guide.md)

**Location**: `docs/architecture/pflow-pocketflow-integration-guide.md` - Add to "Implementation Principles"

**Missing Content**:
- The "Extend, Don't Wrap" meta-principle

**Proposed Addition** (after line 261):
```markdown
## The Core Principle: "Extend, Don't Wrap"

This principle guides every architectural decision:
- Extend pocketflow.Node directly, don't create wrapper classes
- Extend shared dict with validation functions, don't wrap in classes
- Extend CLI patterns, don't reinvent parsing
- Use pocketflow.Flow directly, don't reimplement orchestration

This prevents the "framework on framework" anti-pattern and keeps pflow as a thin, focused layer.
```

## Summary

These five documentation updates address the truly missing content:
1. **Execution tracing details** - Token usage, costs, shared store deltas
2. **Advanced shell pipe features** - Streaming, signals, exit codes
3. **Natural interface pattern** - Explicit documentation of consistent naming
4. **Workflow storage mechanics** - How saving and reuse actually works
5. **"Extend, Don't Wrap" principle** - The meta-principle guiding architecture

All other insights from the reflection are already well-documented across various files.
