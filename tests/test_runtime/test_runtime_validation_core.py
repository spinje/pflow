"""Test the core RuntimeValidationNode functionality.

This module tests the RuntimeValidationNode's ability to:
- Execute workflows and detect runtime issues
- Extract templates from workflow IR
- Check if template paths exist in shared store
- Get available paths for suggestions
- Route correctly based on errors found
"""

from unittest.mock import patch

from pflow.planning.nodes import RuntimeValidationNode


class TestRuntimeValidationNode:
    """Test the RuntimeValidationNode core functionality."""

    def test_extract_templates_from_ir_finds_simple_templates(self):
        """Test that _extract_templates_from_ir() correctly finds simple template patterns."""
        node = RuntimeValidationNode()

        workflow = {
            "nodes": [
                {
                    "id": "api",
                    "type": "http",
                    "params": {
                        "url": "https://api.example.com",
                        "body": {"user": "${api_key}", "data": "${input_data}"},
                    },
                },
                {"id": "writer", "type": "write_file", "params": {"content": "Result: ${api.response}"}},
            ]
        }

        templates = node._extract_templates_from_ir(workflow)

        # Should find all three templates
        assert "${api_key}" in templates
        assert "${input_data}" in templates
        assert "${api.response}" in templates
        assert len(templates) == 3

    def test_extract_templates_finds_nested_and_array_notation(self):
        """Test that _extract_templates_from_ir() correctly finds nested paths and array notation."""
        node = RuntimeValidationNode()

        workflow = {
            "nodes": [
                {
                    "id": "processor",
                    "type": "llm",
                    "params": {
                        "prompt": "Analyze ${github.issues[0].title}",
                        "context": {"user": "${github.user.login}", "repos": "${github.repos[0].name}"},
                    },
                }
            ]
        }

        templates = node._extract_templates_from_ir(workflow)

        # Should find all nested and array templates
        assert "${github.issues[0].title}" in templates
        assert "${github.user.login}" in templates
        assert "${github.repos[0].name}" in templates
        assert len(templates) == 3

    def test_check_template_exists_validates_simple_paths(self):
        """Test that _check_template_exists() correctly validates simple template paths."""
        node = RuntimeValidationNode()

        shared = {"api": {"response": {"status": "success", "data": {"count": 5}}}}

        # Existing paths should return True
        assert node._check_template_exists("${api.response}", shared) is True
        assert node._check_template_exists("${api.response.status}", shared) is True
        assert node._check_template_exists("${api.response.data.count}", shared) is True

        # Non-existing paths should return False
        assert node._check_template_exists("${api.error}", shared) is False
        assert node._check_template_exists("${api.response.missing}", shared) is False
        assert node._check_template_exists("${other.field}", shared) is False

    def test_check_template_exists_validates_array_notation(self):
        """Test that _check_template_exists() correctly validates array notation paths."""
        node = RuntimeValidationNode()

        shared = {
            "github": {
                "issues": [
                    {"id": 1, "title": "Bug fix", "author": {"login": "alice"}},
                    {"id": 2, "title": "Feature", "author": {"login": "bob"}},
                ],
                "user": {"repos": ["repo1", "repo2", "repo3"]},
            }
        }

        # Valid array paths should return True
        assert node._check_template_exists("${github.issues[0].title}", shared) is True
        assert node._check_template_exists("${github.issues[1].author.login}", shared) is True
        assert node._check_template_exists("${github.user.repos[2]}", shared) is True

        # Invalid array indices should return False
        assert node._check_template_exists("${github.issues[5].title}", shared) is False
        assert node._check_template_exists("${github.user.repos[10]}", shared) is False

        # Accessing array notation on non-array should return False
        assert node._check_template_exists("${github.user[0]}", shared) is False

    def test_check_template_handles_workflow_inputs(self):
        """Test that _check_template_exists() assumes workflow inputs are provided."""
        node = RuntimeValidationNode()

        shared = {"api": {"response": "data"}}

        # Templates without dots are assumed to be workflow inputs (not node outputs)
        # These should always return True as we assume they're provided
        assert node._check_template_exists("${api_key}", shared) is True
        assert node._check_template_exists("${username}", shared) is True

        # Node output references (with dots) are validated
        assert node._check_template_exists("${api.response}", shared) is True
        assert node._check_template_exists("${api.missing}", shared) is False

    def test_get_available_paths_returns_dict_keys(self):
        """Test that _get_available_paths() returns correct suggestions for dict structures."""
        node = RuntimeValidationNode()

        shared = {
            "http": {
                "response": {
                    "login": "torvalds",
                    "name": "Linus Torvalds",
                    "bio": "Creator of Linux",
                    "location": "Portland, OR",
                },
                "status": 200,
            }
        }

        # Get available at response level
        available = node._get_available_paths(shared, "http", "response")
        assert set(available) == {"login", "name", "bio", "location"}

        # Get available at root level
        available = node._get_available_paths(shared, "http", "")
        assert set(available) == {"response", "status"}

        # Non-existent path returns empty
        available = node._get_available_paths(shared, "http", "response.missing.path")
        assert available == []

    def test_get_available_paths_returns_array_indices(self):
        """Test that _get_available_paths() returns array indices for list structures."""
        node = RuntimeValidationNode()

        shared = {"github": {"issues": [{"id": 1}, {"id": 2}, {"id": 3}]}}

        # Array should return indices
        available = node._get_available_paths(shared, "github", "issues")
        assert available == ["[0]", "[1]", "[2]"]

        # Empty array
        shared["github"]["prs"] = []
        available = node._get_available_paths(shared, "github", "prs")
        assert available == []

    def test_routing_with_no_errors_returns_default(self):
        """Test that RuntimeValidationNode routes to default when no issues detected."""
        node = RuntimeValidationNode()

        shared = {}
        prep_res = {"workflow_ir": {"nodes": []}, "execution_params": {}, "runtime_attempts": 0}
        exec_res = {"ok": True, "shared_after": {"api": {"response": "success"}}, "result": "completed"}

        action = node.post(shared, prep_res, exec_res)

        assert action == "default"
        assert "runtime_errors" not in shared

    def test_routing_with_fixable_errors_under_limit(self):
        """Test that RuntimeValidationNode routes to runtime_fix for fixable errors with attempts < 3."""
        node = RuntimeValidationNode()

        # Mock the error collection methods to return fixable errors
        with patch.object(node, "_collect_missing_template_errors") as mock_template_errors:
            mock_template_errors.return_value = [
                {
                    "source": "template",
                    "category": "missing_template_path",
                    "attempted": "${api.response.username}",
                    "available": ["login", "name"],
                    "message": "Template path not found",
                    "fixable": True,
                }
            ]

            shared = {}
            prep_res = {
                "workflow_ir": {"nodes": []},
                "execution_params": {},
                "runtime_attempts": 1,  # Under limit of 3
            }
            exec_res = {"ok": True, "shared_after": {}}

            with (
                patch.object(node, "_collect_execution_errors", return_value=[]),
                patch.object(node, "_collect_namespaced_errors", return_value=[]),
            ):
                action = node.post(shared, prep_res, exec_res)

            assert action == "runtime_fix"
            assert "runtime_errors" in shared
            assert len(shared["runtime_errors"]) == 1
            assert shared["runtime_attempts"] == 2

    def test_routing_at_max_attempts_returns_failed(self):
        """Test that RuntimeValidationNode routes to failed_runtime at max attempts."""
        node = RuntimeValidationNode()

        # Mock error collection to return fixable errors
        with patch.object(node, "_collect_missing_template_errors") as mock_template_errors:
            mock_template_errors.return_value = [
                {"source": "template", "category": "missing_template_path", "fixable": True}
            ]

            shared = {}
            prep_res = {
                "workflow_ir": {"nodes": []},
                "execution_params": {},
                "runtime_attempts": 3,  # At limit
            }
            exec_res = {"ok": True, "shared_after": {}}

            with (
                patch.object(node, "_collect_execution_errors", return_value=[]),
                patch.object(node, "_collect_namespaced_errors", return_value=[]),
            ):
                action = node.post(shared, prep_res, exec_res)

            assert action == "failed_runtime"
            assert "runtime_errors" in shared
