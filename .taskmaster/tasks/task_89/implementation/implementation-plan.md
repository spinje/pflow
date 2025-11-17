# Task 89: Detailed Implementation Plan
## Structure-Only Mode and Selective Data Retrieval

**Date**: 2025-01-14
**Status**: Ready for Review
**Estimated LOC**: ~400 lines (200 implementation + 200 tests)

---

## 🎯 Implementation Overview

### Core Behavior Changes
1. **registry run** (CLI + MCP): ALWAYS returns structure-only (no values) + execution_id
2. **New command**: `read-fields` retrieves specific field values from cached executions
3. **Smart filtering**: When fields > 50, use Haiku 4.5 to reduce to relevant subset
4. **No automatic cleanup**: Cache persists indefinitely in MVP (24hr TTL deferred to post-MVP)

### Key Technical Decisions
- **Execution ID format**: `exec-{timestamp}-{random_hex}` (e.g., `exec-1705234567-a1b2c3d4`)
- **Cache location**: `~/.pflow/cache/registry-run/{execution_id}.json`
- **Smart filter model**: `anthropic/claude-haiku-4-5-20251001`
- **Smart filter threshold**: Exactly 50 fields
- **Binary data encoding**: base64 with type marker `{"__type": "base64", "data": "..."}`
- **File permissions**: Default (644) - no sensitive data in cache

---

## 📂 File Inventory

### New Files to Create (8 files)

#### Core Implementation (4 files)
1. **`src/pflow/core/execution_cache.py`** (~80 lines)
   - ExecutionCache class with store/retrieve/list methods
   - TTL tracking (stored but not enforced in MVP)
   - Binary data handling via base64

2. **`src/pflow/core/smart_filter.py`** (~60 lines)
   - LLM-based field filtering using Haiku 4.5
   - Structured output with Pydantic schema
   - Fallback to unfiltered on LLM errors

3. **`src/pflow/cli/read_fields.py`** (~80 lines)
   - CLI command: `pflow read-fields <execution_id> <field_path>...`
   - Variadic field paths support
   - Error handling for missing/expired cache

4. **`src/pflow/execution/formatters/field_output_formatter.py`** (~40 lines)
   - Format field retrieval results for CLI/MCP
   - Support text and json formats
   - Handle None values gracefully

#### Test Files (4 files)
5. **`tests/test_core/test_execution_cache.py`** (~120 lines)
   - Test store/retrieve/list operations
   - Test binary data encoding/decoding
   - Test cache file structure and permissions
   - Test nonexistent execution_id handling

6. **`tests/test_core/test_smart_filter.py`** (~80 lines)
   - Test filtering with >50 fields
   - Test no filtering with <50 fields
   - Test LLM failure fallback
   - Mock Haiku responses

7. **`tests/test_cli/test_read_fields.py`** (~100 lines)
   - Test single field retrieval
   - Test multiple field retrieval
   - Test invalid execution_id
   - Test invalid field paths

8. **`tests/test_mcp_server/test_read_fields_tool.py`** (~80 lines)
   - Test MCP tool interface
   - Test CLI/MCP parity
   - Test async/sync bridge

### Files to Modify (5 files)

1. **`src/pflow/execution/formatters/node_output_formatter.py`**
   - **Line 192**: Add `include_values: bool = False` parameter to `format_structure_output()`
   - **Lines 204-206**: Wrap `format_output_values()` call in `if include_values:`
   - **After line 226**: Add execution_id to output when provided

2. **`src/pflow/cli/registry_run.py`**
   - **Before line 198** (node execution): Generate execution_id
   - **After line 221** (successful execution): Cache outputs via ExecutionCache
   - **Line 265**: Add execution_id parameter to format call
   - **Error handling**: Don't cache if execution fails

3. **`src/pflow/mcp_server/services/execution_service.py`**
   - **Mirror CLI changes**: Generate execution_id, cache outputs
   - **Line 610**: Add execution_id parameter to format call
   - **Ensure parity**: Exact same behavior as CLI

4. **`src/pflow/mcp_server/tools/execution_tools.py`**
   - **Add new tool**: `read_fields(execution_id: str, fields: list[str]) -> str`
   - **Follow pattern**: Use `@mcp.tool()` decorator + `asyncio.to_thread()`
   - **Service call**: Delegate to new `FieldService.read_fields()`

5. **`src/pflow/cli/main_wrapper.py`** (if needed)
   - **Add command**: Import and register `read-fields` command
   - **Verify**: Check if auto-discovery works or explicit registration needed

---

## 🔄 Implementation Phases (Detailed)

### Phase 1: ExecutionCache Foundation
**Goal**: Create cache management without changing any user-facing behavior

#### 1.1 Create ExecutionCache Class
**File**: `src/pflow/core/execution_cache.py`

```python
from pathlib import Path
import json
import time
import secrets
from typing import Any, Optional
import base64

class ExecutionCache:
    """Manage cached node execution results for structure-only mode."""

    def __init__(self):
        self.cache_dir = Path.home() / ".pflow" / "cache" / "registry-run"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def generate_execution_id() -> str:
        """Generate unique execution ID: exec-{timestamp}-{random}"""
        timestamp = int(time.time())
        random_hex = secrets.token_hex(4)  # 8 chars
        return f"exec-{timestamp}-{random_hex}"

    def store(
        self,
        execution_id: str,
        node_type: str,
        params: dict[str, Any],
        outputs: dict[str, Any]
    ) -> None:
        """Store execution results in cache."""
        # Handle binary data encoding
        encoded_outputs = self._encode_binary(outputs)

        cache_data = {
            "execution_id": execution_id,
            "node_type": node_type,
            "timestamp": time.time(),
            "ttl_hours": 24,  # Stored but not enforced in MVP
            "params": params,
            "outputs": encoded_outputs
        }

        filepath = self.cache_dir / f"{execution_id}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2, default=str)

    def retrieve(self, execution_id: str) -> Optional[dict[str, Any]]:
        """Retrieve cached execution results."""
        filepath = self.cache_dir / f"{execution_id}.json"

        if not filepath.exists():
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            cache_data = json.load(f)

        # Decode binary data
        cache_data["outputs"] = self._decode_binary(cache_data["outputs"])

        return cache_data

    def _encode_binary(self, data: Any) -> Any:
        """Recursively encode binary data to base64."""
        if isinstance(data, bytes):
            return {
                "__type": "base64",
                "data": base64.b64encode(data).decode("ascii")
            }
        elif isinstance(data, dict):
            return {k: self._encode_binary(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._encode_binary(item) for item in data]
        return data

    def _decode_binary(self, data: Any) -> Any:
        """Recursively decode base64 data to bytes."""
        if isinstance(data, dict):
            if data.get("__type") == "base64":
                return base64.b64decode(data["data"])
            return {k: self._decode_binary(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._decode_binary(item) for item in data]
        return data
```

#### 1.2 Write Tests
**File**: `tests/test_core/test_execution_cache.py`

**Test cases**:
- ✅ generate_execution_id() creates unique IDs with correct format
- ✅ store() creates cache file with correct structure
- ✅ retrieve() returns None for nonexistent execution_id
- ✅ retrieve() returns correct data for existing execution_id
- ✅ Binary data encoded/decoded correctly
- ✅ Nested structures with binary data handled
- ✅ Cache directory created if doesn't exist

**Run tests**: `uv run python -m pytest tests/test_core/test_execution_cache.py -v`

---

### Phase 2: Modify Formatter for Structure-Only

#### 2.1 Update format_structure_output()
**File**: `src/pflow/execution/formatters/node_output_formatter.py`

**Changes**:

```python
def format_structure_output(
    node_type: str,
    outputs: dict[str, Any],
    shared_store: dict[str, Any],
    registry: Registry,
    execution_time_ms: int,
    include_values: bool = False,  # NEW - default False for structure-only
    execution_id: Optional[str] = None,  # NEW - for display
) -> str:
    """Format node output showing structure/template paths.

    Args:
        include_values: If True, show actual data values before template paths.
                       If False (default), show only template paths (structure-only mode).
        execution_id: Optional execution ID to display for later field retrieval.
    """
    lines = ["✓ Node executed successfully\n"]

    # Show execution ID if provided (NEW)
    if execution_id:
        lines.append(f"Execution ID: {execution_id}\n")

    # MODIFIED - Only show values if explicitly requested
    if include_values:
        output_lines = format_output_values(outputs)
        lines.extend(output_lines)

    # Extract and display template paths (UNCHANGED)
    metadata_paths, has_any_type = extract_metadata_paths(node_type, registry)

    if not metadata_paths:
        # Fallback: infer from outputs
        from pflow.runtime.template_validator import TemplateValidator

        flattened = []
        for key, value in outputs.items():
            type_info = _infer_type(value)
            paths = TemplateValidator._flatten_output_structure(
                base_key=key,
                base_type=type_info["type"],
                structure=type_info.get("structure", {})
            )
            flattened.extend(paths)

        metadata_paths = flattened

    # Display template paths
    lines.append("\nAvailable template paths:")
    for path_info in metadata_paths:
        if isinstance(path_info, tuple):
            path, type_str = path_info
            lines.append(f"  ✓ ${{{path}}} ({type_str})")
        else:
            lines.append(f"  ✓ ${{{path_info}}}")

    return "\n".join(lines)
```

#### 2.2 Write Tests
**File**: `tests/test_execution/formatters/test_node_output_formatter.py` (modify existing)

**New test cases**:
- ✅ format_structure_output with include_values=False shows no data
- ✅ format_structure_output with include_values=True shows data (backward compat)
- ✅ format_structure_output with execution_id displays it
- ✅ Template paths displayed correctly in both modes

**Run tests**: `uv run python -m pytest tests/test_execution/formatters/test_node_output_formatter.py -v`

---

### Phase 3: Update Registry Run CLI

#### 3.1 Modify registry_run.py
**File**: `src/pflow/cli/registry_run.py`

**Changes**:

```python
# Add import at top
from pflow.core.execution_cache import ExecutionCache

# In run() function, BEFORE node execution (around line 195):
# Generate execution ID
from pflow.core.execution_cache import ExecutionCache
cache = ExecutionCache()
execution_id = cache.generate_execution_id()

# Store in shared for potential node access
shared["__execution_id__"] = execution_id

# AFTER successful node execution (around line 221):
try:
    # ... existing execution code ...

    # Cache the execution results (NEW)
    try:
        cache.store(
            execution_id=execution_id,
            node_type=node_type,
            params=resolved_params,  # After template resolution
            outputs=outputs
        )
    except Exception as cache_error:
        # Log warning but don't fail execution
        click.echo(f"⚠️  Failed to cache execution: {cache_error}", err=True)

    # Format output (MODIFIED - add execution_id)
    result = format_node_output(
        node_type=node_type,
        action=action,
        outputs=outputs,
        shared_store=shared,
        execution_time_ms=execution_time_ms,
        registry=registry,
        format_type="structure",  # Always structure mode
        execution_id=execution_id,  # NEW - pass execution_id
    )

except Exception as e:
    # Don't cache failed executions
    # ... existing error handling ...
```

#### 3.2 Write Tests
**File**: `tests/test_cli/test_registry_run.py` (modify existing)

**New test cases**:
- ✅ Execution ID generated and displayed
- ✅ Execution results cached after successful run
- ✅ Failed executions not cached
- ✅ Structure-only output (no values)
- ✅ Cache warning doesn't fail command

**Run tests**: `uv run python -m pytest tests/test_cli/test_registry_run.py -v`

---

### Phase 4: Update Registry Run MCP

#### 4.1 Modify execution_service.py
**File**: `src/pflow/mcp_server/services/execution_service.py`

**Changes**: Mirror Phase 3 changes exactly

```python
# Import at top
from pflow.core.execution_cache import ExecutionCache

# In registry_run() method (around line 556):
# Generate execution ID
cache = ExecutionCache()
execution_id = cache.generate_execution_id()
shared["__execution_id__"] = execution_id

# After successful execution (around line 600):
try:
    # Cache results
    cache.store(
        execution_id=execution_id,
        node_type=node_type,
        params=resolved_params,
        outputs=outputs
    )
except Exception:
    # Ignore cache errors in MCP (stateless)
    pass

# Format output (MODIFIED)
result = format_node_output(
    # ... existing params ...
    format_type="structure",
    execution_id=execution_id,
)
```

#### 4.2 Write Tests
**File**: `tests/test_mcp_server/test_execution_service.py` (modify existing)

**New test cases**:
- ✅ MCP registry_run generates execution_id
- ✅ MCP registry_run caches results
- ✅ CLI and MCP produce identical execution_id format
- ✅ CLI and MCP cache identical data structures

**Run tests**: `uv run python -m pytest tests/test_mcp_server/test_execution_service.py -v`

---

### Phase 5: Implement read-fields CLI Command

#### 5.1 Create CLI Command
**File**: `src/pflow/cli/read_fields.py`

```python
import click
import sys
from typing import Optional

@click.command(name="read-fields")
@click.argument("execution_id", type=str)
@click.argument("field_paths", nargs=-1, required=True)
@click.option(
    "--output-format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format (text or json)"
)
def read_fields(execution_id: str, field_paths: tuple[str, ...], output_format: str):
    """Read specific fields from cached registry run execution.

    EXECUTION_ID: The execution ID from a previous registry run command.
    FIELD_PATHS: One or more field paths to retrieve (e.g., result[0].title).

    Examples:
        pflow read-fields exec-1705234567-a1b2 result[0].title
        pflow read-fields exec-1705234567-a1b2 result[0].title result[0].id
    """
    try:
        from pflow.core.execution_cache import ExecutionCache
        from pflow.runtime.template_resolver import TemplateResolver
        from pflow.execution.formatters.field_output_formatter import format_field_output

        # Load cached execution
        cache = ExecutionCache()
        cache_data = cache.retrieve(execution_id)

        if cache_data is None:
            click.echo(f"❌ Execution '{execution_id}' not found in cache", err=True)
            click.echo("\nRun 'pflow registry run' to execute a node and cache results.", err=True)
            sys.exit(1)

        # Extract field values
        outputs = cache_data["outputs"]
        field_values = {}

        for field_path in field_paths:
            try:
                value = TemplateResolver.resolve_value(field_path, outputs)
                field_values[field_path] = value
            except Exception as e:
                # Store None for invalid paths
                field_values[field_path] = None

        # Format and display
        result = format_field_output(
            field_values=field_values,
            format_type=output_format
        )
        click.echo(result)

    except Exception as e:
        click.echo(f"❌ Error reading fields: {e}", err=True)
        sys.exit(1)
```

#### 5.2 Register Command
**File**: `src/pflow/cli/main_wrapper.py`

**Check if needed**: Verify if commands are auto-discovered or need explicit registration.

If needed, add:
```python
from pflow.cli.read_fields import read_fields

# In main CLI group
cli.add_command(read_fields)
```

#### 5.3 Create Field Output Formatter
**File**: `src/pflow/execution/formatters/field_output_formatter.py`

```python
from typing import Any
import json

def format_field_output(
    field_values: dict[str, Any],
    format_type: str = "text"
) -> str | dict[str, Any]:
    """Format field retrieval results.

    Args:
        field_values: Mapping of field paths to values (None if not found)
        format_type: "text" or "json"

    Returns:
        Formatted string (text mode) or dict (json mode)
    """
    if format_type == "json":
        return field_values

    # Text format
    lines = []
    for field_path, value in field_values.items():
        if value is None:
            lines.append(f"{field_path}: (not found)")
        elif isinstance(value, (dict, list)):
            # Pretty print complex values
            json_str = json.dumps(value, indent=2, default=str)
            lines.append(f"{field_path}:")
            for line in json_str.split("\n"):
                lines.append(f"  {line}")
        else:
            lines.append(f"{field_path}: {value}")

    return "\n".join(lines)
```

#### 5.4 Write Tests
**File**: `tests/test_cli/test_read_fields.py`

**Test cases**:
- ✅ Single field retrieval returns correct value
- ✅ Multiple fields retrieval returns all values
- ✅ Invalid execution_id returns error
- ✅ Invalid field path returns None
- ✅ Complex nested field paths work
- ✅ Binary data decoded correctly
- ✅ Text format displays correctly
- ✅ JSON format returns dict

**Run tests**: `uv run python -m pytest tests/test_cli/test_read_fields.py -v`

---

### Phase 6: Implement read_fields MCP Tool

#### 6.1 Add MCP Tool
**File**: `src/pflow/mcp_server/tools/execution_tools.py`

```python
from typing import Annotated
from pydantic import Field
import asyncio

# Add to existing file after other tools

@mcp.tool()
async def read_fields(
    execution_id: Annotated[str, Field(description="Execution ID from previous registry_run call (format: exec-TIMESTAMP-RANDOM)")],
    field_paths: Annotated[list[str], Field(description="List of field paths to retrieve, e.g., ['result[0].title', 'result[0].id']")],
) -> str:
    """Read specific field values from a cached registry run execution.

    This tool retrieves only the requested fields from a previous registry_run execution,
    enabling efficient data access without re-executing the node.

    Use this after registry_run to access specific data fields shown in the structure output.

    Returns a formatted string showing the field paths and their values.
    Nonexistent fields return None.
    """
    def _sync_read_fields() -> str:
        from pflow.mcp_server.services.field_service import FieldService
        return FieldService.read_fields(execution_id, field_paths)

    return await asyncio.to_thread(_sync_read_fields)
```

#### 6.2 Create Field Service
**File**: `src/pflow/mcp_server/services/field_service.py`

```python
from typing import Any
from pflow.mcp_server.services.base_service import BaseService, ensure_stateless

class FieldService(BaseService):
    """Service for reading fields from cached executions."""

    @classmethod
    @ensure_stateless
    def read_fields(cls, execution_id: str, field_paths: list[str]) -> str:
        """Read specific fields from cached execution.

        Args:
            execution_id: Execution ID from registry run
            field_paths: List of field paths to retrieve

        Returns:
            Formatted string with field values

        Raises:
            ValueError: If execution_id not found
        """
        from pflow.core.execution_cache import ExecutionCache
        from pflow.runtime.template_resolver import TemplateResolver
        from pflow.execution.formatters.field_output_formatter import format_field_output

        # Retrieve cached execution
        cache = ExecutionCache()
        cache_data = cache.retrieve(execution_id)

        if cache_data is None:
            raise ValueError(
                f"Execution '{execution_id}' not found in cache.\n"
                "Run registry_run tool first to execute a node and cache results."
            )

        # Extract field values
        outputs = cache_data["outputs"]
        field_values = {}

        for field_path in field_paths:
            try:
                value = TemplateResolver.resolve_value(field_path, outputs)
                field_values[field_path] = value
            except Exception:
                # Invalid path returns None
                field_values[field_path] = None

        # Format as text (MCP agents prefer text)
        return format_field_output(field_values, format_type="text")
```

#### 6.3 Write Tests
**File**: `tests/test_mcp_server/test_read_fields_tool.py`

**Test cases**:
- ✅ MCP tool calls service correctly
- ✅ Service returns formatted string
- ✅ CLI and MCP return identical formatted output
- ✅ Async/sync bridge works correctly
- ✅ Service raises ValueError for missing execution_id

**Run tests**: `uv run python -m pytest tests/test_mcp_server/test_read_fields_tool.py -v`

---

### Phase 7: Implement Smart Filtering

#### 7.1 Create Smart Filter Module
**File**: `src/pflow/core/smart_filter.py`

```python
from typing import Any
from pydantic import BaseModel
import llm

class FilteredFields(BaseModel):
    """Structured output for smart field filtering."""
    included_fields: list[str]
    reasoning: str

def smart_filter_fields(
    fields: list[tuple[str, str]],
    threshold: int = 50,
) -> list[tuple[str, str]]:
    """Filter fields using Haiku 4.5 when count exceeds threshold.

    Args:
        fields: List of (field_path, type_info) tuples
        threshold: Trigger filtering when field count exceeds this

    Returns:
        Filtered list of (field_path, type_info) tuples
        Falls back to original list if LLM call fails
    """
    # Don't filter if below threshold
    if len(fields) <= threshold:
        return fields

    try:
        # Build prompt
        field_list = "\n".join([f"- {path} ({type_info})" for path, type_info in fields])

        prompt = f"""You are filtering fields from an API response to show only business-relevant data.

INPUT FIELDS ({len(fields)} total):
{field_list}

FILTER RULES:
- REMOVE: URLs, internal IDs, timestamps, metadata, technical fields
- KEEP: Titles, content, status, user-facing data, business information
- TARGET: 8-15 fields maximum

Return only the field paths (without type info) that an AI agent would need to see for workflow orchestration."""

        # Call Haiku 4.5
        model = llm.get_model("anthropic/claude-haiku-4-5-20251001")
        response = model.prompt(
            prompt=prompt,
            schema=FilteredFields,
            temperature=0.0  # Deterministic
        )

        # Parse structured response
        from pflow.planning.utils.llm_helpers import parse_structured_response
        result = parse_structured_response(response, FilteredFields)

        # Filter original fields to included ones
        included_set = set(result.included_fields)
        filtered = [(path, type_info) for path, type_info in fields if path in included_set]

        return filtered if filtered else fields  # Fallback if filter removed everything

    except Exception:
        # Fallback: return all fields
        return fields
```

#### 7.2 Integrate with Formatter
**File**: `src/pflow/execution/formatters/node_output_formatter.py`

**Modify format_structure_output()**:

```python
# After extracting metadata_paths (around line 220):
from pflow.core.smart_filter import smart_filter_fields

# Apply smart filtering
original_count = len(metadata_paths)
metadata_paths = smart_filter_fields(metadata_paths, threshold=50)

# Display template paths
if len(metadata_paths) < original_count:
    lines.append(f"\nAvailable template paths ({len(metadata_paths)} of {original_count} shown):")
else:
    lines.append("\nAvailable template paths:")

for path_info in metadata_paths:
    # ... existing display logic ...
```

#### 7.3 Write Tests
**File**: `tests/test_core/test_smart_filter.py`

**Test cases**:
- ✅ Fields <= 50 not filtered (passthrough)
- ✅ Fields > 50 trigger LLM filtering
- ✅ LLM failure returns original fields (fallback)
- ✅ Filtered results contain subset of original
- ✅ Mock Haiku responses work correctly

**Run tests**: `uv run python -m pytest tests/test_core/test_smart_filter.py -v`

---

### Phase 8: Comprehensive Testing

#### 8.1 Integration Tests
**File**: `tests/test_integration/test_structure_only_flow.py` (new)

**End-to-end scenarios**:
1. ✅ `registry run` → structure + execution_id → `read-fields` → values
2. ✅ Binary data: execute → cache → retrieve → decode
3. ✅ Large response (200 fields) → smart filtering → <20 fields shown
4. ✅ MCP registry_run → MCP read_fields (full flow)
5. ✅ Failed execution → no cache entry created
6. ✅ Invalid field paths → None values returned

#### 8.2 CLI/MCP Parity Tests
**File**: `tests/test_integration/test_cli_mcp_parity.py` (modify existing)

**Parity checks**:
- ✅ CLI and MCP registry_run produce identical structure output
- ✅ CLI and MCP read-fields produce identical field output
- ✅ Execution IDs have same format
- ✅ Cache entries are identical

#### 8.3 Performance Tests
**File**: `tests/test_core/test_execution_cache_performance.py` (new)

**Performance benchmarks**:
- ✅ Cache lookup < 100ms with 100 entries
- ✅ Smart filtering < 2 seconds
- ✅ Binary encoding/decoding efficient

#### 8.4 Run Full Test Suite
```bash
# All new tests
uv run python -m pytest tests/test_core/test_execution_cache.py -v
uv run python -m pytest tests/test_core/test_smart_filter.py -v
uv run python -m pytest tests/test_cli/test_read_fields.py -v
uv run python -m pytest tests/test_mcp_server/test_read_fields_tool.py -v
uv run python -m pytest tests/test_integration/test_structure_only_flow.py -v

# Modified tests
uv run python -m pytest tests/test_execution/formatters/test_node_output_formatter.py -v
uv run python -m pytest tests/test_cli/test_registry_run.py -v
uv run python -m pytest tests/test_mcp_server/test_execution_service.py -v

# Full suite
uv run python -m pytest tests/ -v

# Code quality
make check
```

---

## 🎯 Success Criteria Checklist

Implementation complete when:

- [ ] **Execution Cache**
  - [ ] ExecutionCache class stores/retrieves correctly
  - [ ] Execution IDs use format `exec-{timestamp}-{random}`
  - [ ] Binary data encoded/decoded via base64
  - [ ] Cache files stored in `~/.pflow/cache/registry-run/`

- [ ] **Structure-Only Mode**
  - [ ] `format_structure_output()` has `include_values` parameter
  - [ ] Default behavior shows NO data values
  - [ ] Template paths displayed correctly
  - [ ] Execution ID displayed in output

- [ ] **Registry Run Changes**
  - [ ] CLI generates execution_id before execution
  - [ ] CLI caches outputs after successful execution
  - [ ] MCP mirrors CLI behavior exactly
  - [ ] Failed executions not cached

- [ ] **read-fields Command**
  - [ ] CLI command accepts execution_id + field paths
  - [ ] Supports multiple fields in one call
  - [ ] Returns formatted field values
  - [ ] Handles invalid paths gracefully

- [ ] **MCP Integration**
  - [ ] read_fields tool registered in execution_tools.py
  - [ ] FieldService implements business logic
  - [ ] CLI/MCP produce identical output

- [ ] **Smart Filtering**
  - [ ] Triggers when fields > 50
  - [ ] Uses Haiku 4.5 for filtering
  - [ ] Falls back to all fields on error
  - [ ] Reduces 200+ fields to <20

- [ ] **Testing**
  - [ ] All unit tests pass
  - [ ] Integration tests pass
  - [ ] CLI/MCP parity verified
  - [ ] `make check` passes

---

## 🚨 Potential Issues & Mitigations

### Issue 1: Large Binary Data in Cache
**Problem**: Images/PDFs could bloat cache files
**Mitigation**: Base64 encoding increases size ~33%, acceptable for MVP
**Future**: Consider separate binary storage

### Issue 2: Execution ID Collisions
**Problem**: Timestamp + random could theoretically collide
**Mitigation**: 8-char random hex = 4 billion combinations, extremely unlikely
**Future**: Add collision detection in store()

### Issue 3: Smart Filter Removes Needed Field
**Problem**: LLM might filter out important field
**Mitigation**: All fields still accessible via read-fields
**Future**: Add manual override or field hints

### Issue 4: Cache Growth Without Cleanup
**Problem**: Cache accumulates indefinitely in MVP
**Mitigation**: TTL stored in cache entries for future cleanup
**Future**: Implement automatic cleanup in post-MVP

### Issue 5: LLM Cost for Smart Filtering
**Problem**: Haiku 4.5 costs $1/million input tokens
**Mitigation**: Only triggers >50 fields, typical call ~500 tokens = $0.0005
**Future**: Add cost tracking and warnings

---

## 📊 Estimated Effort

| Phase | New Code | Tests | Total | Time Estimate |
|-------|----------|-------|-------|---------------|
| Phase 1: ExecutionCache | 80 lines | 120 lines | 200 lines | 2 hours |
| Phase 2: Formatter | 30 lines | 50 lines | 80 lines | 1 hour |
| Phase 3: CLI registry run | 40 lines | 60 lines | 100 lines | 1.5 hours |
| Phase 4: MCP registry run | 40 lines | 60 lines | 100 lines | 1.5 hours |
| Phase 5: CLI read-fields | 120 lines | 100 lines | 220 lines | 2 hours |
| Phase 6: MCP read-fields | 60 lines | 80 lines | 140 lines | 1.5 hours |
| Phase 7: Smart filtering | 60 lines | 80 lines | 140 lines | 2 hours |
| Phase 8: Integration tests | 0 lines | 150 lines | 150 lines | 2 hours |
| **TOTAL** | **430 lines** | **700 lines** | **1130 lines** | **14 hours** |

**Note**: Original estimate was 400 lines, actual is higher due to comprehensive testing.

---

## 🔄 Rollback Plan

If issues discovered during implementation:

1. **Revert formatter changes**: Set `include_values=True` as default
2. **Disable caching**: Comment out cache.store() calls
3. **Hide read-fields**: Don't register command/tool
4. **Disable smart filter**: Return fields unmodified

All changes are additive and can be safely reverted.

---

## ✅ Definition of Done

This task is complete when:

1. ✅ All 8 phases implemented and tested
2. ✅ `make test` passes with new tests
3. ✅ `make check` passes (linting, type checking)
4. ✅ Manual testing confirms:
   - `pflow registry run <node>` shows structure-only + execution_id
   - `pflow read-fields <exec-id> <path>` retrieves field value
   - MCP tools work identically
   - Smart filtering reduces 200+ fields
5. ✅ Documentation updated (if needed)
6. ✅ All success criteria checked off

---

## 📝 Notes for Reviewer

**Key decisions made**:
- Execution ID format matches handover spec (timestamp-based, not UUID)
- Structure-only is DEFAULT (breaking change acceptable in MVP)
- No automatic cache cleanup in MVP (TTL stored for future)
- Smart filter threshold = 50 (tunable constant)
- Binary data uses existing base64 pattern

**Architecture highlights**:
- 100% code sharing between CLI and MCP via formatters
- Stateless service pattern maintained
- No new abstractions introduced
- Follows all existing pflow patterns

**Testing strategy**:
- Unit tests for each component
- Integration tests for end-to-end flows
- Parity tests ensure CLI/MCP identical
- Performance tests validate <100ms cache lookup

**Questions for review**:
1. Is structure-only as DEFAULT acceptable? (vs opt-in with flag)
2. Should we add --show-values flag for old behavior?
3. Is 50 field threshold appropriate for smart filtering?
4. Should cache cleanup be manual (`pflow cache clean`) in MVP?

---

**Ready for implementation upon approval** ✅
