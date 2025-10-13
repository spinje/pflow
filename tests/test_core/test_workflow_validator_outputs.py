"""Essential tests for output template validation.

These tests catch REAL bugs in template validation:
1. Template validation reverted to skipping → typos pass, fail at runtime
2. Workflow inputs broken → can't use ${api_key} in outputs
3. Plain references broken → node.key format not validated
4. Multiple errors not collected → only first error shows
5. False positives → valid templates rejected
"""

from pflow.core.workflow_validator import WorkflowValidator
from pflow.registry import Registry


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
        errors, _ = WorkflowValidator.validate(workflow, {}, registry, skip_node_types=True)

        assert len(errors) > 0
        error_msg = "\n".join(errors)

        # Should suggest correct name
        assert "generate_story" in error_msg
        assert "Did you mean" in error_msg
        assert "${generate_story.response}" in error_msg

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
        errors, _ = WorkflowValidator.validate(workflow, {}, registry, skip_node_types=True)

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
        errors, _ = WorkflowValidator.validate(workflow, {}, registry, skip_node_types=True)

        assert len(errors) > 0
        assert "malformed" in "\n".join(errors).lower()

    def test_template_workflow_input_passes(self):
        """CRITICAL: Template without dot (workflow input variable) passes.

        Bug prevented: Line 300-302 check removed (if "." not in template_var).
        Without this test: Can't use ${api_key}, ${user_name} in outputs.

        This is a DIFFERENT CODE PATH than node references.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "llm", "params": {}}],
            "outputs": {"result": {"source": "${user_input}"}},  # No dot - workflow input
        }

        registry = Registry()
        errors, _ = WorkflowValidator.validate(workflow, {}, registry, skip_node_types=True)

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
        errors, _ = WorkflowValidator.validate(workflow, {}, registry, skip_node_types=True)

        assert len(errors) > 0
        assert "non-existent node 'missing'" in "\n".join(errors)

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
        errors, _ = WorkflowValidator.validate(workflow, {}, registry, skip_node_types=True)

        # Should have 2 errors (missing1 and missing2)
        assert len(errors) == 2

        error_msg = "\n".join(errors)
        assert "missing1" in error_msg
        assert "missing2" in error_msg
