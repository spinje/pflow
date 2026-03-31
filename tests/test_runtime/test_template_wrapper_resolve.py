"""Tests for resolve_templates() standalone function.

resolve_templates() resolves template params against the shared store and
returns merged params (static + resolved templates), last_resolutions for
trace capture, and template_errors for permissive mode.

Key behaviors tested:
- Returns merged params (static + resolved template params)
- resolve_templates() is a pure function (no instance state)
- last_resolutions is populated for trace capture
- Inputs-as-context: resolved 'inputs' enrich context for other params

Migrated from TemplateAwareNodeWrapper.resolve_templates() tests to use
standalone functions in pflow.runtime.engine.template_resolution.
"""

from pflow.runtime.engine.template_resolution import (
    build_type_cache,
    resolve_templates,
    split_params,
)
from pflow.runtime.engine.types import TemplateConfig


def _resolve_full(
    params: dict,
    shared: dict,
    interface_metadata: dict | None = None,
    resolution_mode: str = "strict",
    node_id: str = "test-node",
) -> tuple[dict, dict, list]:
    """Helper: split params, build config, resolve templates, return all three outputs."""
    expected_types = build_type_cache(interface_metadata)
    template_params, static_params = split_params(params, expected_types)
    config = TemplateConfig(
        template_params=template_params,
        static_params=static_params,
        expected_types=expected_types,
        resolution_mode=resolution_mode,
    )
    return resolve_templates(config, shared, node_id)


def _resolve(
    params: dict,
    shared: dict,
    interface_metadata: dict | None = None,
) -> dict:
    """Helper: resolve templates and return only merged_params."""
    merged, _resolutions, _errors = _resolve_full(params, shared, interface_metadata)
    return merged


class TestResolveTemplatesReturnValue:
    """Tests for the return value of resolve_templates()."""

    def test_resolve_templates_returns_merged_params(self) -> None:
        """Static and resolved template params are merged into one dict.

        When params contain both static values and template expressions,
        resolve_templates() should return a dict with static values preserved
        and templates resolved against the shared store.
        """
        result = _resolve(
            {"static_key": "static_value", "template_key": "${data}"},
            {"data": "resolved_value"},
        )

        assert result == {
            "static_key": "static_value",
            "template_key": "resolved_value",
        }

    def test_resolve_templates_with_no_template_params(self) -> None:
        """When no params contain templates, returns only static params.

        This is the fast path -- no resolution context is built, no template
        engine is invoked.
        """
        result = _resolve(
            {"key_a": "value_a", "key_b": 42},
            {"irrelevant": "data"},
        )

        assert result == {"key_a": "value_a", "key_b": 42}


class TestResolveConsistency:
    """Tests that multiple calls to resolve_templates() produce consistent results."""

    def test_resolve_consistency(self) -> None:
        """Multiple resolve_templates() calls with same inputs produce same outputs."""
        shared = {"name": "Alice", "count": 5}
        params = {"greeting": "Hello ${name}", "num": "${count}"}

        result_a = _resolve(dict(params), dict(shared))
        result_b = _resolve(dict(params), dict(shared))

        assert result_a == result_b

    def test_resolve_with_static_and_dynamic(self) -> None:
        """Static and dynamic params merge correctly."""
        result = _resolve(
            {"static": "unchanged", "dynamic": "${value}"},
            {"value": "resolved"},
        )

        assert result == {
            "static": "unchanged",
            "dynamic": "resolved",
        }


class TestResolveTemplatesTraceCapture:
    """Tests for last_resolutions (trace capture)."""

    def test_resolve_templates_sets_last_resolutions(self) -> None:
        """last_resolutions maps each template param to its template and resolved value.

        This is read by the engine for trace output.
        """
        _merged, last_resolutions, _errors = _resolve_full(
            {
                "static_key": "no_template",
                "url": "${endpoint}",
                "message": "Hello ${name}!",
            },
            {
                "endpoint": "https://example.com",
                "name": "World",
            },
        )

        # last_resolutions should contain ONLY template params, not static ones
        assert "static_key" not in last_resolutions
        assert "url" in last_resolutions
        assert "message" in last_resolutions

        # Each entry has template (original) and resolved (final value)
        assert last_resolutions["url"]["template"] == "${endpoint}"
        assert last_resolutions["url"]["resolved"] == "https://example.com"
        assert last_resolutions["message"]["template"] == "Hello ${name}!"
        assert last_resolutions["message"]["resolved"] == "Hello World!"

    def test_resolve_templates_last_resolutions_empty_when_no_templates(self) -> None:
        """When there are no template params, last_resolutions stays empty."""
        _merged, last_resolutions, _errors = _resolve_full(
            {"static": "value"},
            {},
        )

        # No template params means no resolutions to record
        assert last_resolutions == {}


class TestResolveTemplatesWithSharedStore:
    """Tests for shared store as the resolution context."""

    def test_resolve_templates_from_shared_store(self) -> None:
        """Templates resolve from shared store values."""
        result = _resolve(
            {"auth": "${api_key}"},
            {"api_key": "secret123"},
        )

        assert result["auth"] == "secret123"

    def test_shared_store_is_the_context(self) -> None:
        """Shared store values are used for resolution.

        initial_params override is removed. Values come from shared store only.
        """
        result = _resolve(
            {"field": "${data}"},
            {"data": "from_shared"},
        )

        assert result["field"] == "from_shared"


class TestInputsAsTemplateContext:
    """Tests for inputs-as-context: resolved inputs enrich the template context.

    When a node has an 'inputs' param, its resolved values become available
    as template variables for other params (e.g., prompt). This enables
    LLM nodes with external prompt files to use variable mappings.
    """

    def test_template_inputs_resolve_in_prompt(self) -> None:
        """Template inputs values are available for prompt resolution."""
        result = _resolve(
            {
                "inputs": {"concept_brief": "${item.concept_brief}"},
                "prompt": "Write about ${concept_brief}",
            },
            {"item": {"concept_brief": "A song about rain"}},
        )

        assert result["prompt"] == "Write about A song about rain"
        assert result["inputs"] == {"concept_brief": "A song about rain"}

    def test_static_inputs_resolve_in_prompt(self) -> None:
        """Static inputs (no templates) are also available for prompt resolution."""
        result = _resolve(
            {
                "inputs": {"language": "python", "framework": "django"},
                "prompt": "Analyze ${language} code using ${framework}",
            },
            {},
        )

        assert result["prompt"] == "Analyze python code using django"

    def test_inputs_mixed_with_shared_store(self) -> None:
        """Prompt can use both input-mapped and shared store variables."""
        result = _resolve(
            {
                "inputs": {"brief": "${item.brief}"},
                "prompt": "Model: ${model_name}. Brief: ${brief}",
            },
            {
                "item": {"brief": "song concept"},
                "model_name": "claude-sonnet",
            },
        )

        assert result["prompt"] == "Model: claude-sonnet. Brief: song concept"

    def test_inputs_override_shared_store_in_prompt(self) -> None:
        """Input mappings take priority over shared store keys for prompt resolution.

        If the same variable name exists in both inputs and shared store,
        the inputs value wins (it's added to context after shared store).
        """
        result = _resolve(
            {
                "inputs": {"data": "${item.data}"},
                "prompt": "Process: ${data}",
            },
            {
                "item": {"data": "from inputs"},
                "data": "from shared store",
            },
        )

        assert result["prompt"] == "Process: from inputs"

    def test_inputs_preserves_type_in_inputs_dict(self) -> None:
        """Resolved inputs preserve native types in the inputs dict."""
        result = _resolve(
            {
                "inputs": {"count": "${item.count}", "tags": "${item.tags}"},
                "prompt": "Count: ${count}",
            },
            {"item": {"count": 42, "tags": ["a", "b"]}},
        )

        assert result["inputs"]["count"] == 42
        assert result["inputs"]["tags"] == ["a", "b"]
        assert result["prompt"] == "Count: 42"

    def test_multiple_inputs_in_prompt(self) -> None:
        """Multiple input mappings are all available in the prompt."""
        result = _resolve(
            {
                "inputs": {
                    "concept_brief": "${item.concept_brief}",
                    "creative_direction": "${item.creative_direction}",
                    "draft_lyrics": "${item.draft_lyrics}",
                },
                "prompt": "Brief: ${concept_brief}\nDirection: ${creative_direction}\nLyrics: ${draft_lyrics}",
            },
            {
                "item": {
                    "concept_brief": "rain song",
                    "creative_direction": "melancholic",
                    "draft_lyrics": "verse one...",
                },
            },
        )

        assert result["prompt"] == "Brief: rain song\nDirection: melancholic\nLyrics: verse one..."

    def test_no_inputs_param_unchanged_behavior(self) -> None:
        """Without inputs, behavior is unchanged -- prompt resolves from shared store."""
        result = _resolve(
            {"prompt": "Hello ${name}"},
            {"name": "world"},
        )

        assert result["prompt"] == "Hello world"

    def test_inputs_trace_capture(self) -> None:
        """Both inputs and prompt appear in last_resolutions for trace."""
        _merged, last_resolutions, _errors = _resolve_full(
            {
                "inputs": {"x": "${item.x}"},
                "prompt": "Value: ${x}",
            },
            {"item": {"x": "42"}},
        )

        assert "inputs" in last_resolutions
        assert "prompt" in last_resolutions
        assert last_resolutions["prompt"]["resolved"] == "Value: 42"
