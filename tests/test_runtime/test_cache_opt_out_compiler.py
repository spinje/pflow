"""Tests for cache opt-out in the compilation pipeline."""

from pflow.registry import Registry
from pflow.runtime.compilation.compiler import compile_workflow


class TestCacheOptOutCompilation:
    """Test that cache setting flows from IR to NodeConfig."""

    def test_cache_false_in_node_config(self):
        """Node with cache: false should have cache_enabled=False in NodeConfig."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "get-branch",
                    "type": "shell",
                    "cache": False,
                    "params": {"command": "git branch"},
                    "purpose": "Read current branch",
                }
            ],
            "edges": [],
        }
        compiled = compile_workflow(ir, Registry())
        config = compiled.node_configs["get-branch"]
        assert config.cache_enabled is False

    def test_cache_true_in_node_config(self):
        """Explicit cache: true should have cache_enabled=True in NodeConfig."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "analyze",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": "echo hello"},
                    "purpose": "Deterministic analysis",
                }
            ],
            "edges": [],
        }
        compiled = compile_workflow(ir, Registry())
        config = compiled.node_configs["analyze"]
        assert config.cache_enabled is True

    def test_cache_absent_defaults_per_node_type(self):
        """Cache default depends on node type. Only `llm` caches by default."""
        # Shell defaults to cache_enabled=False (side-effecting).
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "echo",
                    "type": "shell",
                    "params": {"command": "echo hello"},
                    "purpose": "Simple echo command",
                }
            ],
            "edges": [],
        }
        compiled = compile_workflow(ir, Registry())
        assert compiled.node_configs["echo"].cache_enabled is False

    def test_default_cache_for_node_type_predicate(self):
        """The predicate that gates cache defaults — only `llm` is True."""
        from pflow.runtime.compilation.compiler import _default_cache_for_node_type

        assert _default_cache_for_node_type("llm") is True
        assert _default_cache_for_node_type("shell") is False
        assert _default_cache_for_node_type("code") is False
        assert _default_cache_for_node_type("claude-code") is False
        assert _default_cache_for_node_type("http") is False
        assert _default_cache_for_node_type("read-file") is False
        assert _default_cache_for_node_type("write-file") is False
        assert _default_cache_for_node_type("copy-file") is False
        assert _default_cache_for_node_type("move-file") is False
        assert _default_cache_for_node_type("delete-file") is False
        assert _default_cache_for_node_type("mcp-foo-bar") is False
        assert _default_cache_for_node_type("workflow") is False
