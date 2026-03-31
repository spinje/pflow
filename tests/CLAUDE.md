# Test Navigation and Guidelines

## Test Structure

```
tests/
├── shared/                # Shared test utilities and mocks
│   ├── llm_mock.py       # LLM-level mock (prevents API calls)
│   ├── markdown_utils.py # ir_to_markdown() and write_workflow_file() for .pflow.md test files
│   ├── registry_utils.py # ensure_test_registry() helper
│   └── README.md         # Docs for shared utilities
├── test_cli/              # CLI command tests (CliRunner-based)
├── test_core/             # IR schema, shell integration, settings, workflow manager
├── test_docs/             # Documentation validation
├── test_execution/        # Execution service tests
│   └── formatters/        # Formatter tests (CLI/MCP parity, security)
├── test_integration/      # End-to-end workflow tests
├── test_mcp/              # MCP client-side integration tests (connection pool, http transport)
├── test_mcp_server/       # pflow-as-MCP-server tests
├── test_nodes/            # Node implementation tests
│   ├── test_file/         # File node tests (read/write/copy/move/delete)
│   ├── test_shell/        # Shell node tests (execution, binary, SIGPIPE, security)
│   ├── test_git/          # Git node tests (status/commit/push/checkout/log/tag)
│   ├── test_claude/       # Claude Code node tests
│   └── test_llm/          # LLM node tests (includes RUN_LLM_TESTS integration test)
├── test_registry/         # Registry, scanner, smart filter, and component discovery tests
└── test_runtime/          # Compiler, engine, template resolution, batch, caching, tracing
```

**Mapping convention**: `src/pflow/X/Y/module.py` → `tests/test_X/test_Y/test_module.py`

## Writing Workflow Test Files

**Always use `tests/shared/markdown_utils.py`** to create `.pflow.md` test files (used by 30+ test files):
```python
from tests.shared.markdown_utils import ir_to_markdown, write_workflow_file

# Write IR dict as .pflow.md file
write_workflow_file(ir_dict, tmp_path / "test.pflow.md")

# Or get markdown string directly
md_content = ir_to_markdown(ir_dict, title="Test Workflow", description="...")
```

**Gotchas with `ir_to_markdown`**:
- **Does not emit `edges`, `start_node`, or `ir_version`** — only emits `inputs`, nodes (as "Steps"), and `outputs`. The `.pflow.md` format infers execution order from step order.
- **`purpose` is read from top-level node dict**, not from `params`. If you put `purpose` inside `params`, you get a duplicate.
- Leading whitespace in param values (e.g., `" <<<"`) can be lost during markdown round-trip parsing.

## Autouse Fixtures (tests/conftest.py)

These run automatically for every test — you do NOT need to set them up:
- **`mock_llm_calls`**: Patches `llm.get_model` with mock. **Skips** tests in `/llm/` directories (they use real APIs).
- **`isolate_pflow_config`**: Creates isolated `tmp_path/.pflow/` dir, redirects `Registry`, `SettingsManager`, `MCPServerManager`, and `WorkflowManager` to temp paths. **Pre-populates registry with all core nodes.**
- **`enable_test_nodes`**: Session-scoped, sets `PFLOW_INCLUDE_TEST_NODES=true`

**Surprise**: `isolate_pflow_config` gives every test a registry with all core nodes already loaded. If you need an **empty** registry, create one with an explicit temp path.

**Tip**: `isolate_pflow_config` yields a dict with keys `pflow_dir`, `registry_path`, `settings_path`, `mcp_servers_path`, `workflows_path`. Capture it to inspect or manipulate isolated paths:
```python
def test_something(isolate_pflow_config):
    paths = isolate_pflow_config
    assert paths["registry_path"].exists()
```

**Performance**: Registry scan happens ONCE per session (~0.2s), not per test. First test in isolation pays this cost.

### LLM Mock Resolution Chain

When a test calls an LLM, the mock resolves in this order:
1. Exact model+schema match (e.g., `"anthropic/claude-sonnet-4-5"` + `WorkflowDecision`)
2. Wildcard `"*"` + schema match
3. Built-in schema defaults (has defaults for `WorkflowDecision`, `ComponentSelection`, `FilteredFields`)
4. Final fallback: `{"response": "mock response"}`

If your custom mock isn't being used, check that model name AND schema type both match.

**Mock behavior notes**:
- `response.text()` is a **callable** (not a property) — returns JSON string
- `call_history` entries **truncate prompts to 500 chars** — don't assert on long prompt content
- `reset()` clears custom responses and call_history but preserves built-in schema defaults

## Conftest Hierarchy

| File | What it provides |
|------|-----------------|
| `tests/conftest.py` | Root: auto-applied LLM mock, isolated config, test nodes |
| `tests/shared/llm_mock.py` | LLM-level mock (configurable responses) |

To configure LLM mock responses:
```python
def test_something(mock_llm_responses):
    mock_llm_responses.set_response("anthropic/claude-sonnet-4-5", WorkflowDecision, {"found": True, "workflow_name": "test"})
```

## Pytest Markers

Registered in `pyproject.toml`:
- **`serial`**: Tests that must run sequentially (deselect with `-m "not serial"`)
- **`integration`**: Tests that spawn subprocesses

Other markers used across the suite:
- `@pytest.mark.skipif(not os.getenv("RUN_LLM_TESTS"), ...)` — gates real LLM API tests
- `@pytest.mark.skipif(sys.platform == "win32", ...)` — Unix-only pipe/SIGPIPE tests
- `@pytest.mark.skipif(sys.version_info < (3, 11), ...)` — ExceptionGroup requires 3.11+

## Make Test Commands

| Command | Workers | What it excludes |
|---------|---------|-----------------|
| `make test` | `-n 4` | `test_llm_integration.py` |
| `make test-debug` | sequential | Same exclusions |
| `make test-llm` | sequential | Only runs LLM-specific tests |
| `make test-all` | `-n 4` | Nothing — runs everything |
| `make test-with-skipped` | sequential | Nothing — shows skip reasons |

All commands include `--doctest-modules` (doctests in `src/pflow/` run alongside tests).

## Subprocess Test Fixtures

Use shared fixtures from `tests/conftest.py` for real CLI subprocess tests:
- **`uv_exe`**: Finds `uv` or skips the test
- **`prepared_subprocess_env`**: Creates isolated HOME, sets `PFLOW_INCLUDE_TEST_NODES=true`, writes pre-populated registry JSON

```python
def test_cli_subprocess(tmp_path, uv_exe, prepared_subprocess_env):
    env = prepared_subprocess_env
    completed = subprocess.run([uv_exe, "run", "pflow", "--help"], capture_output=True, text=True, env=env)
    assert completed.returncode == 0
```

**Rule: ONE subprocess test per bug/feature is usually enough.** Use unit tests for edge cases (1000x faster).

For timeout-sensitive tests (e.g., hang detection), you can use minimal inline setup to avoid fixture overhead:
```python
# Special case (~0.3s): Minimal inline setup — only when fixture overhead matters
env = os.environ.copy()
env["HOME"] = str(tmp_path)
(tmp_path / ".pflow").mkdir()
registry = {"nodes": {"shell": {"module": "pflow.nodes.shell.shell", "class_name": "ShellNode"}}}
(tmp_path / ".pflow/registry.json").write_text(json.dumps(registry))
```

## `PYTEST_CURRENT_TEST` in Production Code

pytest sets `PYTEST_CURRENT_TEST` automatically. **Three production files check it** to skip dangerous operations during tests:
- `src/pflow/core/llm_config.py` — Skips LLM key detection
- `src/pflow/cli/main.py` — Guards CLI behavior
- `src/pflow/cli/logging_config.py` — Adjusts logging config

If you modify these files, be aware they behave differently under test.

**Debug env var**: Set `DEBUG_TEST_PATHS=1` to see which temp paths `isolate_pflow_config` uses per test.

## Environment Variable Isolation

For subprocess tests, use `monkeypatch.setenv("HOME", str(tmp_path))`.
For in-process tests, use `monkeypatch.setattr(Path, "home", lambda: tmp_path)`.
These are NOT interchangeable — the code under test may use either `os.environ["HOME"]` or `Path.home()`.

## Retry Testing

**ALWAYS use `wait=0`** when testing retries:
```python
node = SomeNode(max_retries=2, wait=0)  # ✅ Fast
```

## Pitfalls and Gotchas

### 1. Testing Framework Instead of Your Code
```python
# ❌ Don't hand-build complex node graphs to test retry
generator >> validator
validator - "retry" >> generator

# ✅ Test that nodes return correct action strings
action = validator.run(shared)
assert action == "retry"  # WorkflowEngine handles routing
```

### 2. Import Errors
`ModuleNotFoundError: No module named 'src'` → Run from project root, check PYTHONPATH.

### 3. File System Tests
Always use temporary directories. Clean up in `finally` blocks. Prefer `tmp_path` over `tempfile.NamedTemporaryFile(delete=False)`.

### 4. Shared State Between Tests
Tests pass alone but fail together → Ensure proper isolation, don't modify global state.

### 5. Platform-Specific Issues
Use `os.path.join()`, handle line endings, use `pathlib`.

### 6. Test Node Type Confusion
`CompilationError: Node type 'basic-node' not found` → Use actually registered nodes: `echo`, `shell`, `read-file`. Aliases like `basic-node`, `transform-node` are NOT registered. For mocked tests, define any names in your mock registry.

### 7. Test Node Interface Inconsistency
`KeyError: 'test_output'` → The `echo` node (only test node in registry) uses `message`/`echo` keys. `ExampleNode` in mocked tests uses `test_input`/`test_output`. Check node interfaces before use.

### 8. Node Interface Uses `key`, Not `name`
When building mock node interfaces, parameters use `{"key": "param_name", ...}`, NOT `{"name": "param_name", ...}`.

### 9. `purpose` Field Minimum Length
FlowIR schema requires `purpose` to be at least 10 characters. When building IR dicts for tests, don't use short strings like `"test"`.

### 10. Click Interactive Testing Limitation
`CliRunner` always returns `False` for `isatty()`. Can't test interactive prompts (workflow save dialog). Test execution and save functionality independently.

### 11. Mock Pollution Between Test Files
Mocks from one file persist and break others → Use `@pytest.fixture(autouse=True)` with `patch.stopall()` and `importlib.reload()` for modules with persistent mocks.

### 12. Test Registry Must Point to Real Modules
```python
# ❌ {"module": "test.module", "class_name": "ExampleNode"}  # Module doesn't exist
# ✅ {"module": "tests.test_runtime.test_compiler_integration", "class_name": "ExampleNode"}
# ✅ {"module": "pflow.nodes.test_node", "class_name": "ExampleNode"}
```

### 13. Context Builder Uses Fresh Instances
`pflow.registry.context_builder.build_component_context()` creates fresh `WorkflowManager` instances (no singleton). Pass `workflow_manager=` parameter to control which instance is used in tests.

### 14. Testing Implementation Instead of Behavior
```python
# ❌ Relies on default max_suggestions=5
formatted = format_suggestions(workflows)
assert "workflow-6" not in formatted

# ✅ Test the limiting behavior explicitly
formatted = format_suggestions(workflows, max_suggestions=3)
assert "workflow-3" not in formatted
```

### 15. Slow Tests Destroy Parallel Performance
A single 0.5s test caused 6.5s of total overhead with pytest-xdist due to worker scheduling.
```python
# ❌ 0.5s timeout blocks a worker
action = run_code_node(shared, code="time.sleep(10)", timeout=0.5)

# ✅ 0.05s timeout, minimal parallel impact
action = run_code_node(shared, code="time.sleep(1)", timeout=0.05)
```
**Rule**: Keep real wall-clock waiting under 0.1s.

### 16. `caplog` Requires Explicit Level + Logger Name
Tests using `caplog` pass in isolation but fail in the full suite because earlier tests modify logger configuration:
```python
# ❌ Fails in full suite — logger level was changed by a prior test
def test_warns(caplog):
    do_something()
    assert "warning message" in caplog.text

# ✅ Explicitly set level and logger name
def test_warns(caplog):
    caplog.set_level("WARNING", logger="pflow.runtime.compilation.compiler")
    do_something()
    assert "warning message" in caplog.text
```

### 17. `claude_agent_sdk` Mocked via `sys.modules` (Session-Wide)
`test_nodes/test_claude/test_claude_code.py` injects mock `claude_agent_sdk` into `sys.modules` **at module level** (not in a fixture). This happens at import time, persists for the entire pytest session, and has no cleanup. If you need to test real `claude_agent_sdk` integration, it won't work in the same pytest run.
