"""Tests for per-node cache opt-out in the execution engine."""

from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner


class TestPerNodeCacheOptOut:
    """Test that nodes with cache: false skip memoization."""

    def test_cache_false_node_not_memoized(self):
        """A node with cache: false should execute fresh every run."""
        ir = {
            "nodes": [
                {
                    "id": "get-branch",
                    "type": "shell",
                    "cache": False,
                    "params": {"command": "echo main"},
                    "purpose": "Simulates reading external state",
                }
            ],
        }

        runner = WorkflowRunner()

        # First run — should execute
        result1 = runner.run(ir, {}, RunnerConfig())
        assert result1.success

        # Second run — should execute again (not from cache)
        result2 = runner.run(ir, {}, RunnerConfig())
        assert result2.success

        # The node should NOT appear in cache hits
        cache_hits = result2.shared_after.get("__cache_hits__", [])
        assert "get-branch" not in cache_hits

    def test_cache_explicit_true_node_is_memoized(self):
        """A node with explicit cache: true should use memoization."""
        ir = {
            "nodes": [
                {
                    "id": "echo",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": "echo hello"},
                    "purpose": "Deterministic command, safe to cache",
                }
            ],
        }

        runner = WorkflowRunner()

        # First run
        result1 = runner.run(ir, {}, RunnerConfig())
        assert result1.success

        # Second run — should hit cache
        result2 = runner.run(ir, {}, RunnerConfig())
        assert result2.success

        cache_hits = result2.shared_after.get("__cache_hits__", [])
        assert "echo" in cache_hits

    def test_no_cache_flag_overrides_cache_true(self):
        """--no-cache should override per-node cache: true."""
        ir = {
            "nodes": [
                {
                    "id": "echo",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": "echo hello"},
                    "purpose": "Explicitly cached node",
                }
            ],
        }

        runner = WorkflowRunner()

        # First run with cache
        result1 = runner.run(ir, {}, RunnerConfig(cache_enabled=True))
        assert result1.success

        # Second run with --no-cache — should NOT hit cache
        result2 = runner.run(ir, {}, RunnerConfig(cache_enabled=False))
        assert result2.success

        cache_hits = result2.shared_after.get("__cache_hits__", [])
        assert "echo" not in cache_hits

    def test_cache_false_does_not_write_to_memo_cache(self):
        """Critical: cache:false must not write to the memo cache.

        If it did, removing cache:false later would expose stale data —
        the exact silent-correctness bug this feature prevents.

        This is testable because 'cache' is not part of the config hash:
        a node with cache:false and the same node with cache:true produce
        identical cache keys. A leaked write would be a live grenade.
        """

        # The two runs use IDENTICAL IR except the `cache` flag — which is NOT
        # part of the config hash, so both produce the same cache key. This is
        # load-bearing: if run 1 (cache:false) leaked a write, run 2 (cache:true)
        # would read that exact key and report a hit. (Differing `purpose` or
        # command would produce different keys and could never expose a leak.)
        def _ir(cache: bool) -> dict:
            return {
                "nodes": [
                    {
                        "id": "cmd",
                        "type": "shell",
                        "cache": cache,
                        "params": {"command": "echo hello"},
                        "purpose": "Probe whether a cache:false node leaks a memo write",
                    }
                ],
            }

        runner = WorkflowRunner()
        # Run 1: cache: false — must NOT write to the memo cache.
        result1 = runner.run(_ir(False), {}, RunnerConfig())
        assert result1.success

        # Run 2: identical IR but cache: true. If run 1 leaked a write under the
        # shared key, this would be a cache hit.
        result2 = runner.run(_ir(True), {}, RunnerConfig())
        assert result2.success

        # Must NOT be a cache hit — run 1 must not have written
        cache_hits = result2.shared_after.get("__cache_hits__", [])
        assert "cmd" not in cache_hits, (
            "cache:false node leaked a write to the memo cache — "
            "removing cache:false later would silently return stale data"
        )

    def test_cache_false_in_nested_workflow(self, tmp_path):
        """A child node with cache: false stays uncached through a parent workflow node."""
        from tests.shared.markdown_utils import write_workflow_file

        child_ir = {
            "nodes": [
                {
                    "id": "child-cmd",
                    "type": "shell",
                    "cache": False,
                    "params": {"command": "echo child-output"},
                    "purpose": "Child node with cache disabled across workflow boundary",
                }
            ],
        }
        child_path = tmp_path / "cache_child.pflow.md"
        write_workflow_file(child_ir, child_path)

        parent_ir = {
            "nodes": [
                {
                    "id": "run-child",
                    "type": "workflow",
                    "params": {"workflow": str(child_path)},
                    "purpose": "Runs a child workflow containing a cache:false node",
                }
            ],
        }

        runner = WorkflowRunner()

        # First run
        result1 = runner.run(parent_ir, {}, RunnerConfig())
        assert result1.success

        # Second run — child-cmd should NOT be cached
        result2 = runner.run(parent_ir, {}, RunnerConfig())
        assert result2.success

        # Check the child's shared store for cache hits.
        # WorkflowExecutor stores the child's shared store as the node output.
        child_shared = result2.shared_after.get("run-child", {})
        child_cache_hits = child_shared.get("__cache_hits__", [])
        assert "child-cmd" not in child_cache_hits

    def test_mixed_cache_settings(self):
        """Workflow with both cached and uncached nodes."""
        ir = {
            "nodes": [
                {
                    "id": "get-branch",
                    "type": "shell",
                    "cache": False,
                    "params": {"command": "echo main"},
                    "purpose": "External state reader, not cached",
                },
                {
                    "id": "process",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": "echo ${get-branch.stdout}"},
                    "purpose": "Processes branch name, normal caching",
                },
            ],
            "edges": [{"from": "get-branch", "to": "process"}],
        }

        runner = WorkflowRunner()

        # First run
        result1 = runner.run(ir, {}, RunnerConfig())
        assert result1.success

        # Second run — get-branch should NOT be cached, process SHOULD be cached
        result2 = runner.run(ir, {}, RunnerConfig())
        assert result2.success

        cache_hits = result2.shared_after.get("__cache_hits__", [])
        assert "get-branch" not in cache_hits
        # process has a template input that resolves to the same value,
        # so it should hit cache
        assert "process" in cache_hits
