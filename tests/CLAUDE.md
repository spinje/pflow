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
| **4. Real subprocess** → `subprocess.run([pflow, ...])` | Real CLI surface: stderr routing, `logger.*`, exit codes, progress streaming | 300-500ms | CLI-surface behavior that CliRunner can't reach. See `test_progress_streaming_subprocess.py` |

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
- **`isolate_pflow_config`**: Creates isolated `tmp_path/.pflow/` dir, redirects `Registry`, `SettingsManager`, `MCPServerManager`, and `WorkflowManager` to temp paths. **Pre-populates registry with all core nodes.**

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
- **`prepared_subprocess_env`**: Creates isolated HOME, writes pre-populated registry JSON

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

### 18. Rewritten Tests That Assert Less Are Regression Signals
When rewriting tests during a refactor, if the new test asserts LESS than the original, the new implementation likely dropped behavior — the old test wasn't over-specified. Investigate before weakening the assertion.

### 19. Mutation-Contract Markers — Optional Documentation, Ad-Hoc Audit

`@mutation_contract` is a **lightweight documentation pattern** for tests that defend a specific production line. The decorator carries machine-readable metadata (file, line, revert substring, expected failure) so readers can find what each test claims to defend; the verifier (`make mutation-audit`) re-runs that claim on demand.

```python
from tests.shared.mutation_contract import mutation_contract

@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=215,
    revert='if event.get("cached") and event.get("llm_call") is None',
    expected_failure="cost_for_node degrades to (None, 'unavailable')",
)
def test_cost_for_node_cached_event_returns_zero_trace() -> None:
    """Mutation contract: drop the cached short-circuit -> ..."""
    ...
```

**Positioning** — operational data over four cleanup phases shows the markers' actual catch rate is low (mostly line-shift drift after refactors, occasionally an anachronistic contract whose target code has moved). The markers earn their keep as **documentation that doesn't lie**, not as a per-PR safety net. The verifier is an audit tool, not a quality gate.

- **Optional on new tests.** Write `@mutation_contract` when you want the next reader to know exactly what your test defends. Skip it when the test's assertions and the production code path are obvious.
- **Run `make mutation-audit` ad-hoc.** Before a release, when reviewing a sketchy refactor, or when test count balloons — not on every PR. The audit catches test rot (assertion no longer maps to claimed line) and stale line-pin drift.
- **Conftest enforcement is alignment-only.** `tests/conftest.py` fails collection if a docstring claims `Mutation contract:` without a `@mutation_contract` decorator. It does NOT require decoration of new tests — only enforces honesty when a test author chooses to claim a contract.

**Mechanics** (for when you run the audit). For each `@mutation_contract`-decorated test, the verifier:
1. Backs up the production file.
2. Replaces the matched line with `<indent>pass  # MUTATED: <original>`.
3. Runs only that test via subprocess pytest.
4. Restores the file unconditionally.
5. Asserts the test **failed** under mutation; passes count as broken contracts.

**Things that bite** (preserved here so re-derivation isn't needed):

- `revert` must be a unique substring appearing verbatim on `line`. Production refactors that rename or move the matched substring fail loudly with `revert substring not found` — that's the drift signal, not a verifier bug.
- Import-skip is a verification failure. A test module that fails to import hides every marker it contains; the verifier exits non-zero when any module fails to import.
- Pyc cache invalidation is load-bearing. The verifier deletes `__pycache__/*.pyc` for the mutated file before each subprocess. Python's pyc mtime check is second-resolution; multiple mutations within one second silently use stale bytecode without this step.
- Subprocess timeout (60s) prevents verifier hangs. A mutation that hangs the test indefinitely is treated as "mutation caught."

**Cost note** — every refactor that touches `line` numbers in marked production files pays a small mechanical-update tax (find new line, update marker). For load-bearing contracts the tax is worth it; for cosmetic asserts it isn't. Bias toward markers on the architectural seams (cache walker policy, projection vs actually-paid split, workflow-scope keying) and skip them on routine assertions.

### 20. Cross-Layer Features Need End-to-End Tests Through `WorkflowRunner`
Unit tests that mock the boundary you're testing will pass while the real pipeline breaks. When a feature crosses ≥2 layers (e.g. shared store → engine → runner → formatter), write at least one test that runs through `WorkflowRunner().run()` and inspects `result.shared_after` / `result.diagnostics` end-to-end. Failure modes that this catches:
- Engine archives data correctly but the runner drops `shared_store` on the exception path
- Diagnostic context is populated correctly but the renderer never consumes it
- Single layer's tests pass; the integration breaks because each layer is "right by itself"

Pattern: build the IR dict, run through `WorkflowRunner`, assert on `result.shared_after["__failures__"]` and the structured `result.diagnostics[i].context` rather than mocking `_extract_runtime_warnings` or `build_execution_steps` in isolation.
