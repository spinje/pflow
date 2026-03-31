"""Regression test: shared store is the single source of runtime data.

Task 135 eliminated the initial_params override in template resolution.
Previously, _build_resolution_context() merged initial_params over shared store,
meaning CLI-provided values always won over upstream node outputs.

Now, all values flow through the shared store. User-provided params are seeded
into shared store before execution. Upstream node outputs can overwrite them
(this is the correct behavior — node outputs should take precedence over
initial defaults for same-named keys).
"""

from pflow.runtime import compile_workflow
from pflow.runtime.engine import WorkflowEngine


class TestSharedStoreIsOnlyDataSource:
    """Verify that template resolution reads only from shared store."""

    def test_upstream_node_output_available_for_downstream(self):
        """Upstream node output is available for downstream template resolution
        through the shared store — no initial_params needed."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "producer",
                    "type": "shell",
                    "params": {"command": "echo upstream-value"},
                },
                {
                    "id": "consumer",
                    "type": "shell",
                    "params": {"command": "echo got:${producer.stdout}"},
                },
            ],
            "edges": [{"source": "producer", "target": "consumer"}],
        }

        from pflow.registry import Registry

        workflow = compile_workflow(ir, registry=Registry())
        shared: dict = {}
        shared.update(workflow.resolved_defaults)

        engine = WorkflowEngine()
        engine.run(workflow, shared)

        # Consumer should see upstream value via shared store
        assert "upstream-value" in shared["consumer"]["stdout"]

    def test_defaults_seeded_into_shared_store(self):
        """Declared input defaults end up in resolved_defaults, seeded into shared store."""
        ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "greeting": {"type": "str", "default": "hello", "required": False, "description": "A greeting"},
            },
            "nodes": [
                {
                    "id": "greet",
                    "type": "shell",
                    "params": {"command": "echo ${greeting}"},
                },
            ],
            "edges": [],
        }

        from pflow.registry import Registry

        # Don't provide greeting — let the default kick in
        workflow = compile_workflow(ir, registry=Registry())

        # Verify default appears in resolved_defaults
        assert "greeting" in workflow.resolved_defaults
        assert workflow.resolved_defaults["greeting"] == "hello"

        shared: dict = {}
        shared.update(workflow.resolved_defaults)

        engine = WorkflowEngine()
        engine.run(workflow, shared)

        # Default value should be resolved from shared store
        assert "hello" in shared["greet"]["stdout"]

    def test_user_param_available_via_shared_store(self):
        """User-provided params (seeded into shared store) are available for resolution."""
        ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "name": {"type": "str", "required": True},
            },
            "nodes": [
                {
                    "id": "greet",
                    "type": "shell",
                    "params": {"command": "echo Hello ${name}"},
                },
            ],
            "edges": [],
        }

        from pflow.registry import Registry

        workflow = compile_workflow(ir, registry=Registry(), initial_params={"name": "World"})
        shared: dict = {}
        shared.update(workflow.resolved_defaults)
        shared["name"] = "World"  # Seed user param (what Runner does)

        engine = WorkflowEngine()
        engine.run(workflow, shared)

        assert "Hello World" in shared["greet"]["stdout"]

    def test_template_resolution_uses_only_shared_store(self):
        """Template resolution context is built from shared store only.

        This is the core behavioral change: the old _build_resolution_context
        did context.update(self.initial_params). The new resolve_templates
        does context = dict(shared) — no override.
        """
        from pflow.runtime.engine.template_resolution import (
            build_type_cache,
            resolve_templates,
            split_params,
        )
        from pflow.runtime.engine.types import TemplateConfig

        params = {"message": "Hello ${name}"}
        expected_types = build_type_cache(None)
        template_params, static_params = split_params(params, expected_types)

        config = TemplateConfig(
            template_params=template_params,
            static_params=static_params,
            expected_types=expected_types,
            resolution_mode="strict",
        )

        # Value in shared store should be used
        shared = {"name": "from-shared-store"}
        merged, _, _ = resolve_templates(config, shared, "test-node")
        assert merged["message"] == "Hello from-shared-store"
