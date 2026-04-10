"""Essential tests for output template validation.

These tests catch REAL bugs in template validation:
1. Template validation reverted to skipping → typos pass, fail at runtime
2. Workflow inputs broken → can't use ${api_key} in outputs
3. Plain references broken → node.key format not validated
4. Multiple errors not collected → only first error shows
5. False positives → valid templates rejected
"""

from pflow.registry import Registry
from tests.shared.diagnostic_helpers import split_validator_diagnostics


class TestOutputTemplateValidation:
    """Test template reference validation catches semantic errors."""

    def test_typo_shows_fuzzy_match(self):
        """CRITICAL: Typo in node name gets fuzzy-matched suggestion.

        Bug prevented:
        1. Template validation reverted to skipping (line 237)
        2. Fuzzy matching removed (method="fuzzy" deleted)

        Without this test: Typos like generate-story pass validation but fail
        at runtime with cryptic errors.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "generate_story", "type": "llm", "params": {}}],
            "outputs": {"result": {"source": "${generate-story.response}"}},  # Hyphen!
        }

        registry = Registry()
        errors, _ = split_validator_diagnostics(workflow, {}, registry, skip_node_types=True)

        assert len(errors) > 0
        typo_error = next(d for d in errors if "generate-story" in d.message)
        assert typo_error.context is not None
        assert typo_error.context.get("similar_names")
        assert any("generate_story" in name for name in typo_error.context["similar_names"])

    def test_valid_template_passes(self):
        """SANITY: Valid template passes without errors.

        Bug prevented: False positives in template validation.
        Without this test: Valid workflows get rejected.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "generate_story", "type": "llm", "params": {}}],
            "outputs": {"result": {"source": "${generate_story.response}"}},
        }

        registry = Registry()
        errors, _ = split_validator_diagnostics(workflow, {}, registry, skip_node_types=True)

        assert len(errors) == 0

    def test_malformed_template_caught(self):
        """CRITICAL: Malformed template syntax detected.

        Bug prevented: Regex validation broken.
        Without this test: Malformed templates like "${incomplete" pass validation
        and cause runtime errors.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "llm", "params": {}}],
            "outputs": {"result": {"source": "${incomplete"}},  # Missing }
        }

        registry = Registry()
        errors, _ = split_validator_diagnostics(workflow, {}, registry, skip_node_types=True)

        assert len(errors) > 0
        assert "malformed" in "\n".join(d.message for d in errors).lower()

    def test_template_workflow_input_passes(self):
        """CRITICAL: Template referencing declared workflow input passes.

        Bug prevented: Validator rejects valid input references in outputs.
        Without this test: Can't use ${api_key}, ${user_name} in outputs.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "llm", "params": {}}],
            "inputs": {"user_input": {"type": "string", "description": "User input"}},
            "outputs": {"result": {"source": "${user_input}"}},
        }

        registry = Registry()
        errors, _ = split_validator_diagnostics(workflow, None, registry, skip_node_types=True)

        assert len(errors) == 0

    def test_plain_reference_validation(self):
        """CRITICAL: Plain references (no ${}) validated.

        Bug prevented: Plain reference code path (line 244-257) broken.
        Without this test: "node.key" format not validated (different from "${node.key}").

        This is a DIFFERENT CODE BRANCH than templates.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "llm", "params": {}}],
            "outputs": {"result": {"source": "missing.output"}},  # No ${}, still invalid
        }

        registry = Registry()
        errors, _ = split_validator_diagnostics(workflow, {}, registry, skip_node_types=True)

        assert len(errors) > 0
        assert "non-existent source 'missing'" in "\n".join(d.message for d in errors)

    def test_multiple_errors_reported(self):
        """CRITICAL: All errors collected, not just first one.

        Bug prevented: Early return added to validation loop.
        Without this test: Agent fixes first error, still gets validation error,
        doesn't know what else to fix.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "llm", "params": {}}],
            "outputs": {
                "out1": {"source": "${missing1.data}"},
                "out2": {"source": "${missing2.data}"},
                "out3": {"source": "${node1.data}"},  # Valid
            },
        }

        registry = Registry()
        errors, _ = split_validator_diagnostics(workflow, {}, registry, skip_node_types=True)

        # Should have 2 errors (missing1 and missing2)
        assert len(errors) == 2

        error_msg = "\n".join(d.message for d in errors)
        assert "missing1" in error_msg
        assert "missing2" in error_msg

    def test_template_input_field_access_passes(self):
        """CRITICAL: Template with dot-access on declared input passes.

        Bug prevented: GH #247 — ${input.field} rejected as non-existent node.
        Without this test: Can't use ${data.field} in output sources when
        data is a declared workflow input.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "echo_it", "type": "shell", "params": {}}],
            "inputs": {"data": {"type": "dict", "description": "A dict with a field"}},
            "outputs": {"x": {"source": "${data.field}"}},
        }

        registry = Registry()
        errors, _ = split_validator_diagnostics(workflow, None, registry, skip_node_types=True)

        assert len(errors) == 0

    def test_template_input_bracket_access_passes(self):
        """CRITICAL: Template with bracket-access on declared input passes.

        Bug prevented: Same root cause as GH #247 for bracket syntax.
        Without this test: Can't use ${items[0]} in output sources.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "shell", "params": {}}],
            "inputs": {"items": {"type": "list", "description": "A list"}},
            "outputs": {"first": {"source": "${items[0]}"}},
        }

        registry = Registry()
        errors, _ = split_validator_diagnostics(workflow, None, registry, skip_node_types=True)

        assert len(errors) == 0

    def test_template_nonexistent_shows_inputs_in_available(self):
        """CRITICAL: Error for missing source includes both nodes and inputs.

        Bug prevented: Available list only shows nodes, hiding valid inputs.
        Without this test: Users with a typo don't see declared inputs as
        alternatives in the fuzzy suggestions.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "fetch", "type": "shell", "params": {}}],
            "inputs": {"api_key": {"type": "string", "description": "API key"}},
            "outputs": {"result": {"source": "${typo.field}"}},
        }

        registry = Registry()
        errors, _ = split_validator_diagnostics(workflow, None, registry, skip_node_types=True)

        assert len(errors) == 1
        available = errors[0].context.get("available_fields", [])
        assert "fetch" in available
        assert "api_key" in available

    def test_bare_template_nonexistent_caught(self):
        """CRITICAL: Bare template referencing undeclared name is caught.

        Bug prevented: ${typo} (no dot) silently passes validation.
        Without this test: Typos in bare output source templates only
        fail at runtime with a cryptic error.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "shell", "params": {}}],
            "outputs": {"result": {"source": "${typo}"}},
        }

        registry = Registry()
        errors, _ = split_validator_diagnostics(workflow, {}, registry, skip_node_types=True)

        assert len(errors) == 1
        assert "typo" in errors[0].message

    def test_bracket_typo_suggestion_format(self):
        """CRITICAL: Bracket-access typo suggestion doesn't insert spurious dot.

        Bug prevented: ${itmes[0]} suggests ${items.[0]} instead of ${items[0]}.
        Without this test: Bracket-access suggestions have malformed syntax.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "items", "type": "shell", "params": {}}],
            "outputs": {"first": {"source": "${itmes[0]}"}},
        }

        registry = Registry()
        errors, _ = split_validator_diagnostics(workflow, {}, registry, skip_node_types=True)

        assert len(errors) == 1
        assert errors[0].suggestions
        assert "${items[0]}" in errors[0].suggestions[0]
        assert ".[0]" not in errors[0].suggestions[0]
