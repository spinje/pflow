# Test Navigation and Guidelines

## Find the test owner

| Concern | Start here |
|---------|------------|
| Isolation, LLM mocking, trace opt-in, subprocess environments | `tests/conftest.py` |
| Workflow files, typed diagnostics, mock node interfaces | `tests/shared/markdown_utils.py`, `tests/shared/diagnostic_helpers.py`, `tests/shared/mock_nodes.py` |
| LLM responses/history | `tests/shared/llm_mock.py::MockLLMClient` |
| CLI capture and real process boundaries | `tests/test_cli/CLAUDE.md` |
| Runner and cross-layer regressions | `tests/test_execution/`, `tests/test_integration/test_failed_node_invariant.py` |
| Compiler, engine, batch, cache, tracing | `tests/test_runtime/`; template validation has its own `CLAUDE.md` |
| Node behavior and agent backends | `tests/test_nodes/`; Claude SDK constraint below |
| Registry/scanning; MCP client versus server | `tests/test_registry/`; `tests/test_mcp/` versus `tests/test_mcp_server/` |
| Example/document contracts | `tests/test_docs/`, `examples/CLAUDE.md` |
| Import boundaries; encoding guard | `tests/test_import_hygiene.py`, `tests/test_encoding_warning_net.py` |
| Trace fixture parity and generation | `tests/test_core/test_trace_tree.py`; pitfall #19 below |

Most unit tests follow `src/pflow/X/module.py` → `tests/test_X/test_module.py`; integration contracts often live with their caller. Paths beginning `test_` below are relative to `tests/`.

## Choosing a Workflow Test Pattern

| Pattern | Boundary exercised | Use when |
|---------|--------------------|----------|
| Inline IR → `WorkflowRunner().run(ir, ...)` | Compiler, engine, runner | Runtime behavior or IR shapes without parser involvement |
| Temporary `.pflow.md` → runner | Parser and in-process pipeline | File/parser behavior needs scenario-specific text |
| Committed example → runner | Reusable file, source locations, rendered diagnostics | Also useful for manual debugging; see `examples/error-handling/README.md` |
| Real subprocess | Process descriptors, pipes, logging/progress interleaving | In-process capture cannot establish the contract; mark `e2e` |

Use real nodes/shared-store behavior for integration contracts rather than mocking the boundary under test. Keep subprocess cases focused and cover the broader scenario matrix in-process.

Avoid maintaining both inline IR and a committed fixture for the same contract. Prefer the fixture when parser provenance or rendered text is under test; otherwise prefer inline IR. Keep both only when they assert distinct contracts.

Use `tests/shared/markdown_utils.py::write_workflow_file` / `ir_to_markdown` for ordinary generated files. Deliberate malformed-syntax tests can write literal markdown. The helper is **not a general IR round-trip serializer**: it omits `edges`, `start_node`, and `ir_version`; reads `purpose` from the node, not `params`; and inline leading whitespace can be lost during parsing.

Check `examples/CLAUDE.md` and references to a committed fixture before changing or moving it; rerun its bound tests. Source-line assertions can depend on prose and blank lines.

## Autouse fixtures and isolation

`tests/conftest.py` supplies these automatically:

| Fixture | Non-obvious boundary |
|---------|----------------------|
| `isolate_pflow_config` | Redirects both `Path.home()` and `HOME`, manager paths, registry, and memoization cache. Yields isolated config paths; `DEBUG_TEST_PATHS=1` prints them. |
| `mock_llm_client` | Patches `pflow.core.llm_client.complete` and imported consumer bindings; yields `MockLLMClient`. |
| `_inject_fake_llm_api_keys` | Supplies absent canonical-provider keys so validation reaches mocked calls. `no_fake_llm_keys` instead clears ANTHROPIC/OPENAI/GEMINI/GOOGLE key variables, including the Gemini alias. |
| `_block_upstream_cost_map_fetch` | Blocks runtime and validator catalog fetches using separate latches. Fetch-path tests must reset the relevant latch; see `test_core/test_litellm_runtime.py`. |
| `disable_trace_file_writes_by_default` | Suppresses both buffered and streaming writes unless marked `trace_files`. In-memory `result.trace.events` remains available. |

The default isolated registry serves precomputed core nodes from memory; its `registry_path` may not exist. For persistence or empty-registry scenarios, use an explicit temporary path and initialize the intended contents: this bypasses fixture preload, but production `Registry.load()` may still scan a missing registry. `tests/shared/registry_utils.py::ensure_test_registry` provides explicit core-node population when needed.

The LLM mock and fake-key fixtures skip paths containing literal `/llm/` (or its Windows spelling), **not** `/test_llm/`. Thus `test_nodes/test_llm/test_llm_integration.py` still receives these fixtures; `RUN_LLM_TESTS` alone does not disable the mock. Check the actual adapter seam before treating a test as real-provider coverage.

### LLM mock resolution

`MockLLMClient.set_response` resolves by exact model/schema, then wildcard model/schema, then built-in schema defaults, then a generic response. Check both model and schema when a configured response is missed.

`call_history` truncates prompts to 500 characters; use `call_history_full` for full prompt/cache assertions. Responses are `AdapterResponse` objects (`text` is a string, `usage` a dict). Cost defaults to `None`; use `set_response(cost_usd=..., warnings=...)` when those paths matter. The helper owns the detailed response contract.

## Selection and I/O safeguards

Exact targets and markers live in `Makefile` and `pyproject.toml`:

- `make test` excludes `e2e`, `paid`, and the separately ignored LLM integration file. `make test-e2e` selects non-paid boundary tests; `make test-all-local` and `make test-debug` include non-paid e2e.
- `make test-llm` and `make test-all` opt into LLM integration and require an exported OpenAI key. Safe targets exclude `paid` independently of environment flags. Mark real chargeable calls `paid`; a mock does not prove real-provider coverage.
- Mark real CLI subprocess/pipe/external-tool boundaries `e2e`. Generic shell/JSON/stdin assertions should use the active Python environment, not require incidental tools such as `jq` or a `python3` alias. When an external tool is the boundary, check availability and skip explicitly if absent.
- `serial` is a selection marker, not automatic xdist serialization. Default `testpaths` is `tests`; source doctests require explicitly selecting the source path.
- Pass `encoding="utf-8"` for text file and subprocess I/O, including Python snippets embedded in workflows. Make test targets enable `PYTHONWARNDEFAULTENCODING=1`; pytest treats `EncodingWarning` as an error. Bare pytest does not itself enable that interpreter flag. Binary I/O and deliberate byte-semantics tests are exempt.
- Tests needing serialized trace files must use `trace_files`; runtime event assertions can use `result.trace.events`.

For subprocesses, use `uv_exe` and `prepared_subprocess_env` from `tests/conftest.py`. The latter writes a registry and isolates the child home; copy its dict before per-test changes. For custom environments, `set_isolated_home` sets both `HOME` and Windows `USERPROFILE`. A parent-process `Path.home` patch does not change the child.

`PYTEST_CURRENT_TEST` suppresses settings→environment injection in `src/pflow/core/llm_config.py::inject_settings_env_vars` and MCP startup, and skips `src/pflow/cli/logging_config.py::configure_logging`. Real subprocess logging tests must remove it from the child environment; see `test_cli/test_progress_streaming_subprocess.py`.

## Pitfalls and Gotchas

Numbers retained below are referenced by source and test comments.

### 2. Import hygiene

Import production code through `pflow...`, never `src.pflow...`. Both identities can resolve, producing different modules/classes: patches miss and `isinstance` fails. `tests/test_import_hygiene.py` also owns the module-level LLM adapter import allowlist and runtime→UI dependency guard. Avoid blanket module reloads as mock cleanup; they can create the same stale-binding problem.

### 10. CliRunner boundaries

CliRunner's default stdin is non-TTY. Interactive branch tests need explicit TTY seams; see `tests/test_cli/CLAUDE.md`. Captured stderr assertions are useful, but cannot establish real descriptor routing or logger/progress interleaving: existing logging handlers can retain an earlier stream. Use subprocess coverage for those contracts, with production logging enabled as described above.

For `caplog` assertions, set the intended level and logger explicitly; suite-wide logger configuration may differ from an isolated run. Example: `test_runtime/test_compiler_interfaces.py`.

### 15. Bounded real waits

Use `wait=0` for retry-count tests and short, bounded waits for synthetic race windows; don't copy production timeouts into ordinary unit tests. Real timing/process contracts need bounds appropriate to the behavior. Examples: `test_core/test_litellm_runtime.py` and `test_registry/test_registry.py`.

### 17. Claude SDK stub and class identity

`test_nodes/test_agent/conftest.py` calls `tests/shared/claude_sdk_stub.py::install()` during collection, before test modules in that directory. It replaces `claude_agent_sdk` entries in `sys.modules` without teardown. `src/pflow/nodes/agent/claude_backend.py` binds SDK objects at import; installing the stub after an earlier backend import does not replace those bindings. Run real SDK integration separately without collecting the stub-installing conftest.

Keep the stub's `ResultMessage` a real annotated class, assigned into mocked `claude_agent_sdk.types` before backend import. The backend checks its `structured_output` annotation at import time; an auto-Mock is insufficient.

### 19. Production-shaped fixtures

Synthetic traces can encode the same wrong assumption as production code. Start with `tests/shared/trace_fixture_builder.py::TraceFixtureBuilder`; `test_core/test_trace_tree.py::TestTraceFixtureBuilderShapeParity` compares covered event shapes against a real collector.

Committed cache-analysis traces come from `tests/fixtures/cache_analysis/_generate.py`. `test_committed_cache_analysis_fixtures_match_generator_output` in `test_core/test_trace_tree.py` pins them to the generator and supplies the regeneration command. Preserve these producer/parity checks when changing trace shapes. CLI fixture coverage also exists in `test_cli/test_analyze_cache.py::test_analyze_cache_rolls_up_three_deep_sub_workflow_costs` (CliRunner).

The per-test `@mutation_contract` / `mutation-audit` infrastructure was retired because marker upkeep outweighed its value. Prefer producer/parity and integration checks; focused mutation experiments do not require that infrastructure.

### 20. Cross-layer tests through WorkflowRunner

For changes spanning engine, runner, or rendering, include a test through `WorkflowRunner().run()` that observes the promised result. Inspect `result.shared_after`, structured `result.diagnostics`, and rendered output where relevant. Mocking their handoff separately can hide data dropped on error paths. `tests/test_integration/test_failed_node_invariant.py` supplies examples, including nested and batch failures.

### 21. Timeout mocks must reach the running code

A timeout test that passes after the production timeout may have missed its patch. Patch the clock/client actually called; check module identity when the running function and dotted patch target differ. `test_cli/test_ui_interaction_server.py::test_idle_connection_emits_keepalive_frames` demonstrates patching `events.__globals__` for that specific alias problem and bounding awaits so a missed patch fails quickly.

### Mock registry and node interfaces

Use registered node names or explicitly supply local mock metadata. There is no suite-wide `echo` test node: `tests/shared/mock_nodes.py::ExampleNode` uses `test_input` / `test_output`, while locally defined nodes may use other keys. Interface entries use `key`, not `name`. Registry module/class entries used for compilation must be importable; metadata-only validation mocks have a narrower contract.

`pflow.registry.context_builder.build_component_context` creates a fresh WorkflowManager when needed; pass `workflow_manager=` to control that dependency.
