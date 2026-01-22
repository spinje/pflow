# Task 115: Automatic Stdin Routing for Unix-First Piping

## Description

Enable Unix-style piping into workflows by routing stdin to workflow inputs marked with `"stdin": true`. This makes `cat data.json | pflow transform.json | pflow analyze.json` work with explicit workflow configuration.

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
1. CLI reads stdin but doesn't route it to workflow input parameters
2. Validation happens BEFORE stdin could be injected, rejecting missing required inputs
3. No mechanism to declare which workflow input should receive piped data

**Current state:**
- `_validate_before_execution()` runs before stdin is available to inputs
- Workflows must receive all required inputs via CLI - piping doesn't work

## Solution

Implement explicit stdin routing via `"stdin": true` input declaration:

### Algorithm

1. **Check for `stdin: true` input** in workflow declaration
2. **If found and stdin is piped**: Route stdin content to that input (unless CLI overrides)
3. **If found but no stdin piped**: Input must be provided via CLI (normal required input behavior)
4. **If not found**: Stdin is not routed - workflow doesn't accept piped input

### Key Design Principle

Stdin routing is **explicit, not automatic**. No type detection, no auto-matching. The workflow author declares which input receives stdin by adding `"stdin": true`.

This gives flexibility: the same input can be provided via stdin OR CLI argument.

### Explicit Declaration

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

**Case 1: Basic stdin input**
```json
{
  "inputs": {
    "data": {"type": "string", "required": true, "stdin": true},
    "limit": {"type": "number", "default": 10}
  }
}
```
```bash
# Via stdin
echo "hello world" | pflow workflow.json
# → data="hello world", limit=10

# Via CLI (same workflow, different invocation)
pflow workflow.json data="hello world" limit=5
# → data="hello world", limit=5
```

**Case 2: CLI overrides stdin**
```bash
echo "from pipe" | pflow workflow.json data="from cli"
# → data="from cli" (CLI wins)
```

**Case 3: Multiple inputs, one receives stdin**
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
# "template" provided via CLI
```

**Case 4: Pipeline composition**
```bash
cat data.json | pflow -p transform.json | pflow analyze.json > report.md
# Each workflow has stdin: true on its data input
```

**Case 5: No stdin: true = no piping**
```json
{
  "inputs": {
    "file_path": {"type": "string", "required": true}
  }
}
```
```bash
echo "/tmp/data.json" | pflow workflow.json
# Error: Workflow has no input marked with stdin: true
# (Piping not supported for this workflow)
```

## Design Decisions

- **Explicit declaration required**: Workflow author must add `"stdin": true` to one input - no auto-detection
- **No type matching**: We don't detect stdin type or try to match it to inputs - explicit is better than magic
- **No `${stdin}` in shared store**: Stdin ONLY routes to inputs with `stdin: true` - this ensures inputs work with both CLI and stdin
- **CLI override**: CLI param always wins over stdin (`pflow workflow.json data="override"` ignores stdin)
- **Single stdin input**: Only one input per workflow can have `stdin: true`
- **Flexibility**: Same workflow works via piping OR CLI arguments - author declares once, users choose invocation style

## Implementation Notes

### Files to Modify

1. **`src/pflow/cli/main.py`**:
   - Add `_find_stdin_input(workflow_ir)` → returns input name with `stdin: true` or None
   - Add `_route_stdin_to_params(stdin_data, workflow_ir, params)` → injects stdin into params
   - Modify stdin handling to inject into `execution_params` before validation
   - Remove `populate_shared_store()` calls for stdin - the old `${stdin}` pattern is being removed entirely

2. **`src/pflow/core/workflow_validator.py`**:
   - Add validation that only one input has `stdin: true`

3. **`src/pflow/core/ir_schema.py`**:
   - Add `stdin` boolean field to input schema

### Stdin Input Resolution

```python
def _find_stdin_input(workflow_ir: dict) -> str | None:
    """Find the input marked with stdin: true."""
    inputs = workflow_ir.get("inputs", {})

    stdin_inputs = [name for name, spec in inputs.items()
                    if spec.get("stdin") is True]

    if len(stdin_inputs) == 0:
        return None
    if len(stdin_inputs) == 1:
        return stdin_inputs[0]

    raise ValueError(
        f"Multiple inputs marked with stdin: true: {', '.join(stdin_inputs)}. "
        f"Only one input can receive piped stdin."
    )
```

### Stdin Routing Logic

```python
def _route_stdin_to_params(
    stdin_data: str | None,
    workflow_ir: dict,
    params: dict,
) -> dict:
    """Route stdin to the appropriate input parameter."""
    if stdin_data is None:
        return params

    target = _find_stdin_input(workflow_ir)

    if target is None:
        # No stdin: true input - error if user is piping
        raise ValueError(
            "Workflow has no input marked with stdin: true. "
            "Add '\"stdin\": true' to an input to enable piping."
        )

    # CLI param overrides stdin
    if target in params:
        return params

    # Route stdin to target input
    result = params.copy()
    result[target] = stdin_data
    return result
```

## Verification

1. **Basic piping works** (workflow has `stdin: true` on data input):
   ```bash
   echo '{"items": [1,2,3]}' | pflow test-workflow.json
   ```

2. **Pipeline composition works**:
   ```bash
   cat data.json | pflow -p step1.json | pflow step2.json
   ```

3. **Same workflow works via CLI**:
   ```bash
   pflow test-workflow.json data='{"items": [1,2,3]}'
   ```

4. **No stdin: true errors clearly**:
   ```bash
   echo "text" | pflow no-stdin-workflow.json
   # Error: Workflow has no input marked with stdin: true.
   #        Add '"stdin": true' to an input to enable piping.
   ```

5. **Multiple stdin: true errors clearly**:
   ```bash
   # Workflow with two stdin: true inputs
   # Error: Multiple inputs marked with stdin: true: input1, input2.
   #        Only one input can receive piped stdin.
   ```

6. **CLI param overrides stdin**:
   ```bash
   echo "ignored" | pflow workflow.json data="used"
   # Uses "used", not "ignored"
   ```

7. **Workflows without stdin: true**: Work normally via CLI args (just can't receive piped input)

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
| stdin routing | Broken - not routed to inputs | This task (explicit `stdin: true` on input) |
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

**Test workflow B (consumes input via stdin):**
```json
{
  "inputs": {"data": {"type": "string", "required": true, "stdin": true}},
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
- **stdin routing**: Piped input routes to inputs marked with `stdin: true`
- **stdout output**: Workflow results go to stdout for pipeline composition
- **Composability**: Mix with any Unix tool (jq, grep, awk, curl)
- **Flexibility**: Same workflow works via piping OR CLI arguments

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

**Document stdin: true flag for enabling piping:**
```json
{
  "inputs": {
    "data": {"type": "object", "required": true, "stdin": true}
  }
}
```
The `stdin: true` flag marks which input receives piped data. Without it, the workflow cannot accept piped input. This same input can also be provided via CLI argument.

### 3. Verification Checklist

After docs are updated, verify:
- [ ] `pflow instructions usage` mentions piping
- [ ] `pflow instructions create` shows stdin examples
- [ ] Architecture overview lists Unix-first as design principle
- [ ] Examples in docs actually work (test them)

## Related

- Unix-first positioning in pflow marketing/docs
- `src/pflow/core/shell_integration.py` - stdin reading utilities (to be simplified)
- `src/pflow/cli/main.py` - CLI parameter handling and validation flow
- Output mode logic: `src/pflow/cli/main.py:332-378` (`_output_with_header` function)
