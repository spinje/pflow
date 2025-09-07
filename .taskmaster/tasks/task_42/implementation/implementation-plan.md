# Task 42: Claude Code Agentic Node - Implementation Plan

## Overview
Implement a Claude Code agentic super node using Python SDK with dynamic schema-driven outputs.

## Critical SDK Facts (Verified)
- Uses `max_thinking_tokens` NOT `max_tokens`
- NO `temperature` parameter exists
- NO `timeout` parameter in SDK (handle at asyncio level)
- Tool names: ["Read", "Write", "Edit", "Bash"] only

## Implementation Phases

### Phase 1: Package Setup (30 min)
**Objective**: Create package structure and install dependencies

**Tasks**:
1. Install claude-code-sdk: `uv pip install claude-code-sdk`
2. Create package structure:
   - `src/pflow/nodes/claude/`
   - `src/pflow/nodes/claude/__init__.py`
   - `src/pflow/nodes/claude/claude_code.py`
3. Add exports to `__init__.py`
4. Verify CLI installed: `claude --version`

**Dependencies**: claude-code-sdk package

### Phase 2: Authentication Module (45 min)
**Objective**: Implement dual authentication checking

**Tasks**:
1. Create `_check_authentication()` method:
   - Subprocess check: `claude --version`
   - Subprocess check: `claude doctor`
   - Raise user-friendly errors
2. Add restricted directory validation
3. Create dangerous bash pattern list
4. Implement tool whitelist validation

**Key Patterns**:
```python
subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5)
subprocess.run(["claude", "doctor"], capture_output=True, text=True, timeout=10)
```

### Phase 3: Core Node Implementation (2 hours)
**Objective**: Build ClaudeCodeNode with PocketFlow lifecycle

**Tasks**:
1. Create ClaudeCodeNode class extending Node
2. Implement `__init__()` with retry settings:
   - `max_retries=2` (conservative for expensive API)
   - `wait=1.0`
3. Implement `prep()` method:
   - Extract task, context, output_schema
   - Validate working directory
   - Check authentication
   - Return prep_res dict
4. Implement `post()` method:
   - Store results based on schema or fallback
   - Always return "default"

**Critical Pattern**:
```python
def __init__(self):
    super().__init__(max_retries=2, wait=1.0)  # Conservative for API costs
```

### Phase 4: Async-to-Sync Wrapper (1.5 hours)
**Objective**: Implement exact MCP pattern for async handling

**Tasks**:
1. Create `exec()` method:
   - NO try/except (let exceptions bubble)
   - Use `asyncio.run(self._exec_async(prep_res), debug=False)`
   - Return "success" or "error"
2. Create `_exec_async()` method:
   - Handle Python 3.10/3.11+ timeout differences
   - Use `asyncio.timeout` or `asyncio.wait_for`
3. Create `_call_claude()` async method:
   - Build ClaudeCodeOptions
   - Call SDK query function
   - Parse AssistantMessage responses

**Exact Pattern from MCP**:
```python
def exec(self, prep_res: dict) -> str:
    result = asyncio.run(self._exec_async(prep_res), debug=False)
    return "success"

async def _exec_async(self, prep_res: dict) -> None:
    timeout_context = getattr(asyncio, "timeout", None)
    if timeout_context is not None:
        async with timeout_context(300):
            await self._call_claude(prep_res)
    else:
        await asyncio.wait_for(self._call_claude(prep_res), timeout=300)
```

### Phase 5: Schema System (2 hours)
**Objective**: Implement schema-to-prompt conversion and JSON extraction

**Tasks**:
1. Create `_build_schema_prompt()` method:
   - Convert schema dict to JSON template
   - Generate clear instructions
   - Include field descriptions
2. Create `_extract_json()` method:
   - Strategy 1: JSON in code blocks
   - Strategy 2: Raw JSON objects
   - Strategy 3: Find `{` and match `}`
3. Implement schema merging with system_prompt
4. Handle partial/missing keys with None values

**Core Innovation**:
```python
def _build_schema_prompt(self, schema: dict) -> str:
    json_template = {}
    for key, config in schema.items():
        type_str = config.get("type", "str")
        desc = config.get("description", "")
        json_template[key] = f"<{type_str}: {desc}>"

    return f"Structure your response as JSON:\n{json.dumps(json_template, indent=2)}"
```

### Phase 6: Error Handling (1 hour)
**Objective**: Transform SDK exceptions to user messages

**Tasks**:
1. Implement `exec_fallback()` method:
   - Handle CLINotFoundError
   - Handle CLIConnectionError
   - Handle ProcessError
   - Handle TimeoutError
   - Transform to user-friendly messages
2. Add rate limit detection and guidance
3. Store errors appropriately in shared

**Pattern from LLM node**:
```python
def exec_fallback(self, prep_res: dict, exc: Exception) -> None:
    if "CLINotFoundError" in str(exc):
        raise ValueError("Claude Code CLI not installed. Install with: npm install -g @anthropic-ai/claude-code")
    # ... more error transformations
```

### Phase 7: Testing (2-3 hours)
**Objective**: Comprehensive test coverage with mocks

**Tasks**:
1. Create test directory:
   - `tests/test_nodes/test_claude/`
   - `tests/test_nodes/test_claude/test_claude_code.py`
2. Mock SDK query function
3. Mock subprocess calls
4. Test all 23 criteria from spec
5. Use test-writer-fixer subagent

**Key Mock Patterns**:
```python
@patch("pflow.nodes.claude.claude_code.query")
async def test_execution(mock_query):
    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text='{"result": "success"}')])
    mock_query.return_value = mock_response()
```

## Risk Mitigation

### Identified Risks:
1. **JSON parsing unreliability**: Mitigated with multiple extraction strategies
2. **Auth check accuracy**: Dual approach (subprocess + SDK errors)
3. **Tool name uncertainty**: Conservative whitelist
4. **Timeout insufficiency**: Configurable with 300s default

### Validation Points:
- After Phase 1: Verify SDK imports work
- After Phase 2: Test auth check with/without CLI
- After Phase 4: Test async wrapper with mock
- After Phase 5: Test JSON extraction with various formats
- After Phase 7: All 23 test criteria pass

## Success Metrics
- ✅ All test criteria from spec pass
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)
- ✅ Schema system works with fallback
- ✅ Timeout handling works correctly
- ✅ Error messages are actionable

## File Structure
```
src/pflow/nodes/claude/
├── __init__.py          # Exports ClaudeCodeNode
└── claude_code.py       # Main implementation

tests/test_nodes/test_claude/
├── __init__.py
└── test_claude_code.py  # Comprehensive tests
```

## Key Dependencies
- claude-code-sdk (Python package)
- @anthropic-ai/claude-code (npm CLI - for authentication)
- asyncio (standard library)
- subprocess (standard library)
- json, re (standard library)

## Time Estimate
- Total: 10-12 hours
- Can parallelize: Testing while implementing later phases
- Critical path: Phases 1-4 must be sequential

## Next Steps
1. Install dependencies
2. Create package structure
3. Start with authentication module
4. Build incrementally, testing each phase