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

    def test_cache_absent_defaults_to_true(self):
        """Node without cache setting should default to cache_enabled=True."""
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
        config = compiled.node_configs["echo"]
        assert config.cache_enabled is True
