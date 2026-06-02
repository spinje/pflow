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

## Choosing a Workflow Test Pattern

The repo has four distinct patterns for getting a workflow into a test. Each tests a different stack slice. Pick by which layer is part of the system under test — don't mix patterns for the same scenario.

| Pattern | Layer(s) exercised | Per-test cost | When to use |
|---|---|---|---|
| **1. Inline IR dict** → `WorkflowRunner().run(ir_dict, ...)` | Compiler + engine + runner | ~5-10ms | **Default.** Testing IR shapes, internal invariants, compiler behavior, parameterized edge cases, anything where the parser isn't part of the system under test |
| **2. `tmp_path` fixture** (via `tests/shared/markdown_utils.py`) → `runner.run(str(path), ...)` | Parser + full in-process pipeline | ~20-30ms | When the scenario needs a real file but the content is test-specific and not reusable |
| **3. Committed fixture** under `examples/error-handling/` (or similar) → `runner.run(str(fixture_path), ...)` | Parser + full in-process pipeline + renderer text surface | ~10-20ms | **See decision rule below** |
| **4. Real subprocess** → `subprocess.run([pflow, ...])` | Real CLI surface: stderr routing, `logger.*`, exit codes, progress streaming | 300-500ms | CLI-surface behavior that CliRunner can't reach. Mark as `e2e`. See `test_progress_streaming_subprocess.py` |

### Decision rule for committed fixtures (Pattern 3)

**Use a committed fixture in `examples/<subdir>/` + a file-based test when ALL of these hold:**

1. The scenario demonstrates **user-facing behavior** (could plausibly help a user debug their own workflow)
2. **The parser layer is part of what's being tested** (source line tracking, YAML parsing, code-fence handling) **OR** rendered output text is part of the assertion (not just structured context data)
3. You'd **re-run the fixture manually during debugging** — e.g., `pflow examples/error-handling/loop-recovery.pflow.md`
4. The fixture has a **natural descriptive name** (`typo-on-failed-node.pflow.md`, not `edge_case_42.pflow.md`)

**Use inline IR (Pattern 1) otherwise.** Specifically, inline IR is the right default for:
- Tests about specific IR shapes the parser wouldn't produce
- Parameterized tests with `@pytest.mark.parametrize`
- Internal-invariant tests (e.g., "after `mark_node_failed`, `__failures__[id]` has these keys")
- Tests asserting on exception types or compiler rejections
- Anything where the scenario doesn't have pedagogical value

**Never dual-write**: if a scenario exists as both an inline-IR test and a fixture test, delete one. The fixture wins if the parser matters or rendered text is asserted; the inline IR wins otherwise.

### Committed fixture directories

| Directory | Purpose | Test file |
|---|---|---|
| `examples/invalid/` | Parse/schema errors (workflows that should fail at parse time) | `tests/test_docs/test_example_validation.py` |
| `examples/error-handling/` | Runtime error scenarios (failed nodes, coalesce, typo hints, source lines) | `tests/test_integration/test_failed_node_invariant.py` |

**Never rename, move, or delete files in these directories without running their bound tests first.** Committed fixtures double as regression guards and user-facing examples; a typo-fix edit can silently break both contracts.

**`test_docs/test_example_validation.py` auto-discovers via `rglob("*.pflow.md")`** — any new `.pflow.md` file you add under `examples/` automatically gets IR-schema-validated for free. This is load-bearing for Pattern 3: you get schema-level regression coverage without writing any test code.

### Fixture drift risk

Pattern 3's cost is fixture drift: someone edits a fixture "to fix a typo" and silently breaks test assertions that match on specific rendered text. Mitigations:

1. **The fixture's purpose is documented in `examples/<subdir>/README.md`** — edits should match the documented contract
2. **Tests assert on specific substring markers** (`"file:N"`, `"${primary.stdout ?? fallback.stdout}"`) that encode the scenario's load-bearing features — if an edit changes these, the test fails loudly rather than passing on a drifted scenario
3. **Mutation-test your assertions**: temporarily break the production code path you expect the test to catch, confirm the test fails. If the test still passes under mutation, the assertion is too loose

## Autouse Fixtures (tests/conftest.py)

These run automatically for every test — you do NOT need to set them up:
- **`mock_llm_client`**: Patches `pflow.core.llm_client.complete` (and each consumer module's `complete` binding) with `MockLLMClient`. Returns `AdapterResponse` instances. **Skips** tests in `/llm/` directories (they use real APIs when `RUN_LLM_TESTS=1`).
- **`isolate_pflow_config`**: Creates isolated `tmp_path/.pflow/` dir, redirects `Registry`, `SettingsManager`, `MCPServerManager`, and `WorkflowManager` to temp paths. Default `Registry()` loads precomputed core nodes from memory to avoid per-test registry JSON writes.
- **`disable_trace_file_writes_by_default`**: Makes `WorkflowTraceCollector.save_to_file()` a no-op unless the test is marked `trace_files`. In-memory `ExecutionResult.trace` still exists; only disk writes to `.pflow/debug` are suppressed.

**Surprise**: `isolate_pflow_config` gives every test a registry with all core nodes already loaded. If you need an **empty** registry, create one with an explicit temp path.

**Important**: the default isolated `registry_path` may not exist on disk. This is intentional. Tests that assert registry persistence must create `Registry(explicit_tmp_path)` or write the default `registry_path` themselves.

**Tip**: `isolate_pflow_config` yields a dict with keys `pflow_dir`, `registry_path`, `settings_path`, `mcp_servers_path`, `workflows_path`. Capture it to inspect or manipulate isolated paths:
```python
def test_something(isolate_pflow_config):
    paths = isolate_pflow_config
    assert paths["pflow_dir"].exists()
```

**Performance**: Registry scan happens ONCE per session (~0.2s), not per test. Default tests use the precomputed nodes in memory; this avoids writing hundreds of ~48K `registry.json` files during a full run.

### LLM Mock Resolution Chain

When a test calls an LLM, the mock resolves in this order:
1. Exact model+schema match (e.g., `"anthropic/claude-sonnet-4-5"` + `WorkflowDecision`)
2. Wildcard `"*"` + schema match
3. Built-in schema defaults (has defaults for `WorkflowDecision`, `ComponentSelection`, `FilteredFields`)
4. Final fallback: `{"response": "mock response"}`

If your custom mock isn't being used, check that model name AND schema type both match.

**Mock behavior notes**:
- `response.text` is a **string attribute** (not callable). Asserting `response.text()` raises `TypeError`.
- `response.usage` is a dict — read fields with `usage["input_tokens"]`, etc.
- `call_history` entries **truncate prompts to 500 chars** — don't assert on long prompt content. `call_history_full` is the parallel untruncated record (used for cache-structure tests).
- `cost_usd` defaults to `None` in the returned usage dict (mirrors production for unknown-pricing models like Ollama). Tests that need a specific cost should pass `cost_usd=` to `set_response`.
- `response.warnings` is a list of structured warning dicts (`kind`, `text`, `context`). Defaults to `[]`. Tests that need warning paths should pass `warnings=` to `set_response`.
- `reset()` clears custom responses, costs, warnings, and call history; built-in `_DEFAULT_RESPONSES` for known schemas remain available.

## Conftest Hierarchy

| File | What it provides |
|------|-----------------|
| `tests/conftest.py` | Root: auto-applied LLM mock, isolated config, test nodes |
| `tests/shared/llm_mock.py` | `MockLLMClient` — patches the adapter seam (`pflow.core.llm_client.complete`) |

To configure LLM mock responses:
```python
def test_something(mock_llm_client):
    mock_llm_client.set_response(
        "anthropic/claude-sonnet-4-5",
        WorkflowDecision,
        {"found": True, "workflow_name": "test"},
        cost_usd=0.000123,  # optional — defaults to None
        warnings=[],        # optional — defaults to []
    )
```

## Pytest Markers

Registered in `pyproject.toml`:
- **`serial`**: Tests that must run sequentially (deselect with `-m "not serial"`)
- **`integration`**: Tests that spawn subprocesses
- **`e2e`**: Real process, shell-pipe, external CLI boundary, or other slow environment-boundary tests. Excluded from default `make test`; run with `make test-e2e`.
- **`trace_files`**: Tests that need real workflow trace JSON files. Without this marker, `save_to_file()` is a no-op under pytest.

Other markers used across the suite:
- `@pytest.mark.skipif(not os.getenv("RUN_LLM_TESTS"), ...)` — gates real LLM API tests
- `@pytest.mark.skipif(sys.platform == "win32", ...)` — Unix-only pipe/SIGPIPE tests
- `@pytest.mark.skipif(sys.version_info < (3, 11), ...)` — ExceptionGroup requires 3.11+

## Make Test Commands

| Command | Workers | What it excludes |
|---------|---------|-----------------|
| `make test` | `-n 4` | `test_llm_integration.py`, `e2e` |
| `make test-debug` | sequential | Same exclusions |
| `make test-e2e` | `-n 4 --dist=worksteal` | Non-`e2e`, LLM integration |
| `make test-all-local` | `-n 4 --dist=worksteal` | `test_llm_integration.py` only |
| `make test-llm` | sequential | Only runs LLM-specific tests |
| `make test-all` | `-n 4` | Nothing — runs everything |
| `make test-with-skipped` | sequential | Nothing — shows skip reasons |

All commands include `--doctest-modules`, but `pyproject.toml` sets `testpaths = ["tests"]`, so collection only ever reaches `tests/` — **`src/pflow/` doctests are NOT collected by any `make` target**. They run only when pytest is pointed directly at a source path, e.g. `pytest --doctest-modules src/pflow/runtime/template_validation/type_checker.py`. Keep src doctests runnable anyway: if `testpaths` ever gains `src`, a stale example becomes a build failure.

## Subprocess Test Fixtures

Use shared fixtures from `tests/conftest.py` for real CLI subprocess tests:
- **`uv_exe`**: Finds `uv` or skips the test
- **`prepared_subprocess_env`**: Creates isolated HOME, writes pre-populated registry JSON

```python
def test_cli_subprocess(tmp_path, uv_exe, prepared_subprocess_env):
    env = prepared_subprocess_env
    completed = subprocess.run([uv_exe, "run", "pflow", "--help"], capture_output=True, text=True, env=env)
    assert completed.returncode == 0
```

**Rule: ONE subprocess test per bug/feature is usually enough.** Use unit tests for edge cases (1000x faster).

**Marker rule**: real subprocess / pipe / shell-boundary CLI tests must be marked `e2e` so they do not run in default `make test`. Use in-process `CliRunner` or `WorkflowRunner` tests for the broad matrix, and keep subprocess tests as narrow contract pins.

**Trace rule**: do not rely on trace files unless the test is marked `trace_files`. If the test only needs runtime trace events, assert on `result.trace.events`; if it needs serialized JSON, add `@pytest.mark.trace_files`.

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

### 10. CliRunner Limitations
`CliRunner` always returns `False` for `isatty()`. Can't test interactive prompts (workflow save dialog). Test execution and save functionality independently.

**CliRunner also masks stderr coherence bugs**: `logging` writes to the original stderr fd, not Click's captured stream. Partial-line corruption, logger interleaving, and pipe routing bugs are invisible to CliRunner. Use real subprocess tests (Pattern 4) for anything involving stderr output, `logger.*` calls, or pipe routing.

### 11. Mock Pollution Between Test Files
Mocks from one file persist and break others → Use `@pytest.fixture(autouse=True)` with `patch.stopall()` and `importlib.reload()` for modules with persistent mocks.

### 12. Test Registry Must Point to Real Modules
```python
# ❌ {"module": "test.module", "class_name": "ExampleNode"}  # Module doesn't exist
# ✅ {"module": "tests.test_runtime.test_compiler_integration", "class_name": "ExampleNode"}
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

`ResultMessage` is a real `@dataclass` in that test file, not an auto-Mock. This is load-bearing: the Claude Code node probes `ResultMessage.__annotations__` at import time to verify SDK structured-output support. Keep `mock_sdk_types.ResultMessage = ResultMessage` before `sys.modules["claude_agent_sdk.types"] = mock_sdk_types`, or imports will fail before tests run.

### 18. Rewritten Tests That Assert Less Are Regression Signals
When rewriting tests during a refactor, if the new test asserts LESS than the original, the new implementation likely dropped behavior — the old test wasn't over-specified. Investigate before weakening the assertion.

### 19. Synthetic Fixtures Matching Buggy Code

Tests that construct trace events / workflow IRs by hand can pass
against buggy production code if the fixture happens to encode the
bug-compatible shape. Symptom: tests are green, the bug fires in
production, agents trust green tests over real-world output.

**Defenses that work in this codebase:**

- **Builder/producer shape parity tests.** `TraceFixtureBuilder` ships
  with `TestTraceFixtureBuilderShapeParity` (`tests/test_core/test_trace_tree.py`)
  that drives a real `WorkflowTraceCollector` and asserts the builder's
  output keys match the producer's keys. If the builder drifts, every
  test using it fails noisily.
- **Committed-fixture drift detection.** `tests/fixtures/cache_analysis/_generate.py`
  is the single source of truth for committed JSON fixtures;
  `test_committed_cache_analysis_fixtures_match_generator_output`
  fails when committed JSON drifts from generator output. The failure
  message includes the regen command verbatim.
- **Subprocess CLI integration tests.** End-to-end via `pflow ...` on
  real-shape fixtures (e.g.,
  `test_analyze_cache_rolls_up_three_deep_sub_workflow_costs`)
  catches the integration class that unit tests miss.
- **Verification specialist passes** with real CLI on real workflows
  (e.g., the gemini-smoke fixture set under `scratchpads/`). Manual
  but high-leverage; the bugs that hit Task 159 across 4+ phases were
  found here, not by the test suite.

**Defense that didn't earn its keep and was removed:** per-test
`@mutation_contract` markers + `make mutation-audit` verifier.
Operational data across 4 cleanup phases on `feat/prompt-caching`:
1 real bug caught, 6+ line-shift drifts requiring mechanical updates,
32 stale contracts at peak. The infrastructure was deleted because
the maintenance cost exceeded the catch rate. Future test-fidelity
efforts should reinforce the four defenses above rather than
reintroduce per-test markers.

### 20. Cross-Layer Features Need End-to-End Tests Through `WorkflowRunner`
Unit tests that mock the boundary you're testing will pass while the real pipeline breaks. When a feature crosses ≥2 layers (e.g. shared store → engine → runner → formatter), write at least one test that runs through `WorkflowRunner().run()` and inspects `result.shared_after` / `result.diagnostics` end-to-end. Failure modes that this catches:
- Engine archives data correctly but the runner drops `shared_store` on the exception path
- Diagnostic context is populated correctly but the renderer never consumes it
- Single layer's tests pass; the integration breaks because each layer is "right by itself"

Pattern: build the IR dict, run through `WorkflowRunner`, assert on `result.shared_after["__failures__"]` and the structured `result.diagnostics[i].context` rather than mocking `_extract_runtime_warnings` or `build_execution_steps` in isolation.
