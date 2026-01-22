# Task 115: Automatic Stdin Routing for Unix-First Piping

## Description

Enable Unix-style piping into workflows by automatically routing stdin to matching workflow inputs based on type detection. This makes `cat data.json | pflow transform.json | pflow analyze.json` work without special workflow configuration.

## Status
not started

## Priority

high

**Rationale:** Unix-first piping is foundational for target audience (developers, AI agent builders). Without it, "Unix-first" positioning lacks credibility. This is about marketing potential and developer trust, not just UX convenience.

## Problem

pflow's Unix-first positioning claims workflows are "first-class CLI citizens" that can be piped together. Currently this doesn't work:

```bash
# This fails:
echo '{"items": [1,2,3]}' | pflow workflow.json
# Error: Template variable ${stdin} has no valid source

# You have to do this instead:
pflow workflow.json data='{"items": [1,2,3]}'
```

**Root cause:**
1. CLI injects piped stdin into `shared_storage["stdin"]` during execution
2. Validation happens BEFORE execution and rejects `${stdin}` references
3. No automatic bridge between piped stdin and declared workflow inputs

**Current state:**
- `src/pflow/cli/main.py` line 262: `shared_storage["stdin"] = stdin_data.text_data`
- `_validate_before_execution()` runs at line 2164, before stdin injection
- Workflows can't reference `${stdin}` without validation failure

## Solution

Implement automatic stdin routing based on type matching:

### Algorithm

1. **Detect stdin type** by parsing the piped content:
   - `{"key": ...}` → object
   - `[...]` → array
   - `42`, `3.14` → number
   - `true`/`false` → boolean
   - Everything else → string

2. **Find matching inputs** in the workflow that accept this type

3. **Route automatically** based on match count:
   - **Exactly ONE match** → auto-route stdin to that input
   - **ZERO matches** → error: "Stdin type X doesn't match any input"
   - **MULTIPLE matches** → require explicit `"stdin": true` on one input

### Explicit Declaration for Ambiguous Cases

When multiple inputs match the stdin type:

```json
{
  "inputs": {
    "source_data": {"type": "string", "required": true, "stdin": true},
    "config_data": {"type": "string", "required": true}
  }
}
```

The `"stdin": true` flag marks which input receives piped data.

### Examples

**Case 1: Auto-routing (one string input)**
```json
{
  "inputs": {
    "data": {"type": "string", "required": true},
    "limit": {"type": "number", "default": 10}
  }
}
```
```bash
echo "hello world" | pflow workflow.json
# stdin is string, only one string input → routes to "data"
```

**Case 2: Auto-routing (one object input)**
```json
{
  "inputs": {
    "config": {"type": "object", "required": true}
  }
}
```
```bash
echo '{"debug": true}' | pflow workflow.json
# stdin parses as object, one object input → routes to "config"
```

**Case 3: Ambiguous (two string inputs)**
```json
{
  "inputs": {
    "source": {"type": "string", "required": true, "stdin": true},
    "template": {"type": "string", "required": true}
  }
}
```
```bash
echo "data" | pflow workflow.json template="Hello {name}"
# stdin routes to "source" (has stdin: true)
# "template" provided explicitly
```

**Case 4: Pipeline composition**
```bash
cat data.json | pflow transform.json | pflow analyze.json > report.md
# Each workflow has one matching input, auto-routes through pipeline
```

## Design Decisions

- **Type detection before validation**: Parse stdin early, include detected type in validation context
- **Conservative matching**: Only auto-route on exact type match, not coercion (string stdin won't route to object input)
- **Explicit override**: CLI param always wins over stdin (`pflow workflow.json data="override"` ignores stdin)
- **Error messages**: Clear errors for "no match" and "ambiguous" cases with suggestions

## Implementation Notes

### Files to Modify

1. **`src/pflow/cli/main.py`**:
   - Add `_detect_stdin_type(stdin_data)` → returns detected type
   - Add `_find_stdin_target(workflow_ir, stdin_type)` → returns input name or raises
   - Modify stdin handling to inject into `execution_params` before validation
   - Update `_validate_and_prepare_workflow_params()` to handle stdin routing

2. **`src/pflow/core/workflow_validator.py`**:
   - Add support for `"stdin": true` input declaration
   - Validate only one input has `stdin: true` per type

3. **`src/pflow/core/ir_schema.py`** (if exists):
   - Add `stdin` field to input schema

### Type Detection Logic

```python
def _detect_stdin_type(content: str) -> str:
    """Detect the type of stdin content."""
    content = content.strip()

    # Try JSON parse first
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return "object"
        elif isinstance(parsed, list):
            return "array"
        elif isinstance(parsed, bool):
            return "boolean"
        elif isinstance(parsed, (int, float)):
            return "number"
        else:
            return "string"
    except json.JSONDecodeError:
        pass

    # Not valid JSON - treat as string
    return "string"
```

### Stdin Target Resolution

```python
def _find_stdin_target(workflow_ir: dict, stdin_type: str) -> str:
    """Find which input should receive stdin."""
    inputs = workflow_ir.get("inputs", {})

    # First check for explicit stdin: true
    explicit = [name for name, spec in inputs.items()
                if spec.get("stdin") is True]
    if len(explicit) == 1:
        return explicit[0]
    if len(explicit) > 1:
        raise ValueError("Multiple inputs marked with stdin: true")

    # Auto-match by type
    matching = [name for name, spec in inputs.items()
                if spec.get("type") == stdin_type]

    if len(matching) == 1:
        return matching[0]
    elif len(matching) == 0:
        raise ValueError(f"No input accepts stdin type '{stdin_type}'")
    else:
        names = ", ".join(matching)
        raise ValueError(
            f"Multiple inputs accept type '{stdin_type}': {names}. "
            f"Add '\"stdin\": true' to one input to disambiguate."
        )
```

## Verification

1. **Basic piping works**:
   ```bash
   echo '{"items": [1,2,3]}' | pflow test-workflow.json
   ```

2. **Pipeline composition works**:
   ```bash
   cat data.json | pflow step1.json | pflow step2.json
   ```

3. **Type detection is accurate**:
   - JSON objects → object
   - JSON arrays → array
   - Numbers → number
   - Booleans → boolean
   - Plain text → string

4. **Ambiguous cases error clearly**:
   ```bash
   echo "text" | pflow two-string-inputs.json
   # Error: Multiple inputs accept type 'string': input1, input2.
   #        Add '"stdin": true' to one input to disambiguate.
   ```

5. **Explicit param overrides stdin**:
   ```bash
   echo "ignored" | pflow workflow.json data="used"
   # Uses "used", not "ignored"
   ```

6. **Backward compatibility**: Existing workflows without piping still work

## Additional Discovery: Output Side Also Broken

For full Unix piping (`workflow-a | workflow-b | workflow-c`), there are **TWO** issues:

### Issue 1: stdin routing (this task)
Piped input doesn't route to workflow inputs automatically.

### Issue 2: stdout output (separate but related)
Workflow output goes to **stderr by default**, not stdout. This breaks piping.

**Current behavior:**
```bash
pflow workflow.json count=3 > /tmp/stdout.txt 2> /tmp/stderr.txt
# STDOUT: (empty)
# STDERR: ✓ Workflow completed... [output value here]
```

**Reason:** `src/pflow/cli/main.py` lines 372-378 - when non-interactive (piped), everything goes to stderr to preserve ordering.

**Workaround:** The `-p` (print) flag outputs to stdout:
```bash
pflow -p workflow.json count=3 > /tmp/stdout.txt 2> /tmp/stderr.txt
# STDOUT: [output value here]
# STDERR: (empty)
```

**Important:** Flag must come BEFORE workflow path:
- ✅ `pflow -p workflow.json`
- ❌ `pflow workflow.json -p` (error: "CLI flags must come BEFORE workflow text")

### For Full Unix Piping to Work

Both issues need resolution:

| Issue | Current State | Fix |
|-------|---------------|-----|
| stdin routing | Broken - not routed to inputs | This task (auto-route by type) |
| stdout output | Broken - goes to stderr | Either: (a) auto-detect piped stdout, or (b) make `-p` default when stdout is pipe |

**Ideal end state:**
```bash
# No flags needed - just works
cat data.json | pflow transform.json | pflow analyze.json > report.md
```

### Test Verification from Investigation

**Test workflow A (produces output):**
```json
{
  "inputs": {"count": {"type": "number", "required": true}},
  "nodes": [{"id": "generate", "type": "shell", "params": {
    "command": "echo '{\"items\": [1,2,3,4,5]}' | jq '.items[0:${count}]'"
  }}],
  "edges": [],
  "outputs": {"result": {"source": "${generate.stdout}"}}
}
```

**Test workflow B (consumes input):**
```json
{
  "inputs": {"data": {"type": "string", "required": true}},
  "nodes": [{"id": "count", "type": "shell", "params": {
    "stdin": "${data}", "command": "jq 'length'"
  }}],
  "edges": [],
  "outputs": {"count": {"source": "${count.stdout}"}}
}
```

**Test results:**
```bash
# Output works with -p
pflow -p /tmp/workflow-a.json count=3
# → stdout: [1, 2, 3]

# Input still broken
pflow -p /tmp/workflow-a.json count=3 | pflow /tmp/workflow-b.json
# → Error: Workflow requires input 'data'
```

## Documentation Updates (Part of This Task)

After implementation, update documentation to reflect Unix-first piping as a core capability.

### 1. Architecture Docs

**Files:**
- `/Users/andfal/projects/pflow/architecture/overview.md`
- `/Users/andfal/projects/pflow/architecture/architecture.md`

**Add Unix-first as explicit design principle:**
- Alongside existing principles (CLI-first, file-based, stateless)
- Explain stdin/stdout contract
- Position piping as architectural differentiator from n8n/Zapier

**Example content:**
```markdown
## Unix-First Design

pflow workflows are first-class CLI citizens:
- **stdin routing**: Piped input automatically routes to matching workflow inputs
- **stdout output**: Workflow results go to stdout for pipeline composition
- **Composability**: Mix with any Unix tool (jq, grep, awk, curl)

This enables:
```bash
curl api.example.com | pflow transform.json | jq '.items' | pflow notify.json
```
```

### 2. CLI Instructions

**Files:**
- `src/pflow/cli/resources/` (agent instructions)
- Output of `pflow instructions usage` and `pflow instructions create`

**Add piping examples:**
```bash
# Pipeline composition
cat data.json | pflow transform.json | pflow analyze.json > report.md

# Mix with Unix tools
pflow fetch-prs.json | jq '.[] | select(.urgent)' | pflow notify-slack.json

# Chain multiple workflows
pflow step1.json | pflow step2.json | pflow step3.json

# Shell scripting
for repo in frontend backend api; do
  pflow audit.json repo=$repo >> security-report.md
done
```

**Document stdin: true flag for ambiguous cases:**
```json
{
  "inputs": {
    "source": {"type": "string", "required": true, "stdin": true},
    "config": {"type": "string", "required": true}
  }
}
```

### 3. Verification Checklist

After docs are updated, verify:
- [ ] `pflow instructions usage` mentions piping
- [ ] `pflow instructions create` shows stdin examples
- [ ] Architecture overview lists Unix-first as design principle
- [ ] Examples in docs actually work (test them)

## Related

- Unix-first positioning in pflow marketing/docs
- `src/pflow/core/shell_integration.py` - existing stdin handling
- Current stdin injection: `src/pflow/cli/main.py:259-272`
- Output mode logic: `src/pflow/cli/main.py:332-378` (`_output_with_header` function)
