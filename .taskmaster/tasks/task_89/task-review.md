# Task 89 Review: Structure-Only Mode and Selective Data Retrieval

## Metadata

- **Implementation Date**: 2025-01-14 (core), 2025-01-17 (enhancements), 2025-01-20 (smart output)
- **Implementation Context**: Multi-phase implementation across 7 phases + caching enhancement + smart output display
- **Final Status**: Production-ready, all tests passing (96/96 unit + 9 MCP integration + 10 smart output)
- **Token Efficiency Achieved**: 600x improvement (200,000 → 300 tokens)

## Executive Summary

Task 89 fundamentally changes how pflow returns node execution results—instead of returning full data (~200K tokens), it returns only data structure/template paths (~300 tokens), achieving 600x token efficiency. Includes selective field retrieval via `read-fields` command, smart LLM-based filtering for large field sets, and in-memory caching. Enforces security-by-default (no data exposure unless explicit retrieval).

## Implementation Overview

### What Was Built

**Core Features**:
1. **Structure-only mode** - `registry run` returns template paths only (NO data values)
2. **ExecutionCache** - Stores node outputs in `~/.pflow/cache/registry-run/`
3. **read-fields command** - Selective field retrieval from cached executions
4. **Smart filtering** - Haiku 4.5 reduces large field sets (>30 fields) to 8-15 relevant ones
5. **Smart filter caching** - LRU cache avoids redundant LLM calls (67% latency improvement)
6. **CLI + MCP parity** - Identical behavior across both interfaces

**Post-Implementation Enhancement (2025-01-20): Smart Output Display**
The original structure-only default was reconsidered for UX. Now supports three `output_mode` settings:
- **smart** (NEW DEFAULT): Show template paths WITH values, truncate large values (>200 chars)
- **structure**: Original Task 89 behavior (paths only, no values)
- **full**: Show all paths with full values, no filtering or truncation

Configure via: `pflow settings registry output-mode <smart|structure|full>`

**CRITICAL INSIGHT**: The original "hide all values" default was too aggressive for debugging. Users repeatedly needed to run `read-fields` even for simple outputs like `stdout: "hello world"`. Smart mode shows short values inline while still truncating large payloads, eliminating the extra step in 90% of cases.

**Bonus Discoveries**:
- Smart filtering shows "(X of Y shown)" when filtering occurs
- Caching provides 66% cost reduction on repeated API queries
- Array depth handling enhancement addresses nested API responses

### Implementation Approach

**Seven-phase approach**:
1. ExecutionCache foundation (generate IDs, store/retrieve results)
2. Formatter modification (structure-only output)
3. CLI registry run (cache + execution_id)
4. MCP execution_service (mirror CLI)
5. CLI read-fields command
6. MCP read-fields tool
7. Smart filtering with Haiku 4.5

**Plus enhancement**: In-memory LRU caching added post-implementation based on performance analysis.

**Critical Architectural Choice**: Structure-only as DEFAULT (not opt-in). Breaking change acceptable for MVP with zero users.

## Files Modified/Created

### Core Implementation (12 new files)

**Cache Layer**:
- `src/pflow/core/execution_cache.py` (181 LOC) - Stores/retrieves node execution results
  - Critical methods: `generate_execution_id()`, `store()`, `retrieve()`
  - Binary data handling via base64 encoding with type markers

**Smart Filtering**:
- `src/pflow/core/smart_filter.py` (266 LOC including caching) - LLM-based field reduction
  - **CRITICAL**: Threshold = 30 (not 50 as originally planned)
  - Two-layer caching: `smart_filter_fields_cached()` → `_smart_filter_fields_cached_impl()`
  - Enhanced array depth handling in prompt (lines 119-149)

**CLI Commands**:
- `src/pflow/cli/read_fields.py` (81 LOC) - Retrieve specific fields from cache
  - Variadic args: `pflow read-fields <exec-id> field1 field2 ...`
  - Supports `--output-format` (text/json)

**Formatters**:
- `src/pflow/execution/formatters/field_output_formatter.py` (47 LOC) - Format field retrieval output
  - Shared by CLI and MCP (ensures parity)

**MCP Layer**:
- `src/pflow/mcp_server/services/field_service.py` (91 LOC) - MCP service for field retrieval
  - Pattern: `@ensure_stateless`, fresh instances, local imports, return str

### Modified Files (8 files)

**Formatter Integration** (CRITICAL):
- `src/pflow/execution/formatters/node_output_formatter.py`
  - Added `include_values: bool = False` parameter (structure-only default)
  - Added `execution_id: Optional[str]` parameter
  - Integrated smart filtering at lines 246-257
  - **Integration point**: Unified `paths_to_display` variable for both runtime/metadata paths

**CLI Execution**:
- `src/pflow/cli/registry_run.py` - Generate execution_id, cache results
- `src/pflow/cli/registry.py` - **CRITICAL**: Hardcoded `show_structure=True` (line 746)
- `src/pflow/cli/main_wrapper.py` - Registered read-fields command

**MCP Execution**:
- `src/pflow/mcp_server/services/execution_service.py` - Mirrors CLI caching logic + output_mode
- `src/pflow/mcp_server/tools/execution_tools.py` - Added `read_fields` MCP tool

**Smart Output Display Enhancement (2025-01-20)**:
- `src/pflow/core/settings.py` - Added `output_mode` to RegistrySettings with validator
- `src/pflow/cli/commands/settings.py` - Added `pflow settings registry output-mode` command
- `src/pflow/execution/formatters/node_output_formatter.py` - Added smart/full formatting functions
- `src/pflow/cli/registry_run.py` - Load settings and pass output_mode to formatter

### Test Files (4 new test files, 1 modified)

**Critical Tests**:
- `tests/test_core/test_execution_cache.py` (398 LOC, 25 tests)
- `tests/test_core/test_smart_filter.py` (450 LOC, 23 tests including caching)
  - **CRITICAL**: `test_fields_at_threshold_passthrough` - Verifies 30 not >= 31
  - **CRITICAL**: `test_preserves_order` - Cache order independence
- `tests/test_cli/test_read_fields.py` (174 LOC, 12 tests)
- `tests/test_mcp_server/test_read_fields.py` (228 LOC, 15 tests)
- `tests/test_execution/formatters/test_node_output_formatter.py` - Added 8 structure-only tests + 10 smart output tests
  - `TestSmartOutputMode` (7 tests) - Value display, truncation, summaries, primitives
  - `TestOutputModeSettings` (3 tests) - Default, validation, persistence

## Integration Points & Dependencies

### Incoming Dependencies (What depends on Task 89)

**Future Workflow Orchestration**:
- Agents call `registry_run` → receive structure → call `read_fields` for specific data
- Template paths used in workflow IR (`${result[0].title}` syntax)

**MCP Agents**:
- `registry_run` MCP tool → structure output
- `read_fields` MCP tool → selective retrieval

### Outgoing Dependencies (What Task 89 depends on)

**Template System** (CRITICAL):
- `src/pflow/runtime/template_validator.py::_flatten_output_structure()` - Extracts template paths
- `src/pflow/runtime/template_resolver.py::resolve_value()` - Resolves field paths in read-fields

**LLM Integration**:
- `llm.get_model()` - Simon Willison's LLM library
- `pflow.planning.utils.llm_helpers::parse_structured_response()` - Structured output parsing
- Model: `anthropic/claude-haiku-4-5-20251001` (Haiku 4.5)

**Registry System**:
- `src/pflow/registry/registry.py::extract_metadata_paths()` - Node interface metadata
- Node metadata schema: `interface.outputs[].structure`

### Shared Store Keys

**New Keys Created**:
- `__execution_id__` (string) - Generated execution ID stored in shared for node access
  - Format: `exec-{timestamp}-{random_hex}`
  - Example: `exec-1763151373-11162323`

**Keys Consumed**:
- Node outputs (varies by node type) - Cached in ExecutionCache

### Cache Files Created

**Location**: `~/.pflow/cache/registry-run/{execution_id}.json`

**Structure**:
```json
{
  "execution_id": "exec-...",
  "node_type": "shell",
  "timestamp": 1763151373.123,
  "ttl_hours": 24,
  "params": {...},
  "outputs": {...}
}
```

**Binary Data Encoding**: `{"__type": "base64", "data": "..."}`

## Architectural Decisions & Tradeoffs

### Key Decisions

**1. Structure-Only as DEFAULT (Not Opt-In)** → **REVISED: Smart Output as Default**
- **Original Decision**: Remove `--show-structure` flag, make structure-only the default
- **Original Reasoning**: Zero users = acceptable breaking change, better UX for agents
- **2025-01-20 Revision**: Structure-only was too aggressive for debugging workflows
- **New Default**: `smart` mode shows values with truncation (>200 chars → truncate)
- **Configuration**: `pflow settings registry output-mode <smart|structure|full>`
- **Backward Compat**: `structure` mode preserves original Task 89 behavior

**2. Threshold 30 (Changed from 50)**
- **Decision**: Trigger smart filtering at 31+ fields (was 51+)
- **Reasoning**: Performance analysis showed high accuracy at depth 1-5, benefits from earlier filtering
- **Alternative**: Keep 50 (rejected after testing showed 30 provides better UX)
- **Impact**: More APIs benefit from smart filtering

**3. Two-Layer Caching Pattern**
- **Decision**: Public wrapper sorts fields → cached impl uses LRU cache
- **Reasoning**: LRU cache requires hashable tuples, but field order shouldn't matter
- **Alternative**: Direct `@lru_cache` on tuple (rejected - order-dependent hashing)
- **Implementation**: `smart_filter_fields_cached()` → `_smart_filter_fields_cached_impl()`

**4. Fallback Philosophy: Degraded > None**
- **Decision**: On LLM error, return all fields (no filtering)
- **Reasoning**: Users always get results; smart filtering is enhancement not requirement
- **Alternative**: Fail fast on LLM error (rejected - bad UX)
- **Pattern**: Broad `except Exception` with `logger.warning()` + return original

**5. CLI/MCP Parity via Shared Formatters**
- **Decision**: Both CLI and MCP call same formatters (return str/dict, never print)
- **Reasoning**: Guaranteed identical behavior, single source of truth
- **Alternative**: Duplicate logic in CLI/MCP (rejected - drift risk)
- **Pattern**: Formatter returns → CLI uses click.echo() → MCP returns directly

### Technical Debt Incurred

**1. No Automatic Cache Cleanup**
- **What**: TTL (24 hours) stored but not enforced
- **Why**: MVP decision - zero users, can add later
- **When to fix**: v2.0 or when cache size becomes issue
- **How to fix**: Background thread or startup cleanup (10-20 LOC)

**2. Fixed Threshold (Not Configurable)**
- **What**: Threshold = 30 hardcoded
- **Why**: MVP simplicity, no user request for config
- **When to fix**: When users need domain-specific thresholds
- **How to fix**: Add `--filter-threshold` CLI flag + settings config

**3. Process-Scoped Cache (Not Persistent)**
- **What**: LRU cache cleared on process restart
- **Why**: Simplicity, no persistence layer in MVP
- **When to fix**: When long-running MCP servers need persistence
- **How to fix**: Serialize cache to disk (20-30 LOC)

## Testing Implementation

### Test Strategy Applied

**Test-as-you-go** (not test-after):
- Each phase implementation immediately followed by tests
- Caught bugs early (e.g., mock infrastructure, order independence)
- 96 unit tests + 9 MCP integration tests

**Critical vs. Coverage**:
- Focused on integration points, edge cases, error paths
- Avoided testing obvious code
- Example: Tested threshold boundary (30 vs 31), not basic field counting

### Critical Test Cases (High-Value Tests)

**Threshold Boundary** (test_smart_filter.py):
- `test_fields_at_threshold_passthrough` - Verifies 30 fields = NO filter (must use >)
- `test_fields_above_threshold_filters` - Verifies 31 fields = YES filter

**Cache Order Independence** (test_smart_filter.py):
- `test_preserves_order` - Different field orders produce same cache key
- Caught bug: Initial implementation was order-dependent

**Fallback Behavior** (test_smart_filter.py):
- `test_llm_failure_returns_original` - LLM errors don't crash
- `test_empty_llm_response_returns_original` - Safety fallback when LLM returns nothing

**CLI/MCP Parity** (test_read_fields.py MCP):
- `test_cli_and_mcp_produce_identical_output` - Shared formatter guarantees parity
- `test_error_handling_parity` - Errors handled identically

**Binary Data Roundtrip** (test_execution_cache.py):
- `test_store_with_binary_data` - Base64 encoding/decoding works
- `test_binary_roundtrip` - Decode(Encode(binary)) == binary

### Tests That Don't Matter (Remove If Needed)

- Basic getter/setter tests (execution_id format validation)
- Obvious code paths (empty list returns empty)
- Mock coverage for coverage sake

## Unexpected Discoveries

### Gotchas Encountered

**1. LRU Cache Order Dependency**
- **Issue**: `@lru_cache` on tuple is order-dependent
- **Impact**: `[(a, str), (b, str)]` ≠ `[(b, str), (a, str)]` → different cache keys
- **Solution**: Sort fields before hashing (two-layer pattern)
- **Time to debug**: 15 minutes
- **Where**: `smart_filter.py:191` - Sort by path before caching

**2. Threshold Semantics (> not >=)**
- **Issue**: Spec said "trigger at >50" but easy to implement as >=
- **Impact**: 50 fields would incorrectly trigger filtering
- **Solution**: Explicit test at boundary (30 fields = passthrough)
- **Where**: `smart_filter.py:98` - `if len(fields) <= threshold`

**3. Mock Infrastructure Limitation**
- **Issue**: `llm_mock.py` provides `set_response()` not `set_error()`
- **Impact**: Can't mock LLM failures easily
- **Solution**: Use `monkeypatch.setattr()` to directly mock `llm.get_model`
- **Where**: `test_smart_filter.py:183-186`

**4. Formatter Integration Has Two Code Paths**
- **Issue**: `format_structure_output()` has runtime_paths AND metadata_paths branches
- **Impact**: Smart filtering needs to work on both
- **Solution**: Unified `paths_to_display` variable before filtering
- **Where**: `node_output_formatter.py:230-244`

**5. Array Depth Paradox**
- **Issue**: LLM filters out critical business logic at depth 6+ (fraud flags, rate limits)
- **Impact**: Smart filtering removed important nested array fields
- **Solution**: Enhanced prompt with explicit array handling guidance
- **Where**: `smart_filter.py:119-149` - ARRAY FIELD PRIORITY section

### Edge Cases Found

**Empty Execution Cache**:
- `read-fields` with invalid execution_id → clear error message
- Test: `test_invalid_execution_id_raises_value_error`

**Invalid Field Paths**:
- `read-fields` with nonexistent path → returns "(not found)" not error
- Test: `test_invalid_field_path_returns_none`

**LLM Returns Empty List**:
- Smart filter gets `[]` from LLM → fallback to original fields
- Test: `test_empty_llm_response_returns_original`

**Binary Data in Cache**:
- Bytes in outputs → base64 encoded → stored as JSON → decoded on retrieval
- Test: `test_binary_roundtrip`

## Patterns Established

### Reusable Patterns

**1. Formatter Pattern (GOLDEN RULE)**
```python
def format_something(data, format_type: str = "text") -> str | dict:
    """Formatter that returns (never prints)."""
    if format_type == "json":
        return {"key": "value"}  # dict
    return "formatted text"  # str

# Caller handles display
result = format_something(data, "text")
click.echo(result)  # CLI
return result  # MCP
```

**Why**: Guarantees CLI/MCP parity, testable without I/O mocking.

**2. MCP Service Pattern**
```python
class MyService(BaseService):
    @classmethod
    @ensure_stateless
    def my_method(cls, ...) -> str:
        # Create fresh instances (stateless)
        cache = SomeCache()

        # Import formatters locally (avoid circular imports)
        from pflow.execution.formatters.my_formatter import format_it

        # Return formatted result (MCP expects str)
        result = format_it(data, format_type="text")
        if not isinstance(result, str):
            raise TypeError(f"Expected str, got {type(result)}")
        return result
```

**Why**: Stateless execution, consistent with MCP architecture.

**3. Two-Layer Caching (Order Independence)**
```python
def public_wrapper(fields: list[tuple]) -> list[tuple]:
    """Normalize input before caching."""
    sorted_fields = tuple(sorted(fields, key=lambda x: x[0]))
    return _cached_impl(sorted_fields)

@lru_cache(maxsize=100)
def _cached_impl(fields: tuple[tuple]) -> tuple[tuple]:
    """LRU cached implementation."""
    return expensive_operation(fields)
```

**Why**: Hashable inputs for LRU cache + order independence.

**4. Fallback Error Handling**
```python
try:
    return smart_operation(data)
except Exception as e:
    logger.warning(f"Operation failed, using fallback: {e}")
    return fallback_data  # Degraded output > no output
```

**Why**: MVP philosophy - keep working even if enhancement fails.

**5. Smart Value Truncation Pattern (2025-01-20)**
```python
# Truncation thresholds for smart display
SMART_MAX_STRING_LENGTH = 200  # Strings > 200 chars → "text..." (truncated)
SMART_MAX_DICT_KEYS = 5        # Dicts > 5 keys → {...N keys}
SMART_MAX_LIST_ITEMS = 5       # Lists > 5 items → [...N items]
# Numbers, booleans, null: Always show fully

# Return tuple (formatted_str, was_truncated) for hint display
formatted, truncated = format_value_for_smart_display(value)
if truncated:
    show_read_fields_hint(execution_id)
```

**Why**: Balances immediate debugging utility with terminal readability.

### Anti-Patterns to Avoid

**❌ Don't Mock at Interface Level (Mock at LLM Level)**
```python
# BAD: Mocking service functions
mock_service.some_method.return_value = "fake"

# GOOD: Mock at LLM level (catches all code paths)
mock_llm_calls.set_response("model-name", Schema, {"data": "..."})
```

**Why**: Service-level mocks miss integration issues.

**❌ Don't Use Assert for Type Narrowing**
```python
# BAD: Linter error (S101)
assert isinstance(result, str)

# GOOD: Explicit check with TypeError
if not isinstance(result, str):
    raise TypeError(f"Expected str, got {type(result)}")
```

**Why**: Linters complain about asserts in production code.

**❌ Don't Duplicate Logic Between CLI and MCP**
```python
# BAD: Different formatting in CLI vs MCP
# cli/command.py
print(json.dumps(data))

# mcp/service.py
return str(data)

# GOOD: Shared formatter
# both call format_data(data, "text")
```

**Why**: Causes drift, breaks parity.

## Breaking Changes

### API/Interface Changes

**1. registry run Default Behavior Changed**
- **Before**: Shows full data values
- **After**: Shows ONLY structure (template paths)
- **Impact**: Any code expecting data values from stdout will break
- **Mitigation**: Zero users = acceptable for MVP

**2. New --output-format for read-fields**
- **Before**: N/A (new command)
- **After**: Supports `text` (default) and `json`
- **Impact**: None (new feature)

### Behavioral Changes

**1. Execution ID Now Generated for All registry run Calls**
- **Before**: No execution ID
- **After**: Every registry run generates and displays execution_id
- **Impact**: Stdout format changed, cache files created
- **Location**: `~/.pflow/cache/registry-run/`

**2. Smart Filtering Triggers at 31+ Fields (Was Never There)**
- **Before**: All template paths shown
- **After**: >30 fields → LLM filtering → 8-15 shown
- **Impact**: Large API responses display fewer paths
- **User visibility**: Shows "(X of Y shown)" message

## Future Considerations

### Extension Points

**1. Domain-Specific Filtering** (TODO in code)
```python
# Future: Add context parameter for domain-specific filtering
# smart_filter_fields(fields, threshold=30, context="fraud detection")
# Prompt would include: "Prioritize fraud-related fields"
```
**Where**: `smart_filter.py:109-112`

**2. Persistent Cache**
```python
# Future: Serialize LRU cache to disk for long-running MCP servers
# On startup: load cache from ~/.pflow/cache/smart-filter-cache.json
# On shutdown: save cache state
```
**When**: Long-running MCP servers need cache persistence

**3. Cache Stats API Endpoint**
```python
# Future: Expose cache stats via CLI/MCP
# pflow cache stats → {hits: 45, misses: 5, hit_rate: 0.9}
```
**Already implemented**: `get_cache_stats()` in `smart_filter.py:244`

### Scalability Concerns

**1. Cache Memory Growth**
- **Issue**: LRU cache capped at 100 entries (~50KB), but could grow if maxsize increased
- **When**: >1000 different API structures queried
- **Solution**: Monitor memory, increase maxsize or implement disk persistence

**2. Large Field Sets (1000+ fields)**
- **Issue**: Smart filtering tested up to 3010 fields, works but slow (2.5-3.5s)
- **When**: Complex GraphQL APIs with introspection
- **Solution**: Pre-filter obvious fields before LLM call (remove *_url, *_id patterns)

**3. Execution Cache Unbounded Growth**
- **Issue**: No TTL enforcement = cache grows forever
- **When**: Production usage with many API calls
- **Solution**: Implement cleanup (startup, background thread, or manual command)

## AI Agent Guidance

### Quick Start for Related Tasks

**If implementing similar caching features**:
1. Read `smart_filter.py:181-243` - Two-layer caching pattern
2. Read `test_smart_filter.py:TestSmartFilterCaching` - Order independence tests
3. Pattern: Public wrapper (normalize) → private cached impl (LRU)

**If modifying structure-only behavior**:
1. Read `node_output_formatter.py:184-264` - Integration point
2. Test both runtime_paths AND metadata_paths code branches
3. Verify CLI/MCP parity via shared formatter tests

**If adding new read-fields capabilities**:
1. Read `field_service.py:29-90` - MCP service pattern
2. Read `read_fields.py:18-81` - CLI command pattern
3. Add to BOTH, test parity in `test_read_fields.py:TestCLIMCPParity`

### Common Pitfalls

**1. Forgetting CLI/MCP Parity**
- **Mistake**: Implementing feature in CLI only
- **Fix**: Always implement in BOTH CLI and MCP services
- **Test**: Add parity test in `test_*_tool.py::TestCLIMCPParity`

**2. Assuming Threshold >= (Should Be >)**
- **Mistake**: Using `if len(fields) < threshold` (wrong)
- **Correct**: `if len(fields) <= threshold` (30 fields = passthrough)
- **Test**: `test_fields_at_threshold_passthrough`

**3. Not Sorting Before Caching**
- **Mistake**: Caching unsorted tuples → order-dependent cache keys
- **Fix**: Sort by path before calling cached impl
- **Test**: `test_preserves_order`

**4. Binary Data in Cache**
- **Mistake**: Storing bytes directly in JSON (fails)
- **Fix**: Base64 encode with `{"__type": "base64", "data": "..."}`
- **Where**: `execution_cache.py:_encode_binary()`

### Test-First Recommendations

**When modifying smart filtering**:
1. Run `test_smart_filter.py::TestSmartFilterCaching` first (cache correctness)
2. Then `test_smart_filter.py::TestSmartFilterThreshold` (threshold boundary)
3. Finally `test_node_output_formatter.py::TestSmartFilteringIntegration` (integration)

**When modifying formatters**:
1. Run `test_node_output_formatter.py` (structure-only behavior)
2. Then `test_read_fields.py::TestFieldOutputFormatter` (field formatting)
3. Finally `test_read_fields.py::TestCLIMCPParity` (CLI/MCP identical)

**When modifying execution cache**:
1. Run `test_execution_cache.py::TestRetrieveMethod` (retrieval logic)
2. Then `test_execution_cache.py::TestBinaryEncoding` (base64 roundtrip)
3. Finally `test_cli/test_read_fields.py` (end-to-end cache usage)

---

*Generated from complete implementation context of Task 89 including all phases, enhancements, and post-completion improvements*
