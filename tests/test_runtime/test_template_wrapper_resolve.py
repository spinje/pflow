"""Tests for TemplateAwareNodeWrapper.resolve_templates() method.

resolve_templates() was extracted from _run() to allow external callers
(e.g., memoization/cache logic) to resolve template params against the
shared store and inspect the result before deciding whether to run the node.

Key behaviors tested:
- Returns merged params (static + resolved template params)
- resolve_templates() is a pure query (no instance state mutation beyond last_resolutions)
- _run() calls resolve_templates() internally on every execution
- last_resolutions is populated for trace capture
- initial_params override shared store values in the resolution context
"""

from pflow.runtime.wrappers.template_wrapper import TemplateAwareNodeWrapper


class DummyNode:
    """Minimal node for testing template resolution.

    Captures params at execution time so tests can verify what the wrapper
    passed through.
    """

    def __init__(self) -> None:
        self.params: dict = {}
        self.params_at_execution: dict = {}

    def set_params(self, params: dict) -> None:
        self.params = params

    def _run(self, shared: dict) -> str:
        self.params_at_execution = dict(self.params)
        return "default"


def _make_wrapper(
    initial_params: dict | None = None,
    interface_metadata: dict | None = None,
) -> tuple[DummyNode, TemplateAwareNodeWrapper]:
    """Create a DummyNode + TemplateAwareNodeWrapper pair."""
    node = DummyNode()
    wrapper = TemplateAwareNodeWrapper(
        node,
        "test-node",
        initial_params=initial_params or {},
        interface_metadata=interface_metadata,
    )
    return node, wrapper


class TestResolveTemplatesReturnValue:
    """Tests for the return value of resolve_templates()."""

    def test_resolve_templates_returns_merged_params(self) -> None:
        """Static and resolved template params are merged into one dict.

        When params contain both static values and template expressions,
        resolve_templates() should return a dict with static values preserved
        and templates resolved against the shared store.
        """
        _node, wrapper = _make_wrapper()
        wrapper.set_params({
            "static_key": "static_value",
            "template_key": "${data}",
        })

        result = wrapper.resolve_templates({"data": "resolved_value"})

        assert result == {
            "static_key": "static_value",
            "template_key": "resolved_value",
        }

    def test_resolve_templates_with_no_template_params(self) -> None:
        """When no params contain templates, returns only static params.

        This is the fast path -- no resolution context is built, no template
        engine is invoked.
        """
        _node, wrapper = _make_wrapper()
        wrapper.set_params({
            "key_a": "value_a",
            "key_b": 42,
        })

        result = wrapper.resolve_templates({"irrelevant": "data"})

        assert result == {"key_a": "value_a", "key_b": 42}


class TestRunWithResolveTemplates:
    """Tests that _run() and resolve_templates() produce consistent results."""

    def test_resolve_then_run_matches_run_alone(self) -> None:
        """Calling resolve_templates() then _run() produces the same node params
        as calling _run() alone — resolve_templates() is a pure query.
        """
        shared = {"name": "Alice", "count": 5}
        params = {"greeting": "Hello ${name}", "num": "${count}"}

        # Path A: resolve_templates() then _run()
        node_a, wrapper_a = _make_wrapper()
        wrapper_a.set_params(dict(params))
        wrapper_a.resolve_templates(dict(shared))
        wrapper_a._run(dict(shared))
        params_a = node_a.params_at_execution

        # Path B: _run() alone (no prior resolve_templates)
        node_b, wrapper_b = _make_wrapper()
        wrapper_b.set_params(dict(params))
        wrapper_b._run(dict(shared))
        params_b = node_b.params_at_execution

        assert params_a == params_b

    def test_run_without_prior_resolve(self) -> None:
        """_run() works standalone by calling resolve_templates() internally.

        This is the normal execution path -- no external caller pre-resolves.
        """
        node, wrapper = _make_wrapper()
        wrapper.set_params({
            "static": "unchanged",
            "dynamic": "${value}",
        })

        result = wrapper._run({"value": "resolved"})

        assert result == "default"
        assert node.params_at_execution == {
            "static": "unchanged",
            "dynamic": "resolved",
        }


class TestResolveTemplatesTraceCapture:
    """Tests for last_resolutions side effect (trace capture)."""

    def test_resolve_templates_sets_last_resolutions(self) -> None:
        """last_resolutions maps each template param to its template and resolved value.

        This is read by InstrumentedNodeWrapper for trace output.
        """
        _node, wrapper = _make_wrapper()
        wrapper.set_params({
            "static_key": "no_template",
            "url": "${endpoint}",
            "message": "Hello ${name}!",
        })

        wrapper.resolve_templates({
            "endpoint": "https://example.com",
            "name": "World",
        })

        # last_resolutions should contain ONLY template params, not static ones
        assert "static_key" not in wrapper.last_resolutions
        assert "url" in wrapper.last_resolutions
        assert "message" in wrapper.last_resolutions

        # Each entry has template (original) and resolved (final value)
        assert wrapper.last_resolutions["url"]["template"] == "${endpoint}"
        assert wrapper.last_resolutions["url"]["resolved"] == "https://example.com"
        assert wrapper.last_resolutions["message"]["template"] == "Hello ${name}!"
        assert wrapper.last_resolutions["message"]["resolved"] == "Hello World!"

    def test_resolve_templates_last_resolutions_empty_when_no_templates(self) -> None:
        """When there are no template params, last_resolutions stays empty."""
        _node, wrapper = _make_wrapper()
        wrapper.set_params({"static": "value"})

        wrapper.resolve_templates({})

        # No template params means no resolutions to record
        assert wrapper.last_resolutions == {}


class TestResolveTemplatesWithInitialParams:
    """Tests for initial_params in the resolution context."""

    def test_resolve_templates_with_initial_params(self) -> None:
        """initial_params are available in the resolution context.

        When a template references a variable that exists in initial_params
        but not in the shared store, it should still resolve.
        """
        _node, wrapper = _make_wrapper(initial_params={"api_key": "secret123"})
        wrapper.set_params({"auth": "${api_key}"})

        result = wrapper.resolve_templates({})  # empty shared store

        assert result["auth"] == "secret123"

    def test_initial_params_override_shared_store(self) -> None:
        """initial_params take priority over shared store values.

        This ensures CLI-provided parameters win over runtime data, which is
        the documented resolution priority.
        """
        _node, wrapper = _make_wrapper(initial_params={"data": "from_initial"})
        wrapper.set_params({"field": "${data}"})

        result = wrapper.resolve_templates({"data": "from_shared"})

        assert result["field"] == "from_initial"
