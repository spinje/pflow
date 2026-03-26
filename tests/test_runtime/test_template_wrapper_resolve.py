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


class TestInputsAsTemplateContext:
    """Tests for inputs-as-context: resolved inputs enrich the template context.

    When a node has an 'inputs' param, its resolved values become available
    as template variables for other params (e.g., prompt). This enables
    LLM nodes with external prompt files to use variable mappings — the same
    pattern code nodes use, but for template resolution instead of namespace
    injection.
    """

    def test_template_inputs_resolve_in_prompt(self) -> None:
        """Template inputs values are available for prompt resolution.

        This is the core use case: an LLM node maps batch item fields to
        the variable names an external prompt expects.
        """
        _node, wrapper = _make_wrapper()
        wrapper.set_params({
            "inputs": {"concept_brief": "${item.concept_brief}"},
            "prompt": "Write about ${concept_brief}",
        })

        result = wrapper.resolve_templates({
            "item": {"concept_brief": "A song about rain"},
        })

        assert result["prompt"] == "Write about A song about rain"
        assert result["inputs"] == {"concept_brief": "A song about rain"}

    def test_static_inputs_resolve_in_prompt(self) -> None:
        """Static inputs (no templates) are also available for prompt resolution.

        When inputs have literal values, they should still enrich the context.
        """
        _node, wrapper = _make_wrapper()
        wrapper.set_params({
            "inputs": {"language": "python", "framework": "django"},
            "prompt": "Analyze ${language} code using ${framework}",
        })

        result = wrapper.resolve_templates({})

        assert result["prompt"] == "Analyze python code using django"

    def test_inputs_mixed_with_shared_store(self) -> None:
        """Prompt can use both input-mapped and shared store variables.

        Variables not in inputs fall back to normal shared store resolution.
        """
        _node, wrapper = _make_wrapper()
        wrapper.set_params({
            "inputs": {"brief": "${item.brief}"},
            "prompt": "Model: ${model_name}. Brief: ${brief}",
        })

        result = wrapper.resolve_templates({
            "item": {"brief": "song concept"},
            "model_name": "claude-sonnet",
        })

        assert result["prompt"] == "Model: claude-sonnet. Brief: song concept"

    def test_inputs_override_shared_store_in_prompt(self) -> None:
        """Input mappings take priority over shared store keys for prompt resolution.

        If the same variable name exists in both inputs and shared store,
        the inputs value wins (it's added to context after shared store).
        """
        _node, wrapper = _make_wrapper()
        wrapper.set_params({
            "inputs": {"data": "${item.data}"},
            "prompt": "Process: ${data}",
        })

        result = wrapper.resolve_templates({
            "item": {"data": "from inputs"},
            "data": "from shared store",
        })

        assert result["prompt"] == "Process: from inputs"

    def test_inputs_preserves_type_in_inputs_dict(self) -> None:
        """Resolved inputs preserve native types in the inputs dict.

        While prompt interpolation stringifies values, the inputs dict
        itself should keep native types (for code nodes that also use inputs).
        """
        _node, wrapper = _make_wrapper()
        wrapper.set_params({
            "inputs": {"count": "${item.count}", "tags": "${item.tags}"},
            "prompt": "Count: ${count}",
        })

        result = wrapper.resolve_templates({
            "item": {"count": 42, "tags": ["a", "b"]},
        })

        assert result["inputs"]["count"] == 42
        assert result["inputs"]["tags"] == ["a", "b"]
        assert result["prompt"] == "Count: 42"

    def test_multiple_inputs_in_prompt(self) -> None:
        """Multiple input mappings are all available in the prompt."""
        _node, wrapper = _make_wrapper()
        wrapper.set_params({
            "inputs": {
                "concept_brief": "${item.concept_brief}",
                "creative_direction": "${item.creative_direction}",
                "draft_lyrics": "${item.draft_lyrics}",
            },
            "prompt": "Brief: ${concept_brief}\nDirection: ${creative_direction}\nLyrics: ${draft_lyrics}",
        })

        result = wrapper.resolve_templates({
            "item": {
                "concept_brief": "rain song",
                "creative_direction": "melancholic",
                "draft_lyrics": "verse one...",
            },
        })

        assert result["prompt"] == "Brief: rain song\nDirection: melancholic\nLyrics: verse one..."

    def test_no_inputs_param_unchanged_behavior(self) -> None:
        """Without inputs, behavior is unchanged — prompt resolves from shared store.

        This confirms the feature is purely additive.
        """
        _node, wrapper = _make_wrapper()
        wrapper.set_params({
            "prompt": "Hello ${name}",
        })

        result = wrapper.resolve_templates({"name": "world"})

        assert result["prompt"] == "Hello world"

    def test_inputs_run_integration(self) -> None:
        """Inputs-as-context works through the full _run() path."""
        node, wrapper = _make_wrapper()
        wrapper.set_params({
            "inputs": {"topic": "${item.topic}"},
            "prompt": "Write about ${topic}",
        })

        wrapper._run({"item": {"topic": "the ocean"}})

        assert node.params_at_execution["prompt"] == "Write about the ocean"

    def test_inputs_trace_capture(self) -> None:
        """Both inputs and prompt appear in last_resolutions for trace."""
        _node, wrapper = _make_wrapper()
        wrapper.set_params({
            "inputs": {"x": "${item.x}"},
            "prompt": "Value: ${x}",
        })

        wrapper.resolve_templates({"item": {"x": "42"}})

        assert "inputs" in wrapper.last_resolutions
        assert "prompt" in wrapper.last_resolutions
        assert wrapper.last_resolutions["prompt"]["resolved"] == "Value: 42"
