"""End-to-end test for cache: false from markdown to execution.

Catches boolean coercion failures across the full pipeline:
markdown parsing → IR → compilation → engine memoization guard.

If any layer converts the boolean False to a truthy string "false",
the node silently gets cached — defeating the feature entirely.
"""

from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner


class TestCacheOptOutEndToEnd:
    """Full pipeline: .pflow.md with cache: false → no memoization."""

    def test_cache_false_markdown_prevents_memoization(self, tmp_path):
        """cache: false in a .pflow.md file must prevent cross-run caching."""
        workflow_file = tmp_path / "test.pflow.md"
        workflow_file.write_text(
            """\
# Cache Opt-Out Test

## Steps

### get-state

Read external state that changes between runs.

- type: shell
- cache: false

```shell command
echo current-state
```
"""
        )

        runner = WorkflowRunner()

        result1 = runner.run(str(workflow_file), {}, RunnerConfig())
        assert result1.success, f"First run failed: {result1.errors}"

        result2 = runner.run(str(workflow_file), {}, RunnerConfig())
        assert result2.success, f"Second run failed: {result2.errors}"

        cache_hits = result2.shared_after.get("__cache_hits__", [])
        assert "get-state" not in cache_hits, (
            "Node with cache: false was served from memo cache — "
            "boolean coercion likely broken in the parse→compile→engine chain"
        )
