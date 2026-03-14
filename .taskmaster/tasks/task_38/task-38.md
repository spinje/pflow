# Task 38: Conditional Branching in Workflows

## Overview

Add conditional branching to `.pflow.md` workflows. Python code nodes can set `next` to dynamically route execution. Any node can use `- next:` for static routing and `- on-error:` for error handling. PocketFlow and the compiler already support action-based transitions — the work is in the markdown format, parser, and python code node.

## Design

### Routing Mechanisms

| Syntax | Where | What it does |
|--------|-------|-------------|
| Document order | All nodes | Default linear chain (unchanged) |
| `- next: node-id` | Any node (markdown) | Override default successor |
| `- next: end` | Any node (markdown) | Terminate flow (no successor) |
| `- on-error: node-id` | Any node (markdown) | Route on node failure |
| `next: str = "node-id"` | Python code node | Dynamic routing (code decides) |

### Behavior Rules

1. **No `next` set in code** → `post()` returns `"default"` → follows document order (or `- next:`)
2. **`next` set in code** → `post()` returns that value → follows the matching edge
3. **`result` is optional** when `next` is set (routing-only nodes don't need output data)
4. **`- next: end`** on the last main-flow node prevents chaining into branch targets below it
5. **`on-error`** fires after all retries are exhausted (repair system is gated/disabled)
6. **Max 100 node visits** to guard against infinite loops (workflow-level default)
7. **Code overrides markdown** — if both `- next:` and code `next =` exist, code wins at runtime

### Example Workflow

```markdown
## Steps

### fetch-data
Fetch user data from the API

- type: http
- url: https://api.example.com/users
- on-error: handle-error

### classify
Route based on the response

- type: python
```python code
category: str = shared["fetch-data"]["result"]["type"]
if category == "premium":
    next: str = "priority-process"
elif category == "spam":
    next: str = "quarantine"
```

### standard-process
Handle normal items

- type: shell
- command: ./process.sh standard
- next: end

### priority-process
Fast-track premium items

- type: shell
- command: ./process.sh priority
- next: end

### quarantine
Isolate spam

- type: shell
- command: ./quarantine.sh

### handle-error
Log the failure

- type: shell
- command: echo "Failed: ${fetch-data.error}"
```

**Flow paths:**
- Happy path (default): fetch-data → classify → standard-process (end)
- Premium: fetch-data → classify → priority-process (end)
- Spam: fetch-data → classify → quarantine
- Error: fetch-data → handle-error

### Common Patterns

**Error handling:**
```markdown
### call-api
- type: http
- url: https://api.example.com/data
- on-error: handle-error
```

**Classification routing (LLM + code):**
```markdown
### classify
- type: llm
- prompt: Classify this ticket as billing, technical, or feature-request

### route
- type: python
```python code
category: str = shared["classify"]["result"]
next: str = category
```
```

**Skip-ahead:**
```markdown
### validate
- type: python
```python code
data: dict = shared["fetch"]["result"]
if data.get("already_processed"):
    next: str = "save"
```

### transform
Process the data
...

### save
Write to disk
...
```

**Retry loop:**
```markdown
### call-api
- type: http
- url: ${input.url}
- on-error: wait-and-retry

### process-result
...
- next: end

### wait-and-retry
- type: shell
- command: sleep 5
- next: call-api
```

**Convergence (branches rejoin):**
```markdown
### route
- type: python
- next: path-a, path-b

### done
Final step
...

### path-a
- type: shell
- next: done

### path-b
- type: shell
- next: done
```

## What Already Works

1. **PocketFlow** (`src/pflow/pocketflow/__init__.py`): `node - "action" >> target` conditional transitions, `get_next_node()` resolves action → successor, `successors` dict stores action → node mappings
2. **Compiler** (`src/pflow/runtime/compiler.py:798-862`): `_wire_nodes()` reads `action` field from edges, uses PocketFlow operators to wire
3. **IR Schema** (`src/pflow/core/ir_schema.py`): `action` field on edges (default: `"default"`)
4. **Wrapper chain**: All wrappers (Instrumented, TemplateAware, Namespaced) transparently pass action strings through
5. **Existing nodes**: All return `"default"` or `"error"` from `post()` — these map to `- next:` and `- on-error:`

## What Needs to Change

### 1. Markdown Parser (`src/pflow/core/markdown_parser.py`)

**Current**: Generates edges purely from document order (line 385-389). No syntax for routing.

**Changes**:
- Parse `- next:` field on step nodes (single value or comma-separated list)
- Parse `- on-error:` field on step nodes
- AST-parse python code blocks for literal `next: str = "..."` assignments to discover routing targets
- Generate edges:
  - Document-order edges with action `"default"` (for nodes without `- next:`)
  - `- next: node-id` → edge with action `"default"` (overrides document order)
  - `- next: end` → no outgoing edge
  - `- on-error: node-id` → edge with action `"error"`
  - AST-detected `next = "node-id"` → edge with action = the literal string (node ID)
- Validate all targets reference existing node IDs (suggest corrections for close matches)
- Validate branch targets have explicit `- next:` (prevents silent fall-through)
- Validate non-router nodes don't fall through into branch targets via document order
- Validate dynamic `next = variable` assignments have `- next:` declarations on the code node

### 2. Python Code Node (`src/pflow/nodes/python/python_code.py`)

**Current**: Requires `result` variable, `post()` always returns `"default"` or `"error"`.

**Changes**:
- After exec, check if `next` was set in namespace
- If `next` is set: `post()` returns that string instead of `"default"`
- Make `result` optional when `next` is present in namespace
- `next` shadows Python's `next` builtin — acceptable in isolated routing code blocks

### 3. Loop Guard (flow runner level)

**Current**: No protection against infinite loops.

**Changes**:
- Track per-node visit count during flow execution
- Stop with clear error when any node exceeds 100 visits (default)
- Configurable via workflow-level setting if needed later

### 4. Tests

- **Parser tests**: `- next:`, `- on-error:`, `- next: end`, AST detection of `next =` literals
- **Python code node tests**: `next` variable routing, `result` optional when `next` set
- **Integration tests**: Error handling, classification routing, skip-ahead, retry loops, convergence
- **Validation tests**: Invalid targets, typo suggestions, loop guard

### 5. Examples

- Example `.pflow.md` workflows demonstrating each pattern
- Update `examples/core/error-handling.pflow.md` to use `on-error` syntax

## What Does NOT Change

- **PocketFlow** (`src/pflow/pocketflow/__init__.py`) — no changes needed
- **Compiler** (`src/pflow/runtime/compiler.py`) — already handles action-based edges
- **IR Schema** (`src/pflow/core/ir_schema.py`) — already has `action` field
- **Other node types** — they already return `"default"` / `"error"`, which maps to the new routing
- **Planner** — gated (Task 107), not relevant

## Out of Scope

- **Parallel execution** (Task 39) — branching is conditional (ONE path), not parallel (ALL paths)
- **Dynamic routing targets** — `next = some_variable` requires `- next:` declaration (enforced at parse time); AST only parses string literals
- **Repair system integration** — repair is gated/disabled; `on-error` is the primary error mechanism
- **Complex expression evaluation** — no `- if:` conditions; use python code nodes for any decision logic

## Edge Cases and Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Code `next =` vs markdown `- next:` | Code wins at runtime | Markdown is the default; code overrides dynamically |
| `result` when `next` is set | Optional | Routing-only nodes don't produce output data |
| `next` shadows Python builtin | Acceptable | Routing code blocks are isolated, `next()` never needed there |
| Branch target exclusion from linear chain | Explicit `- next: end`, enforced at parse time | Branch targets without `- next:` cause silent fall-through; parser validates all three failure modes |
| Loop protection | Max 100 visits per node | Prevents infinite loops; can be made configurable later |
| Validation timing | Parse time for literals | All node IDs known at parse time; typo suggestions possible |

## Success Criteria

1. All routing mechanisms work: `- next:`, `- on-error:`, `- next: end`, code `next =`
2. Parser correctly generates edges with action strings
3. Python code node returns `next` value as action string
4. All patterns work end-to-end: error handling, classification, skip-ahead, loops, convergence
5. Invalid targets caught at parse time with helpful error messages
6. Loop guard prevents infinite execution
7. `make test` and `make check` pass

## Status

complete — implemented and merged

## Dependencies

- No external dependencies
- Builds on existing PocketFlow, compiler, and IR schema support
