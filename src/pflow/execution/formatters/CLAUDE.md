# CLAUDE.md - Formatters Module

**Single-source-of-truth formatters** ensuring CLI and MCP return identical output. Created in Task 72, eliminated ~800 lines of duplicate code.

**Golden Rule**: Formatters RETURN (str/dict), never print. Consumers handle display.

---

## The 10 Formatters

| Formatter | Purpose | Return Type |
|-----------|---------|-------------|
| `success_formatter.py` | Successful execution + metrics | dict |
| `error_formatter.py` | Failed execution + sanitized errors | dict |
| `validation_formatter.py` | Validation success/failure | str |
| `node_output_formatter.py` | Node execution (text/json/structure) | str or dict |
| `workflow_save_formatter.py` | Save success + execution hints | str |
| `workflow_describe_formatter.py` | Workflow interface display | str |
| `workflow_list_formatter.py` | Saved workflow listings | str |
| `discovery_formatter.py` | LLM workflow discovery results | str |
| `registry_list_formatter.py` | All nodes grouped by package | str |
| `registry_search_formatter.py` | Node search results | str |

---

## Critical Rules

### 1. Return, Never Print

```python
# ✅ CORRECT
def format_something(...) -> str:
    return "\n".join(lines)

# ❌ WRONG - Breaks MCP
def format_something(...):
    click.echo("Result")  # NO!
```

### 2. Honor Type Contracts

```python
# ✅ CORRECT - Signature matches return
def format_text_output(...) -> str:
    return "text"

# ❌ WRONG - Type violation crashes consumers
def format_text_output(...) -> str:
    return {"key": "value"}  # Dict when str expected!
```

**Why**: MCP expects exact types. Violations cause crashes.

### 3. Sanitize Security Data

```python
# error_formatter.py ALWAYS sanitizes by default
def format_execution_errors(..., sanitize: bool = True):
    if sanitize:
        # Removes API keys, tokens, passwords from error responses
```

**Never disable sanitization** for external output. Test security with `pytest tests/test_execution/formatters/test_error_formatter.py -k sanitize`

### 4. Handle Optional Parameters

```python
# ✅ CORRECT - None-safe
def format_save_success(..., metadata=None):
    keywords = metadata.get("keywords", []) if metadata else []

# ❌ WRONG - Crashes on None
def format_save_success(..., metadata=None):
    keywords = metadata.get("keywords", [])  # KeyError!
```

**Why**: MCP passes `None`, CLI may pass data. Must handle both.

---

## Dependencies

**`execution_state.py`** - Builds per-node execution steps
- Used by: `success_formatter`, `error_formatter`
- Returns: `[{"node_id": "x", "status": "completed", "duration_ms": 150, "cached": False}]`

**`Registry`** - Node metadata for template path extraction
- Used by: `node_output_formatter` (structure mode)
- Critical for showing `${node.field}` paths agents use

**`MetricsCollector`** - LLM usage metrics
- Used by: `success_formatter`, `error_formatter`
- Returns: `{"duration_ms": 1234, "total_cost_usd": 0.05}`

**`sanitize_parameters()`** from `mcp_server.utils.errors`
- Used by: `error_formatter`
- Removes sensitive data (API keys, tokens)

---

## Usage Patterns

```python
# Execution success
from pflow.execution.formatters.success_formatter import format_execution_success
result = format_execution_success(shared_storage, workflow_ir, metrics_collector)

# Execution errors (ALWAYS sanitize=True for external output)
from pflow.execution.formatters.error_formatter import format_execution_errors
formatted = format_execution_errors(result, shared_storage, ir_data, metrics_collector, sanitize=True)

# Node output - structure mode (shows ${node.field} template paths for agents)
from pflow.execution.formatters.node_output_formatter import format_node_output
result = format_node_output(node_type, action, outputs, shared_store, execution_time_ms, registry, format_type="structure")
```

---

**node_output_formatter format modes**: `text` (human-readable), `json` (structured dict), `structure` (template paths like `${node.field}` - critical for agents to discover workflow variables)

---

## Common Pitfalls

### 1. Breaking Type Contracts
```python
# ❌ Returns dict when str expected
def format_text(...) -> str:
    return {"key": "value"}
```

### 2. Assuming Non-None Parameters
```python
# ❌ Crashes on None
keywords = metadata.get("keywords")
```

### 3. Forgetting Sanitization
```python
# ❌ Exposes API keys
return {"error": raw_response}
```

### 4. Not Testing Both Consumers
Must verify: CLI text output AND MCP JSON response both work.

---

## Modification Guidelines

**Adding formatter**: Choose return type (`str`/`dict`) → Handle optional params (`if param else default`) → Write tests (type contracts, None-safety, security) → Update CLI and MCP

**Extending formatter**: Add fields, don't remove. Always test: `pytest tests/test_execution/formatters/ tests/test_cli/ tests/test_mcp_server/ -v`

---

## Integration Checklist

When modifying formatters:
- [ ] Return type matches signature
- [ ] No `print()` or `click.echo()` calls
- [ ] Handles `None` for optional params
- [ ] Sanitizes sensitive data
- [ ] CLI and MCP get identical output
- [ ] Tests added/updated
- [ ] Docstring examples accurate

---

## Quick Diagnostics

**Formatter not working?**
1. Check return type: `print(type(result))`
2. Test with None: `formatter(..., metadata=None)`
3. Run tests: `pytest tests/test_execution/formatters/ -v`

**Output wrong?**
1. Verify `format_type` parameter (text/json/structure)
2. Check data sources populated (shared_storage, workflow_ir)
3. Compare with test examples

**Tests failing?**
1. Type contract: Return type matches signature?
2. Parity: CLI and MCP same output?
3. None-safety: Optional params handled?

---

## Related Files

- `execution_state.py` - Per-node execution state builder
- `tests/test_execution/formatters/` - 75+ test cases
- `src/pflow/cli/CLAUDE.md` - CLI usage patterns
- `src/pflow/mcp_server/` - MCP integration
