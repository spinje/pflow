# Data Type Coercion in pflow

How pflow handles JSON parsing and type conversion as data flows between nodes.

## Navigation

**Related Documents:**
- **Templates**: [Template Variables](../reference/template-variables.md) — syntax, resolution, validation
- **Shared Store**: [Shared Store Pattern](./shared-store.md) — how nodes communicate
- **Node Design**: [Simple Nodes](../features/simple-nodes.md) — node architecture
- **Implementation**: `src/pflow/core/json_utils.py` — shared parsing utility

---

## Overview

### The Problem

Nodes produce different output types. Shell nodes write stdout as strings. HTTP nodes may return parsed JSON. LLM nodes return text. But downstream consumers often need a different type — a dict to access fields, a list to iterate over, a string to embed in a prompt.

### The Design Philosophy

> **Producers store raw values. Consumers declare types. The system bridges the gap.**

This follows the same pattern used by every well-designed LLM orchestration system:

- **LangChain**: Output parsers are explicit, separate components attached to chains
- **Vercel AI SDK**: Structured output declared via `output` schema property on `generateText()`
- **n8n**: Separate "Output Parser" nodes sit between LLM and downstream nodes
- **Simon Willison's `llm` library** (which pflow wraps): `response.text()` returns raw text, always

None of these systems speculatively parse output. Parsing is always driven by an **intent signal** — the consumer declaring what it needs, or the user explicitly requesting structured access.

---

## Design Principles

### 1. Producers store what they produce

Nodes write their natural output type. Shell nodes store stdout (string). LLM nodes store the response (string). HTTP nodes store the body. No node should speculatively parse its own output "in case" a downstream consumer needs it differently.

### 2. Parsing requires an intent signal

The system only converts types when something signals that conversion is needed:

| Intent Signal | Example | Who signals? |
|--------------|---------|-------------|
| Dot notation in template | `${node.stdout.field}` | Workflow author |
| Target node declares type | Interface says `param: dict` | Node developer |
| Batch items declaration | `items: ${node.output}` | Workflow author |
| Inline structured object | `{"data": "${node.stdout}"}` | Workflow author |

### 3. Guards prevent false positives

Every auto-parse point has safety guards:
- **Container-only**: Only parse to `dict`/`list`, never to primitives (prevents numeric string coercion like Discord snowflake IDs)
- **Size limit**: 10MB max via `json_utils.py`
- **First-char check**: Quick rejection if string doesn't start with `{`, `[`, `"`, etc.
- **Simple template only**: Complex templates like `"prefix ${var}"` always stay as strings

### 4. Display-layer parsing is read-only

Parsing at the CLI output boundary (for pretty-printing) never affects data flow. It's purely presentational.

---

## Complete Auto-Parse Inventory

Every location in pflow where automatic JSON parsing or type coercion occurs:

### Point 1: Template Traversal (GOOD)

**Location**: `src/pflow/runtime/template_resolver.py:202-231` — `_try_parse_json_for_traversal()`

**When it fires**: User writes `${node.stdout.field}` — dot notation on a string value.

**Intent signal**: The dot notation is an explicit declaration: "I want to access a field inside this value." If the value is a string, the system tries to parse it as JSON to enable traversal.

**Guards**: Only parses to `dict`/`list`. Primitives (int, float, bool) are never parsed — preserves numeric strings.

**Example**:
```
# Shell node outputs: shared["stdout"] = '{"items": [1,2,3], "count": 3}'
# Template: ${shell-node.stdout.count}
# Result: 3 (parsed on demand, original string untouched)
```

### Point 2: resolve_nested Simple Template (ACCEPTABLE)

**Location**: `src/pflow/runtime/template_resolver.py:632-638` — inside `resolve_nested()`

**When it fires**: A simple template (`${var}` as the entire value) inside an inline structured object resolves to a JSON string.

**Intent signal**: Partial — the user constructed a structured object (`{"data": "${shell.stdout}"}`) implying they want structured data. But they didn't explicitly say "parse this."

**Guards**: Only fires for simple templates (full `${var}` replacement). Only parses to containers. Complex templates like `"prefix ${var}"` always stay as strings.

**Why it exists**: Without this, `{"body": "${shell.stdout}"}` where stdout is `'{"key":"value"}'` would produce `{"body": '{"key":"value"}'}` — double-encoded. This prevents that.

**Tech debt note**: This is the weakest link in the design — it has no schema signal from the consumer. Revisit when Task 66 (structured output) lands.

### Point 3: Node Wrapper Target-Side Coercion (GOOD)

**Location**: `src/pflow/runtime/node_wrapper.py:827-842`

**When it fires**: After template resolution, if the resolved value is a string and the target node's interface declares the parameter as `dict`, `list`, `object`, or `array`.

**Intent signal**: The receiving node's interface declaration. This is schema-driven — the node developer explicitly declared "I expect a dict here."

**Guards**: Type-safe — only parses when the parsed type matches the declared type. `dict` expects `dict`, `list` expects `list`.

**Also handles the reverse**: If a resolved value is a `dict`/`list` but the target expects `str`, it serializes to JSON string (lines 844-849).

### Point 4: Batch Node Items Parse (GOOD)

**Location**: `src/pflow/runtime/batch_node.py:262-271`

**When it fires**: Batch items template resolves to a string (typically from shell stdout).

**Intent signal**: The workflow author declared this as batch items, which semantically means "iterate over this." A string can't be iterated as items — parsing to list is the only useful interpretation.

**Guards**: Only parses to `list`. If the string isn't a JSON array, it stays as-is and the batch node raises a clear error.

### Point 5: Display Layer (FINE)

**Location**: `src/pflow/cli/main.py:973-997`, `src/pflow/execution/formatters/success_formatter.py:120-141`

**When it fires**: At the CLI output boundary, when displaying workflow results.

**Intent signal**: N/A — this is presentation, not data flow.

**Impact**: Read-only. Parses JSON strings for pretty-printing. Never affects the shared store or downstream nodes. Every CLI tool does this.

### Point 6: LLM Node parse_json_response (REMOVED)

**Location**: `src/pflow/nodes/llm/llm.py:47-78` (to be removed)

**When it fired**: Every LLM response, eagerly, on every call.

**Intent signal**: None. The method speculatively extracted content from markdown code blocks and attempted `json.loads()`. No consumer type declaration, no user intent signal.

**Why it was removed**: Violated principle #1 (producer should store raw value) and #2 (no intent signal). Caused a data-loss bug where prose responses containing JSON code blocks had the prose silently discarded. See `scratchpads/json-parse-bug/bug-report.md`.

**What replaces it**: Nothing — the template system (Points 1-4) already handles all legitimate use cases. Task 66 (planned) will add explicit structured output for workflows that need guaranteed JSON.

---

## How They Interact

Data flows through these coercion points in order:

```
Node Output (raw value)
    │
    ▼
Template Resolution (resolve_nested)
    │
    ├── Simple template ${var} inside inline object?
    │   └── Point 2: Auto-parse to container if JSON string
    │
    ├── Dot notation ${node.stdout.field}?
    │   └── Point 1: Parse on demand for traversal
    │
    └── Other templates: preserve as-is
    │
    ▼
Node Wrapper Type Coercion
    │
    ├── Resolved string, target expects dict/list?
    │   └── Point 3: Schema-driven parse
    │
    ├── Resolved dict/list, target expects string?
    │   └── Point 3 (reverse): Serialize to JSON
    │
    └── Types match: pass through
    │
    ▼
Node Input (coerced value)
    │
    ... (node executes) ...
    │
    ▼
CLI Output Display
    └── Point 5: Parse for pretty-printing (read-only)
```

Points 1, 2, and 3 may fire on the same data in a single resolution pass. They are ordered by specificity: traversal is most targeted, resolve_nested is intermediate, node wrapper is the final safety net.

---

## Shared Infrastructure: json_utils.py

All auto-parse points (except the removed LLM node) use the shared utility at `src/pflow/core/json_utils.py`:

### `try_parse_json(value) -> tuple[bool, Any]`

Two-value return pattern distinguishing three cases:
- `(True, {"key": "value"})` — parsed successfully to dict
- `(True, None)` — parsed successfully to JSON null
- `(False, "original string")` — parse failed, original returned

### `parse_json_or_original(value) -> Any`

Convenience wrapper for when you don't need to distinguish success from failure. Used by the display layer.

### Performance Guards

- **First-char check**: Rejects strings not starting with `{`, `[`, `"`, `t`, `f`, `n`, `-`, or digit
- **Size limit**: 10MB default (configurable), prevents memory exhaustion
- **Empty string rejection**: Returns immediately

---

## Known Limitations & Tech Debt

1. **resolve_nested auto-parse (Point 2)** has no schema signal from the consumer. It's the weakest design point. Could surprise users if `${shell.stdout}` happens to be valid JSON but they wanted the raw string in an inline object. Mitigated by the container-only guard.

2. **No caching of parsed JSON**. The same string may be parsed multiple times if referenced in multiple templates. Acceptable for MVP (parsing is <1ms vs node execution 100-1000ms). Consider caching if profiling shows this as a bottleneck.

3. **LLM node fix pending**. `parse_json_response` needs to be removed and replaced with raw string storage. See `scratchpads/json-parse-bug/bug-report.md` for the full bug analysis.

4. **Task 66 (Structured Output)** will add explicit schema-driven JSON parsing for LLM nodes. This is the proper solution for "I want guaranteed JSON from an LLM" — declaring a schema, not hoping the heuristic works.

---

## See Also

- [Template Variables Reference](../reference/template-variables.md) — full template syntax and resolution rules
- [Shared Store Pattern](./shared-store.md) — how nodes communicate through the shared store
- `src/pflow/core/json_utils.py` — shared JSON parsing utility (source of truth for parsing logic)
- `src/pflow/runtime/CLAUDE.md` — runtime module documentation (wrapper chain, template system)
- `scratchpads/json-parse-bug/bug-report.md` — the bug that prompted this documentation
