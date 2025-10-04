"""Test RequirementsAnalysisNode catches vague input and routes correctly.

WHEN TO RUN:
- Always (part of standard test suite)
- After modifying RequirementsAnalysisNode
- After changing requirements_analysis.md prompt structure

WHAT IT VALIDATES:
- Vague input detection triggers clarification_needed route
- Clear input allows continuation with empty string
- Error is embedded in _error field for ResultPreparationNode
- Templatized input is preferred over raw input
- exec_fallback handles LLM failures gracefully

CRITICAL: This prevents wasted LLM calls and user frustration.
"""

from unittest.mock import Mock, patch

import pytest

from pflow.planning.nodes import RequirementsAnalysisNode


class TestRequirementsAnalysisNode:
    """Test RequirementsAnalysisNode critical behavior."""

    def test_vague_input_triggers_clarification_needed(self):
        """Vague input MUST trigger clarification_needed route.

        This is THE most critical test - it prevents the entire pipeline
        from failing mysteriously when users provide unclear requests.
        """
        import json

        node = RequirementsAnalysisNode()

        # Mock LLM to return "not clear"
        with patch("llm.get_model") as mock_llm:
            mock_model = Mock()
            # Create the response data structure
            response_data = {
                "is_clear": False,
                "clarification_needed": "Please specify what to process and how",
                "steps": [],
                "estimated_nodes": 0,
                "required_capabilities": [],
                "complexity_indicators": {},
            }
            # Mock text() to return JSON string
            mock_model.prompt.return_value = Mock(text=lambda: json.dumps(response_data))
            mock_llm.return_value = mock_model

            shared = {"templatized_input": "process the data"}

            # Execute full lifecycle
            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            # CRITICAL ASSERTIONS
            assert action == "clarification_needed", "Vague input must route to clarification"
            assert "_error" in exec_res, "Error must be embedded for ResultPreparationNode"
            assert exec_res["_error"]["category"] == "invalid_input", "Must be invalid_input category"
            assert "Please specify" in exec_res["_error"]["user_action"], "User must see clarification message"

            # Verify requirements_result has embedded error too
            assert shared["requirements_result"] == exec_res
            assert "_error" in shared["requirements_result"]

    def test_clear_input_allows_continuation(self):
        """Clear input MUST allow pipeline to continue.

        This ensures we don't accidentally block valid requests.
        """
        import json

        node = RequirementsAnalysisNode()

        # Mock LLM to return clear requirements
        with patch("llm.get_model") as mock_llm:
            mock_model = Mock()
            # Create the response data structure
            response_data = {
                "is_clear": True,
                "clarification_needed": None,
                "steps": ["Fetch issues from GitHub", "Generate changelog", "Write to file"],
                "estimated_nodes": 3,
                "required_capabilities": ["github_api", "text_generation", "file_io"],
                "complexity_indicators": {"has_external_services": True},
            }
            # Mock text() to return JSON string
            mock_model.prompt.return_value = Mock(text=lambda: json.dumps(response_data))
            mock_llm.return_value = mock_model

            shared = {"templatized_input": "fetch ${issue_count} issues and create changelog"}

            # Execute full lifecycle
            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            # CRITICAL ASSERTIONS
            assert action == "", "Clear input must return empty string for default routing"
            assert "_error" not in exec_res, "No error should be embedded for clear input"
            assert shared["requirements_result"] == exec_res
            assert exec_res["is_clear"] is True
            assert len(exec_res["steps"]) == 3
            assert "github_api" in exec_res["required_capabilities"]

    def test_uses_templatized_input_over_raw(self):
        """Node MUST prefer templatized_input over user_input.

        This ensures we work with abstracted parameters, not raw values.
        """
        node = RequirementsAnalysisNode()

        # Both inputs provided - should use templatized
        shared = {
            "templatized_input": "fetch ${count} issues from ${repo}",
            "user_input": "fetch 20 issues from octocat/hello-world",
        }

        prep_res = node.prep(shared)

        # CRITICAL ASSERTION
        assert prep_res["input_text"] == "fetch ${count} issues from ${repo}"
        assert prep_res["is_templatized"] is True

    def test_falls_back_to_user_input_when_no_templatized(self):
        """Node MUST fall back to user_input if templatized not available.

        This ensures backward compatibility.
        """
        node = RequirementsAnalysisNode()

        # Only raw input provided
        shared = {"user_input": "fetch 20 issues from octocat/hello-world"}

        prep_res = node.prep(shared)

        # Should fall back to user_input
        assert prep_res["input_text"] == "fetch 20 issues from octocat/hello-world"
        assert prep_res["is_templatized"] is False

    def test_error_embedded_for_result_preparation(self):
        """Error MUST be embedded in _error field for ResultPreparationNode.

        This ensures users see helpful messages instead of generic failures.
        """
        import json

        node = RequirementsAnalysisNode()

        with patch("llm.get_model") as mock_llm:
            mock_model = Mock()
            # Create the response data structure
            response_data = {
                "is_clear": False,
                "clarification_needed": "Please provide more details about what data to process",
                "steps": [],
                "estimated_nodes": 0,
                "required_capabilities": [],
                "complexity_indicators": {},
            }
            # Mock text() to return JSON string
            mock_model.prompt.return_value = Mock(text=lambda: json.dumps(response_data))
            mock_llm.return_value = mock_model

            shared = {"templatized_input": "do the thing"}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            _ = node.post(shared, prep_res, exec_res)  # Action not needed for this test

            # Verify error structure for ResultPreparationNode
            assert "_error" in exec_res
            error_dict = exec_res["_error"]

            # Must have all required fields for display
            assert "category" in error_dict
            assert "message" in error_dict
            assert "user_action" in error_dict
            assert "technical_details" in error_dict
            assert "retry_suggestion" in error_dict

            # User action should contain the clarification message
            assert "Please provide more details" in error_dict["user_action"]

    def test_exec_fallback_embeds_error_on_llm_failure(self):
        """exec_fallback MUST embed error correctly on LLM failure.

        This ensures graceful degradation when LLM is unavailable.
        """
        node = RequirementsAnalysisNode()

        prep_res = {"input_text": "test input", "is_templatized": False, "model_name": "test-model", "temperature": 0.0}

        # Simulate LLM failure
        exception = Exception("LLM API timeout")

        result = node.exec_fallback(prep_res, exception)

        # CRITICAL ASSERTIONS
        assert result is not None
        assert "_error" in result, "Error must be embedded even in fallback"

        # Check if it's the specific fallback structure (from exec_fallback default)
        # or the generic structure (from create_fallback_response)
        if "is_clear" in result:
            # Got the specific fallback
            assert result["is_clear"] is False, "Fallback must default to unclear"
            assert "Failed to analyze requirements" in result.get("clarification_needed", "")
            assert result["steps"] == []
        else:
            # Got the generic fallback - should still have error embedded
            assert "error" in result, "Generic fallback has error field"

        # Error should be properly structured regardless
        error_dict = result["_error"]
        # Error category could be network, llm_error, or other based on classify_error logic
        assert error_dict["category"] in ["llm_error", "network", "unknown"], (
            f"Unexpected category: {error_dict['category']}"
        )
        # The message should be present
        assert "message" in error_dict
        assert error_dict["message"]  # Should have some message

    def test_missing_input_raises_valueerror(self):
        """Missing input MUST raise ValueError in prep.

        This prevents silent failures with empty input.
        """
        node = RequirementsAnalysisNode()

        # No input provided
        shared = {}

        with pytest.raises(ValueError, match="Missing required input"):
            node.prep(shared)

    def test_abstracts_values_keeps_services(self):
        """Requirements MUST abstract values but keep services explicit.

        This is a key Task 52 requirement - "20 GitHub issues" -> "GitHub issues"
        """
        import json

        node = RequirementsAnalysisNode()

        with patch("llm.get_model") as mock_llm:
            mock_model = Mock()
            # Create the response data structure
            response_data = {
                "is_clear": True,
                "clarification_needed": None,
                "steps": [
                    "Fetch filtered issues from GitHub repository",  # Service explicit, value abstracted
                    "Analyze issue labels and priorities",
                    "Generate formatted changelog",
                    "Write changelog to file",
                ],
                "estimated_nodes": 4,
                "required_capabilities": [
                    "github_api",
                    "text_processing",
                    "file_io",
                ],  # Services explicit
                "complexity_indicators": {
                    "has_external_services": True,
                    "external_services": ["github"],
                },
            }
            # Mock text() to return JSON string
            mock_model.prompt.return_value = Mock(text=lambda: json.dumps(response_data))
            mock_llm.return_value = mock_model

            # Input has templatized values
            shared = {"templatized_input": "fetch last ${issue_limit} ${issue_state} issues from GitHub"}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)

            # Verify abstraction worked correctly
            steps = exec_res["steps"]

            # Should NOT contain template variables
            for step in steps:
                assert "${" not in step, f"Step should not contain template variables: {step}"

            # Should keep GitHub service explicit
            assert any("GitHub" in step for step in steps), "GitHub service should remain explicit"

            # Capabilities should be specific services, not generic
            assert "github_api" in exec_res["required_capabilities"]
            assert "generic_api" not in exec_res["required_capabilities"]
