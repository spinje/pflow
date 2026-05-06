"""Cache layer independence contract: ``--no-cache`` disables ONLY the memo
layer, not LLM provider prompt caching.

Spec § "Cache Layer Independence (--no-cache scope)" mandates that a workflow
declaring ``prompt_cache: [...]`` continues to send ``cache_control`` markers
to the LLM provider even when run with ``--no-cache`` (cache_enabled=False on
RunnerConfig). The two cache layers are conceptually independent.
"""

from __future__ import annotations

from pathlib import Path

from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner
from tests.shared.llm_mock import MockLLMClient

_WORKFLOW_WITH_PROMPT_CACHE = """\
# No-cache flag test

A workflow that uses prompt_cache: AND is run under --no-cache.

## Inputs

### topic

Topic to summarize.

- type: string

## Cache

```cache
The topic of the analysis:

${topic}
```

## Steps

### review

Summarize the topic.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [topic]

```prompt
Provide a concise summary.
```
"""


def _has_cache_control(system_blocks: object) -> bool:
    """Return True iff ``system`` is a list of blocks with at least one
    carrying a ``cache_control`` marker."""
    if not isinstance(system_blocks, list):
        return False
    return any(isinstance(block, dict) and "cache_control" in block for block in system_blocks)


def test_prompt_cache_fires_under_no_cache_flag(tmp_path: Path, mock_llm_client: MockLLMClient) -> None:
    """``--no-cache`` (cache_enabled=False) MUST NOT disable LLM provider
    prompt caching. The system message still carries cache_control markers."""
    mock_llm_client.set_response("*", None, "ok", cache_creation_input_tokens=1024)
    workflow_path = tmp_path / "wf.pflow.md"
    workflow_path.write_text(_WORKFLOW_WITH_PROMPT_CACHE, encoding="utf-8")

    runner = WorkflowRunner()
    result = runner.run(
        str(workflow_path),
        {"topic": "climate"},
        config=RunnerConfig(cache_enabled=False),
    )
    assert result.status.value in {"completed", "success"}, result.status

    # Assert the LLM mock was called with system blocks carrying a
    # ``cache_control`` marker — proving that prompt caching fires regardless
    # of the memo layer being disabled.
    full_history = mock_llm_client.call_history_full
    assert full_history, "MockLLMClient was never called"
    last_call = full_history[-1]
    system_arg = last_call.get("system")
    assert _has_cache_control(system_arg), f"Expected system blocks with cache_control marker, got: {system_arg!r}"
