# Smart Output Display for `registry run` - Implementation Spec

## Overview

Modify `pflow registry run` to support three output modes controlled via settings:
- **smart** (default): Show template paths WITH values, truncate large values, apply smart filtering
- **structure**: Current Task 89 behavior - paths only, no values, apply smart filtering
- **full**: Show all paths with full values, NO smart filtering, NO truncation

## Output Format Examples

### Smart Mode (Default)

**Short values:**
```
✓ Node executed successfully

Execution ID: exec-1766180609-f4e20a18

Output:
  ✓ ${stdout} (str) = "hello world"
  ✓ ${stderr} (str) = ""
  ✓ ${exit_code} (int) = 0

Execution time: 7ms
```

**With truncation (after smart filtering):**
```
✓ Node executed successfully

Execution ID: exec-1766162256-9f06183c

Output (8 of 54 shown):
  ✓ ${result.status} (int) = 200
  ✓ ${result.ok} (bool) = true
  ✓ ${result.data} (dict) = {...5 keys}
  ✓ ${result.data.items} (list) = [...156 items]
  ✓ ${result.data.items[0].id} (str) = "abc123"
  ✓ ${result.data.items[0].title} (str) = "Hello World"
  ✓ ${result.data.items[0].body} (str) = "This is a long description that..." (truncated)
  ✓ ${result.headers.content-type} (str) = "application/json"

Use `pflow read-fields exec-1766162256-9f06183c <path>` for full values.

Execution time: 8506ms
```

### Structure Mode (Current Task 89 Behavior)

```
✓ Node executed successfully

Execution ID: exec-1766180609-f4e20a18

Available template paths:
  ✓ ${exit_code} (int)
  ✓ ${stderr} (str)
  ✓ ${stdout} (str)

Use these paths in workflow templates.

Execution time: 7ms
```

### Full Mode (Everything, No Filtering)

```
✓ Node executed successfully

Execution ID: exec-1766180609-f4e20a18

Output (all 54 fields):
  ✓ ${result.status} (int) = 200
  ✓ ${result.ok} (bool) = true
  ... (all 54 fields with full values, no truncation)

Execution time: 8506ms
```

## Truncation Rules

| Type | Condition | Display |
|------|-----------|---------|
| String | >200 chars | `"first 197 chars..." (truncated)` |
| Dict | >5 keys | `{...N keys}` |
| List | >5 items | `[...N items]` |
| Number | - | Always full |
| Boolean | - | `true` / `false` |
| Null | - | `null` |

## Settings Configuration

**Location**: `~/.pflow/settings.json`

```json
{
  "registry": {
    "nodes": {...},
    "include_test_nodes": false,
    "output_mode": "smart"
  }
}
```

**Valid values**: `"smart"`, `"structure"`, `"full"`

**CLI commands**:
```bash
pflow settings registry output-mode          # Show current mode
pflow settings registry output-mode smart    # Set to smart
pflow settings registry output-mode structure # Set to structure
pflow settings registry output-mode full     # Set to full
```

## Implementation Plan

### Phase 1: Settings Infrastructure

**File: `src/pflow/core/settings.py`**

1. Add `output_mode` field to `RegistrySettings`:
```python
class RegistrySettings(BaseModel):
    nodes: NodeFilterSettings = Field(default_factory=NodeFilterSettings)
    include_test_nodes: bool = Field(default=False)
    output_mode: str = Field(
        default="smart",
        description="Output mode for registry run: smart, structure, or full"
    )

    @field_validator("output_mode")
    @classmethod
    def validate_output_mode(cls, v: str) -> str:
        valid_modes = ["smart", "structure", "full"]
        if v not in valid_modes:
            raise ValueError(f"Invalid output_mode: {v}. Must be one of: {', '.join(valid_modes)}")
        return v
```

### Phase 2: CLI Commands

**File: `src/pflow/cli/commands/settings.py`**

Add a new command group for registry settings:
```python
@settings.group()
def registry() -> None:
    """Manage registry settings."""
    pass

@registry.command(name="output-mode")
@click.argument("mode", required=False, type=click.Choice(["smart", "structure", "full"]))
def registry_output_mode(mode: Optional[str]) -> None:
    """Show or set registry output mode.

    Examples:
        pflow settings registry output-mode          # Show current
        pflow settings registry output-mode smart    # Set to smart
    """
```

### Phase 3: Formatter Enhancement

**File: `src/pflow/execution/formatters/node_output_formatter.py`**

1. Add `format_value_for_display()` function for value truncation:
```python
def format_value_for_display(value: Any, max_str_length: int = 200) -> tuple[str, bool]:
    """Format a value for display with truncation.

    Returns:
        Tuple of (formatted_string, was_truncated)
    """
```

2. Add `format_smart_output()` function:
```python
def format_smart_output(
    paths: list[tuple[str, str]],
    outputs: dict[str, Any],
    shared_store: dict[str, Any],
    source_description: str | None,
    execution_id: str,
) -> tuple[list[str], bool]:
    """Format paths with their actual values (smart mode).

    Returns:
        Tuple of (lines, any_truncated)
    """
```

3. Modify `format_structure_output()` to accept `output_mode` parameter

4. Modify `format_node_output()` wrapper to pass through `output_mode`

### Phase 4: Call Site Updates

**File: `src/pflow/cli/registry_run.py`**

In `_display_results()`:
1. Import SettingsManager locally
2. Load settings and get `output_mode`
3. Pass `output_mode` to `format_node_output()`

**File: `src/pflow/mcp_server/services/execution_service.py`**

In `run_registry_node()`:
1. Import SettingsManager locally
2. Load settings and get `output_mode`
3. Pass `output_mode` to `format_node_output()`

### Phase 5: Tests

**File: `tests/test_execution/formatters/test_node_output_formatter.py`**

Add tests for:
- `format_value_for_display()` truncation rules
- `format_smart_output()` with various data types
- Smart filtering still applies in smart mode
- No filtering in full mode
- Structure mode unchanged

**File: `tests/test_core/test_settings.py`**

Add tests for:
- `output_mode` validation
- Default value is "smart"

**File: `tests/test_cli/test_settings.py`**

Add tests for:
- `pflow settings registry output-mode` commands

## File Inventory

### Files to Modify

1. `src/pflow/core/settings.py` - Add output_mode field
2. `src/pflow/cli/commands/settings.py` - Add CLI commands
3. `src/pflow/execution/formatters/node_output_formatter.py` - Add smart output formatting
4. `src/pflow/cli/registry_run.py` - Read setting and pass to formatter
5. `src/pflow/mcp_server/services/execution_service.py` - Read setting and pass to formatter

### Files to Create

None - all changes are in existing files

### Test Files to Modify

1. `tests/test_execution/formatters/test_node_output_formatter.py`
2. `tests/test_core/test_settings.py`
3. `tests/test_cli/test_settings.py` (if exists, otherwise add tests)

## Dependencies

- `TemplateResolver.resolve_value()` from `pflow.runtime.template_resolver` - for resolving values from paths
- `smart_filter_fields_cached()` from `pflow.core.smart_filter` - reuse existing smart filtering
- `SettingsManager` from `pflow.core.settings` - for loading settings

## Behavior Matrix

| Mode | Smart Filtering | Show Values | Truncation | Header |
|------|-----------------|-------------|------------|--------|
| smart | Yes (>25 fields) | Yes | Yes | "Output (N of M shown):" |
| structure | Yes (>25 fields) | No | N/A | "Available template paths:" |
| full | No | Yes | No | "Output (all N fields):" |

## Edge Cases

1. **Empty outputs**: Show "No outputs available"
2. **Binary data**: Show `<binary data, N bytes>`
3. **Circular references**: Use existing JSON serialization which handles this
4. **None values**: Show `null`
5. **Very long paths**: No truncation on paths, only values

## CLI/MCP Parity

Both CLI and MCP will:
1. Read the same setting from `~/.pflow/settings.json`
2. Call the same formatter functions
3. Produce identical output

This ensures agents using MCP get the same behavior as CLI users.
