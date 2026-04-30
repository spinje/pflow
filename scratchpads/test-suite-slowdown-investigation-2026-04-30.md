# Test Suite Slowdown Investigation Handoff

Date: 2026-04-30
Branch: `feat/prompt-caching`
Workspace: `/Users/andfal/projects/pflow-feat-prompt-caching`

## Context

User reports the suite now takes about `114s`, up from about `20s`, while test count grew from roughly `5600` to roughly `5900`.

This investigation was performed inside Codex sandbox mode, so `make test` / `uv run` are not trustworthy here. The repo-local sandbox skill says to use:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest ...
```

The sandbox also has known failures for three subprocess tests that invoke Homebrew `uv` directly.

## Current Workspace State

The worktree was dirty during the investigation. I did not edit source or tests.

Observed dirty/staged state included Segment 4 cache-analysis work:

- New `src/pflow/core/cache_analysis/*`
- New `pflow analyze-cache` CLI command
- New MCP analyze-cache service/tool tests
- New docs/guide caching content
- Several staged files plus unstaged edits in:
  - `pyproject.toml`
  - `src/pflow/core/cache_analysis/__init__.py`
  - `src/pflow/core/cache_analysis/analyze.py`
  - `src/pflow/core/cache_analysis/render_json.py`
  - `src/pflow/core/cache_analysis/summarize.py`
  - `tests/test_core/test_cache_analysis_renderers.py`
  - `tests/test_integration/test_no_cache_flag.py`
  - `tests/test_mcp_server/test_analyze_cache_tool.py`

Approximate Segment 4 test additions:

```text
tests/test_cli/test_analyze_cache.py                         244 lines
tests/test_core/test_cache_analysis_analyze.py               287 lines
tests/test_core/test_cache_analysis_cross_workflow.py        302 lines
tests/test_core/test_cache_analysis_padding_advisor.py       121 lines
tests/test_core/test_cache_analysis_per_id_coverage.py       177 lines
tests/test_core/test_cache_analysis_renderers.py             216 lines
tests/test_core/test_cache_analysis_summarize.py             119 lines
tests/test_core/test_cache_analysis_token_estimation.py      135 lines
tests/test_core/test_cache_analysis_warnings.py              491 lines
tests/test_core/test_cache_serialization.py                   77 lines
tests/test_execution/test_plan_cache_nudge.py                127 lines
tests/test_integration/test_no_cache_flag.py                  84-87 lines
tests/test_mcp_server/test_analyze_cache_tool.py             197 lines
```

Total new Segment 4 test-line footprint: about `2577` lines.

## Commands Run And Results

### Current near-full parallel sandbox run

Command:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest \
  -n 4 \
  --doctest-modules \
  --ignore=tests/test_nodes/test_llm/test_llm_integration.py \
  -k 'not test_dry_run_json_mode_emits_no_stderr and not test_litellm_not_imported_by_cli_main and not test_progress_streams_before_downstream_nodes_complete' \
  --durations=80 \
  --durations-min=0.05 \
  -q
```

Result:

```text
5881 passed, 18 skipped in 15.87s
```

Important: this command intentionally excludes three subprocess tests because of sandbox-specific `uv` failures.

### Same near-full run with LiteLLM remote cost map disabled

Command:

```bash
HOME=/private/tmp/pflow-test-home LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python -m pytest \
  -n 4 \
  --doctest-modules \
  --ignore=tests/test_nodes/test_llm/test_llm_integration.py \
  -k 'not test_dry_run_json_mode_emits_no_stderr and not test_litellm_not_imported_by_cli_main and not test_progress_streams_before_downstream_nodes_complete' \
  -q \
  --tb=short \
  --durations=30 \
  --durations-min=0.1
```

Result:

```text
5881 passed, 18 skipped in 12.91s
real 14.42
```

This suggests LiteLLM import/model-cost-map fetch adds a small but measurable cost in the sandbox. On a non-sandbox machine with slow DNS/network, it may add much more.

### Current near-full sequential sandbox run

Command:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest \
  -n 0 \
  --doctest-modules \
  --ignore=tests/test_nodes/test_llm/test_llm_integration.py \
  -k 'not test_dry_run_json_mode_emits_no_stderr and not test_litellm_not_imported_by_cli_main and not test_progress_streams_before_downstream_nodes_complete' \
  -q \
  --tb=short \
  --durations=30 \
  --durations-min=0.1
```

Result:

```text
5881 passed, 18 skipped, 3 deselected in 49.52s
real 51.99
```

This is important because a non-parallel run already moves from ~15s to ~52s in this environment. It still does not reach the user's `114s`, but it explains part of the delta if their command lost xdist parallelism or workers are ineffective.

### Collection only

Command:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest --collect-only -q
```

Result:

```text
5911 tests collected in 2.08s
real 3.38
```

Collection is not the main issue in the sandbox.

### New Segment 4 test slice

Command:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest \
  tests/test_cli/test_analyze_cache.py \
  tests/test_core/test_cache_analysis_analyze.py \
  tests/test_core/test_cache_analysis_cross_workflow.py \
  tests/test_core/test_cache_analysis_padding_advisor.py \
  tests/test_core/test_cache_analysis_per_id_coverage.py \
  tests/test_core/test_cache_analysis_renderers.py \
  tests/test_core/test_cache_analysis_summarize.py \
  tests/test_core/test_cache_analysis_token_estimation.py \
  tests/test_core/test_cache_analysis_warnings.py \
  tests/test_core/test_cache_serialization.py \
  tests/test_execution/test_plan_cache_nudge.py \
  tests/test_integration/test_no_cache_flag.py \
  tests/test_mcp_server/test_analyze_cache_tool.py \
  -q \
  --durations=40 \
  --durations-min=0.01
```

Result:

```text
1 failed, 183 passed in 2.02s
real 4.34
```

Failure:

```text
tests/test_cli/test_analyze_cache.py::test_analyze_cache_with_workflow_having_warnings_still_exits_zero
json.decoder.JSONDecodeError
```

Reason: LiteLLM emitted a warning before JSON output:

```text
LiteLLM: Failed to fetch remote model cost map from https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json ...
```

This is both a correctness bug for JSON-mode output and a performance clue.

### New Segment 4 targeted slice with local LiteLLM map

Command:

```bash
HOME=/private/tmp/pflow-test-home LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python -m pytest \
  tests/test_cli/test_analyze_cache.py \
  tests/test_core/test_cache_analysis_token_estimation.py \
  tests/test_mcp_server/test_analyze_cache_tool.py \
  -q \
  --durations=20 \
  --durations-min=0.01
```

Result:

```text
31 passed in 1.44s
real 2.27
```

### LiteLLM direct import/token counter timing

Command:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python - <<'PY'
import time
start=time.perf_counter()
import litellm
print('import litellm', time.perf_counter()-start)
start=time.perf_counter()
print(litellm.token_counter(model='gpt-4o', text='hello world'))
print('token_counter', time.perf_counter()-start)
PY
```

Result:

```text
LiteLLM: Failed to fetch remote model cost map ...
import litellm 0.8303670409368351
2
token_counter 0.16653337504249066
real 1.20
```

In a non-sandbox environment, if GitHub/raw DNS or HTTPS is slow but not failing immediately, this can be much worse. LiteLLM's own code shows the fetch timeout default is `5` seconds.

Relevant LiteLLM environment flag:

```bash
LITELLM_LOCAL_MODEL_COST_MAP=True
```

Found in `.venv/lib/python3.13/site-packages/litellm/litellm_core_utils/get_model_cost_map.py`.

### CLI import check

Command:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -c "import sys; from pflow.cli.main import main; print('litellm' in sys.modules); print([k for k in sys.modules if k == 'litellm' or k.startswith('litellm.')][:5])"
```

Result:

```text
False
[]
real 0.48
```

So the current CLI import path does not eagerly import LiteLLM. LiteLLM is being touched when `analyze-cache` / token estimation actually runs.

## Sandbox-Excluded Tests To Check Outside Sandbox

These are excluded by the sandbox near-full command but are included by normal `make test`:

- `tests/test_cli/test_dry_run_subprocess.py::test_dry_run_json_mode_emits_no_stderr`
- `tests/test_cli/test_lazy_imports.py::test_litellm_not_imported_by_cli_main`
- `tests/test_cli/test_progress_streaming_subprocess.py::TestRealSubprocessProgressRendering::test_progress_streams_before_downstream_nodes_complete`

Inside sandbox, they fail fast due to `uv` behavior and are not useful for timing:

- `uv run pflow` can fail to spawn `pflow`
- `uv run python -c ...` can panic with `Attempted to create a NULL object`
- streaming subprocess test returns quickly after not seeing marker

Outside sandbox, these are prime suspects because they use real subprocesses and have large timeout ceilings:

- `test_dry_run_json_mode_emits_no_stderr`: `timeout=60`
- streaming subprocess test: waits up to `10s`, plus cleanup wait up to `10s`
- all `uv run ...` subprocess tests can pay `uv` startup/resolution overhead

## Branch Commit / Size Observations

Task 159 branch added a lot of tests before Segment 4:

```text
git diff --shortstat origin/main..HEAD -- tests src pyproject.toml
50 files changed, 9016 insertions(+), 253 deletions(-)

git diff --stat origin/main..HEAD -- tests
23 files changed, 6260 insertions(+), 5 deletions(-)
```

Notable commits by test/source footprint:

```text
caff861d B1.1: 4 files, 409 insertions, 6 deletions
29134670 B1.2: 2 files, 349 insertions
84c6d7da B2.1: 2 files, 521 insertions
75398846 B2.2: 2 files, 409 insertions
7ad993ed B2.3: 2 files, 901 insertions, 1 deletion
3b64f994 B3.0: 2 files, 184 insertions
91275361 Segment 2: 16 files, 1903 insertions, 54 deletions
1be206c3 Segment 3: 22 files, 3709 insertions, 67 deletions
b6d646ee Segment 3 fixes: 7 files, 339 insertions, 133 deletions
```

Segment 4 dirty/staged work adds about another `5.4k` source+test lines, including the `~2.6k` test lines listed above.

## Strongest Current Hypotheses

### Hypothesis 1: Normal command includes `uv run` subprocess tests that sandbox excluded

Why plausible:

- User reports `make test`; `make test` does not exclude the three sandbox-problem subprocess tests.
- Several real subprocess tests run `uv run pflow` or `uv run python`.
- If `uv` is slow/resolving/rechecking environment repeatedly, a handful of tests can add large wall time.

What would confirm:

Run outside sandbox:

```bash
/usr/bin/time -p uv run python -m pytest \
  tests/test_cli/test_dry_run_subprocess.py::test_dry_run_json_mode_emits_no_stderr \
  tests/test_cli/test_lazy_imports.py::test_litellm_not_imported_by_cli_main \
  tests/test_cli/test_progress_streaming_subprocess.py::TestRealSubprocessProgressRendering::test_progress_streams_before_downstream_nodes_complete \
  -q -s --tb=short --durations=20 --durations-min=0
```

Also run with direct venv Python:

```bash
/usr/bin/time -p .venv/bin/python -m pytest \
  tests/test_cli/test_dry_run_subprocess.py::test_dry_run_json_mode_emits_no_stderr \
  tests/test_cli/test_lazy_imports.py::test_litellm_not_imported_by_cli_main \
  tests/test_cli/test_progress_streaming_subprocess.py::TestRealSubprocessProgressRendering::test_progress_streams_before_downstream_nodes_complete \
  -q -s --tb=short --durations=20 --durations-min=0
```

If these alone take tens of seconds, inspect subprocess command construction and consider using `.venv/bin/pflow` / `.venv/bin/python` fixtures instead of `uv run` where the test is not specifically about `uv`.

### Hypothesis 2: LiteLLM remote model-cost-map fetch is slow locally

Why plausible:

- Segment 4 introduced `src/pflow/core/cache_analysis/token_estimation.py`.
- It calls `litellm.token_counter()`, which imports LiteLLM.
- LiteLLM imports fetch `model_prices_and_context_window.json` from GitHub unless `LITELLM_LOCAL_MODEL_COST_MAP=True`.
- In sandbox this emitted a warning and broke JSON output in `test_analyze_cache_with_workflow_having_warnings_still_exits_zero`.
- LiteLLM default remote-fetch timeout is `5` seconds.

What would confirm:

Run outside sandbox:

```bash
/usr/bin/time -p .venv/bin/python - <<'PY'
import time
start = time.perf_counter()
import litellm
print("import litellm", time.perf_counter() - start)
start = time.perf_counter()
print(litellm.token_counter(model="gpt-4o", text="hello world"))
print("token_counter", time.perf_counter() - start)
PY
```

Then:

```bash
/usr/bin/time -p env LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python - <<'PY'
import time
start = time.perf_counter()
import litellm
print("import litellm", time.perf_counter() - start)
start = time.perf_counter()
print(litellm.token_counter(model="gpt-4o", text="hello world"))
print("token_counter", time.perf_counter() - start)
PY
```

If the env var removes many seconds, the fix should probably be in test setup and/or pflow's analyzer token-estimation wrapper, not only in developer instructions.

Candidate fixes:

- In tests, set `LITELLM_LOCAL_MODEL_COST_MAP=True` globally in `tests/conftest.py`.
- In pflow code, set local model cost map before lazy-importing LiteLLM for token counting, or avoid LiteLLM for analyzer token estimation in tests by injecting a token counter.
- Avoid letting LiteLLM warnings pollute CLI JSON output.

### Hypothesis 3: Loss of parallelism or poor worker scheduling

Why plausible:

- Sequential near-full sandbox run was `~52s`, parallel was `~14-16s`.
- User's `114s` could be a slower machine plus sequential execution, or xdist workers being blocked by a few long subprocess/network tests.

What would confirm:

Run outside sandbox:

```bash
/usr/bin/time -p uv run python -m pytest -n 4 --doctest-modules --ignore=tests/test_nodes/test_llm/test_llm_integration.py -q --durations=80 --durations-min=0.1
```

and:

```bash
/usr/bin/time -p uv run python -m pytest -n 0 --doctest-modules --ignore=tests/test_nodes/test_llm/test_llm_integration.py -q --durations=80 --durations-min=0.1
```

If `-n 4` is still about `114s`, inspect slow durations and subprocess/network tests. If only `-n 0` is about `114s`, the issue is likely parallelism not being used or not effective.

## Specific Files To Inspect Next

Primary suspects:

- `src/pflow/core/cache_analysis/token_estimation.py`
  - Lazy-imports `litellm`
  - Calls `litellm.token_counter(model=model, text=text)`
- `tests/test_core/test_cache_analysis_token_estimation.py`
  - Directly exercises estimator path
- `tests/test_cli/test_analyze_cache.py`
  - JSON-mode failure seen in sandbox from LiteLLM warning prefix
- `tests/test_mcp_server/test_analyze_cache_tool.py`
  - Calls analyzer service, may touch token estimator
- `tests/test_cli/test_dry_run_subprocess.py`
  - Uses `uv run pflow`, timeout `60`
- `tests/test_cli/test_lazy_imports.py`
  - Uses `uv run python -c`
- `tests/test_cli/test_progress_streaming_subprocess.py`
  - Many real subprocess tests; one sandbox-excluded streaming test has long waits
- `tests/conftest.py`
  - Global test setup. Consider setting `LITELLM_LOCAL_MODEL_COST_MAP=True` here if confirmed.

## Suggested Next Commands For Non-Sandbox Agent

Start with the user's exact slow command:

```bash
/usr/bin/time -p make test
```

Then run the equivalent with explicit durations:

```bash
/usr/bin/time -p uv run python -m pytest \
  -n 4 \
  --doctest-modules \
  --ignore=tests/test_nodes/test_llm/test_llm_integration.py \
  -q \
  --durations=120 \
  --durations-min=0.05
```

Check whether LiteLLM remote fetch is the multiplier:

```bash
/usr/bin/time -p env LITELLM_LOCAL_MODEL_COST_MAP=True uv run python -m pytest \
  -n 4 \
  --doctest-modules \
  --ignore=tests/test_nodes/test_llm/test_llm_integration.py \
  -q \
  --durations=120 \
  --durations-min=0.05
```

Check subprocess suspects:

```bash
/usr/bin/time -p uv run python -m pytest \
  tests/test_cli/test_dry_run_subprocess.py \
  tests/test_cli/test_lazy_imports.py \
  tests/test_cli/test_progress_streaming_subprocess.py \
  -q -s --tb=short --durations=80 --durations-min=0
```

Check new Segment 4 tests:

```bash
/usr/bin/time -p env LITELLM_LOCAL_MODEL_COST_MAP=True uv run python -m pytest \
  tests/test_cli/test_analyze_cache.py \
  tests/test_core/test_cache_analysis_analyze.py \
  tests/test_core/test_cache_analysis_cross_workflow.py \
  tests/test_core/test_cache_analysis_padding_advisor.py \
  tests/test_core/test_cache_analysis_per_id_coverage.py \
  tests/test_core/test_cache_analysis_renderers.py \
  tests/test_core/test_cache_analysis_summarize.py \
  tests/test_core/test_cache_analysis_token_estimation.py \
  tests/test_core/test_cache_analysis_warnings.py \
  tests/test_core/test_cache_serialization.py \
  tests/test_execution/test_plan_cache_nudge.py \
  tests/test_integration/test_no_cache_flag.py \
  tests/test_mcp_server/test_analyze_cache_tool.py \
  -q --durations=80 --durations-min=0.01
```

## Bottom Line

In sandbox, the current suite is not inherently `114s`; it is around the old target when run in parallel with the sandbox exclusions.

Most likely explanations for the user's non-sandbox `114s`:

1. Normal `make test` includes real `uv run` subprocess tests that sandbox excluded.
2. Segment 4 introduced LiteLLM token estimation; LiteLLM may spend up to seconds fetching its remote model cost map and can also corrupt JSON output with warnings.
3. Parallelism may not be effective in the user's run, or one worker may be blocked by subprocess/network timeout behavior.

First non-sandbox verification should compare:

- `make test`
- same command with `LITELLM_LOCAL_MODEL_COST_MAP=True`
- subprocess-test slice alone
- `-n 4` vs `-n 0`

