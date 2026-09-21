# Testing quick reference

Read `tests/CLAUDE.md` for current fixture behavior, workflow-test patterns, test selection, and isolation safeguards. This reference states implementation obligations and routes to working examples; use the test owners below instead of copying invented APIs.

## Testing obligations

- Features, bug fixes, and refactors need meaningful tests. Write them alongside implementation, not after the work is declared complete.
- Use TDD by default for specified behavior: reproduce a bug or write the expected failure first, implement the change, then refactor with the tests passing. Exploratory work can establish the behavior as it goes; it still needs tests before completion.
- Resolve unclear requirements before encoding them as assertions. Tests must check the intended contract, not merely reproduce the implementation.
- Treat failing tests as unfinished work. Run focused checks while implementing and the required repository checks before handing off; report failures and verification limits honestly.
- Never weaken assertions to accept a bug, swallow a failure to make a test pass, or replace the behavior under test with a mock. A useful test must fail when its promised behavior is broken.

## Choose the boundary and example

Paths below are repository-relative.

| What changes | Start here |
|---|---|
| Node inputs, output, or error routing | `src/pflow/nodes/CLAUDE.md`; `tests/test_nodes/test_file/test_read_file.py` |
| Retry count, backoff, or non-retriable errors | `src/pflow/core/node.py`; `tests/test_core/test_node_retry.py` |
| Registry persistence or scanning | `tests/test_registry/test_registry.py`; `src/pflow/registry/CLAUDE.md` |
| Parser, schema, or compiler contract | The corresponding `tests/test_core/` or `tests/test_runtime/` tests; assert the promised structure when structure is the contract |
| Behavior crossing runtime, runner, and diagnostics | `tests/test_execution/test_runner.py`; `tests/test_integration/test_failed_node_invariant.py` |
| CLI command or actual process/pipe boundary | `tests/test_cli/CLAUDE.md`; `tests/CLAUDE.md` → Choosing a Workflow Test Pattern |
| Generated workflow file or structured diagnostic assertions | `tests/shared/markdown_utils.py`; `tests/shared/diagnostic_helpers.py` |
| LLM adapter calls and responses | `tests/conftest.py`; `tests/shared/llm_mock.py` |

Most unit tests follow the source layout. Integration tests belong with the boundary they exercise; a matching source/test filename is not itself a coverage requirement.

## pflow-specific traps

- Node parameters enter through `set_params`; `run(shared)` exercises prep, exec, and post. `exec` receives the prepared value, not arbitrary shared-store/keyword inputs. Inspect the concrete node's prep and post contracts before writing a direct-exec test.
- `Node._exec` owns retries. Direct `exec()` calls bypass them. The default fallback re-raises; some nodes deliberately convert exhausted failures to error results/actions. Use `pytest.raises` for expected exceptions and test the concrete node's routing where relevant. Do not swallow failures in a test node that is supposed to exercise retry.
- Use real node and shared-store behavior for integration contracts. Mock external calls or a specific dependency seam when that is outside the contract being tested. Temporary files exercise a real filesystem; use `tmp_path` or `tempfile` for isolation.
- Use `WorkflowRunner` for cross-layer workflow tests. A `CompiledWorkflow` is configuration consumed by `WorkflowEngine`, not an object with its own `run()` method. Keep lower-level tests at the lower-level boundary when that is the intended contract.
- Autouse fixtures alter registry, LLM, home-directory, and trace behavior. Check `tests/CLAUDE.md` before interpreting a test as persistence, real-provider, or serialized-trace coverage. Do not opt into paid calls without explicit authorization.
- Use `encoding="utf-8"` for text file/subprocess I/O. The Makefile enables the encoding-warning check; bare pytest does not enable the interpreter flag by itself.
- Use zero retry waits or a patched dependency for ordinary retry tests. Real timing/process contracts need short, bounded waits appropriate to their behavior; an arbitrary test-duration or mock-line threshold does not establish correctness.

## Check before handoff

Each test should have a clear behavior, a failure that diagnoses it, and no dependency on another test's execution order. Prefer one coherent assertion group; assert all parts needed to prove that contract. Run a failing test alone to diagnose it, then in the relevant suite to catch isolation problems.

Test targets and markers are defined in `Makefile` and `pyproject.toml`; their selection limits are documented in `tests/CLAUDE.md`. In a Codex sandbox, follow the `sandbox-testing` skill before running checks. Preserve required project checks and report what actually ran.
