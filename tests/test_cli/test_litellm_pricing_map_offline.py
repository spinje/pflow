"""Subprocess regression test for the LiteLLM pricing-map deterministic-offline default (GH #384).

LiteLLM loads its model pricing/context map at ``import litellm`` time via
``httpx.get(URL, timeout=5)``. Without intervention, ``pflow analyze-cache``
output drifts between runs depending on network availability and what LiteLLM
upstream has shipped since the bundled backup was cut — same workflow, same
inputs, different ``unavailable_models`` / ``unpriced_model`` classifications.

``pflow.core.litellm_runtime.configure_litellm_defaults`` sets
``LITELLM_LOCAL_MODEL_COST_MAP=True`` before LiteLLM imports so the bundled
backup is used unconditionally. This test pins that contract end-to-end by
pointing LiteLLM at a deliberately unreachable model-cost URL and asserting
``pflow analyze-cache`` neither errors nor logs LiteLLM's
``"Failed to fetch remote model cost map"`` warning.

The unreachable URL is the load-bearing detail. If a future refactor removes
``configure_litellm_defaults`` from any of the 6 production import sites,
the subprocess would attempt the bad URL, fail, log the warning, and this
test fails — exactly the regression to catch.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


# A minimal workflow with an LLM node — analyze-cache must touch
# litellm.model_cost to project its pricing. Mirrors the structure of
# .taskmaster/tasks/task_159/baseline/04-warning-catalog/20-llm.thinking-temperature-mismatch/
# but is self-contained so the test doesn't depend on the baseline fixture.
_WORKFLOW_BODY = """# Offline pricing-map regression

## Inputs

### article

Article.

- type: string
- required: true

## Steps

### deep-think

LLM node referencing a model whose pricing must come from LiteLLM.

- type: llm
- model: anthropic/claude-opus-4-7
- temperature: 1

```prompt
${article}
```

## Outputs

### result

The LLM response.

- source: ${deep-think.response}
- type: string
"""


def test_analyze_cache_does_not_attempt_remote_model_cost_map(
    tmp_path: Path,
    uv_exe: str,
    prepared_subprocess_env: dict[str, str],
) -> None:
    """``pflow analyze-cache`` must not log LiteLLM's remote-fetch warning."""
    workflow = tmp_path / "workflow.pflow.md"
    workflow.write_text(_WORKFLOW_BODY)

    env = dict(prepared_subprocess_env)
    # Point LiteLLM's model-cost URL at a guaranteed-unreachable host.
    # `.invalid` is reserved (RFC 2606) and resolves to NXDOMAIN — fast fail.
    # If pflow's offline-default is intact, this URL is never read.
    env["LITELLM_MODEL_COST_MAP_URL"] = "http://invalid-pflow-offline-regression-host.invalid/model_prices.json"
    # Don't let a developer's inherited LITELLM_LOCAL_MODEL_COST_MAP shadow
    # the default we're testing.
    env.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)

    result = subprocess.run(  # noqa: S603 — fixture-controlled args; mirrors other subprocess CLI tests
        [
            uv_exe,
            "run",
            "pflow",
            "analyze-cache",
            str(workflow),
            "--no-trace-autoload",
            "--format=json",
            "article=hello",
        ],
        env=env,
        capture_output=True,
        check=False,
        # LiteLLM's httpx.get uses a 5s timeout. 10s gives 2x headroom on slow
        # CI while surfacing regressions ~3x faster than the previous 30s.
        timeout=10,
    )

    stderr = result.stderr.decode("utf-8", errors="replace")
    assert "Failed to fetch remote model cost map" not in stderr, (
        "LiteLLM logged a remote-fetch failure — pflow's offline-default policy is "
        "not being applied at one of the litellm import sites. Route the offending "
        "import through pflow.core.litellm_runtime.import_litellm.\n\n"
        f"stderr:\n{stderr}"
    )
    # analyze-cache must succeed even with a bad URL because the fetch never fires.
    assert result.returncode == 0, (
        f"analyze-cache exited {result.returncode} with an unreachable "
        f"LITELLM_MODEL_COST_MAP_URL. The fix should make the URL irrelevant.\n"
        f"stdout: {result.stdout.decode('utf-8', errors='replace')[:500]}\n"
        f"stderr: {stderr[:500]}"
    )
