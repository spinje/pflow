"""Tests for prompt loader validation functionality.

This test file verifies the critical bidirectional validation behavior
of the prompt loader:
- Variables provided by code must exist in template
- Variables in template must be provided by code
"""

import pytest

from src.pflow.planning.prompts.loader import extract_variables, format_prompt


class TestPromptValidation:
    """Test the bidirectional validation of prompt variables."""

    def test_normal_operation_variables_match(self):
        """Test normal case where template and code variables match perfectly."""
        # Simple test template with two variables
        template = "Hello {{name}}, your score is {{score}}."
        variables = {"name": "Alice", "score": 100}

        # Should format without errors
        result = format_prompt(template, variables)
        assert result == "Hello Alice, your score is 100."

    def test_missing_variable_in_template(self):
        """Test when code provides a variable that doesn't exist in template.

        This catches when someone forgets to add {{variable}} to the .md file.
        """
        # Template missing {{score}} placeholder
        template = "Hello {{name}}!"
        variables = {"name": "Alice", "score": 100}  # Code provides 'score'

        # Should raise ValueError about unused variable
        with pytest.raises(ValueError) as exc_info:
            format_prompt(template, variables)

        error_msg = str(exc_info.value)
        assert "Variables provided but not in template" in error_msg
        assert "score" in error_msg

    def test_missing_variable_in_code(self):
        """Test when template needs a variable that code doesn't provide.

        This catches when code forgets to provide a required variable.
        """
        # Template expects both variables
        template = "Hello {{name}}, your score is {{score}}."
        variables = {"name": "Alice"}  # Code missing 'score'

        # Should raise KeyError about missing variable
        with pytest.raises(KeyError) as exc_info:
            format_prompt(template, variables)

        error_msg = str(exc_info.value)
        assert "Missing required variables" in error_msg
        assert "score" in error_msg

    def test_typo_in_variable_name(self):
        """Test when there's a typo in variable name (template vs code mismatch).

        This is a common error - variable names don't match exactly.
        """
        # Template has typo: usr_input instead of user_input
        template = "Processing {{usr_input}} for {{context}}."
        variables = {"user_input": "test", "context": "validation"}

        # Should raise ValueError because 'user_input' not in template
        # AND KeyError because 'usr_input' not provided
        with pytest.raises(ValueError) as exc_info:
            format_prompt(template, variables)

        error_msg = str(exc_info.value)
        assert "Variables provided but not in template" in error_msg
        assert "user_input" in error_msg


class TestVariableExtraction:
    """Test the variable extraction helper function."""

    def test_extract_variables_simple(self):
        """Test extracting variables from a simple template."""
        template = "Hello {{name}}, welcome to {{place}}!"
        variables = extract_variables(template)
        assert variables == {"name", "place"}

    def test_extract_variables_none(self):
        """Test extracting from template with no variables."""
        template = "Hello world!"
        variables = extract_variables(template)
        assert variables == set()

    def test_extract_variables_duplicates(self):
        """Test that duplicate variables are only returned once."""
        template = "{{name}} is {{name}} and lives in {{city}}"
        variables = extract_variables(template)
        assert variables == {"name", "city"}
