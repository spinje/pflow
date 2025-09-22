"""Tests for template resolver array index support."""

from pflow.runtime.template_resolver import TemplateResolver


class TestArrayIndexSupport:
    """Test array index notation in template variables."""

    def test_resolves_simple_array_access(self):
        """Test resolution of simple array index access."""
        context = {"items": ["first", "second", "third"]}

        assert TemplateResolver.resolve_value("items[0]", context) == "first"
        assert TemplateResolver.resolve_value("items[1]", context) == "second"
        assert TemplateResolver.resolve_value("items[2]", context) == "third"

    def test_resolves_nested_array_access(self):
        """Test resolution of nested array with object properties."""
        context = {"data": {"users": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]}}

        assert TemplateResolver.resolve_value("data.users[0].name", context) == "Alice"
        assert TemplateResolver.resolve_value("data.users[1].name", context) == "Bob"
        assert TemplateResolver.resolve_value("data.users[0].age", context) == 30

    def test_resolves_multi_dimensional_arrays(self):
        """Test resolution of multi-dimensional arrays."""
        context = {"matrix": [[1, 2, 3], [4, 5, 6], [7, 8, 9]]}

        assert TemplateResolver.resolve_value("matrix[0][0]", context) == 1
        assert TemplateResolver.resolve_value("matrix[1][1]", context) == 5
        assert TemplateResolver.resolve_value("matrix[2][2]", context) == 9

    def test_handles_out_of_bounds_index(self):
        """Test that out of bounds array index returns None."""
        context = {"items": ["a", "b", "c"]}

        assert TemplateResolver.resolve_value("items[10]", context) is None
        assert TemplateResolver.resolve_value("items[-1]", context) is None

    def test_handles_non_list_array_access(self):
        """Test that array access on non-list returns None."""
        context = {"not_array": "string value", "dict_value": {"key": "value"}}

        assert TemplateResolver.resolve_value("not_array[0]", context) is None
        assert TemplateResolver.resolve_value("dict_value[0]", context) is None

    def test_template_string_resolution_with_arrays(self):
        """Test full template string resolution with array indices."""
        context = {"qa_pairs": [{"question": "What?", "answer": "That."}, {"question": "Why?", "answer": "Because."}]}

        template = "Q: ${qa_pairs[0].question} A: ${qa_pairs[0].answer}"
        result = TemplateResolver.resolve_string(template, context)
        assert result == "Q: What? A: That."

        template = "Second: ${qa_pairs[1].question} - ${qa_pairs[1].answer}"
        result = TemplateResolver.resolve_string(template, context)
        assert result == "Second: Why? - Because."

    def test_real_world_slack_qa_workflow(self):
        """Test the exact scenario from the Slack Q&A workflow."""
        context = {
            "analyze_questions": {
                "response": {
                    "qa_pairs": [
                        {"question": "How many letters in 'cat'?", "answer": "There are 3 letters in the word 'cat'."},
                        {
                            "question": "What is the meaning of 'chairs'?",
                            "answer": "A 'chair' is a piece of furniture.",
                        },
                    ]
                }
            }
        }

        # Test exact templates that were failing
        q1 = TemplateResolver.resolve_string("${analyze_questions.response.qa_pairs[0].question}", context)
        assert q1 == "How many letters in 'cat'?"

        a1 = TemplateResolver.resolve_string("${analyze_questions.response.qa_pairs[0].answer}", context)
        assert a1 == "There are 3 letters in the word 'cat'."

        q2 = TemplateResolver.resolve_string("${analyze_questions.response.qa_pairs[1].question}", context)
        assert q2 == "What is the meaning of 'chairs'?"

    def test_variable_exists_with_arrays(self):
        """Test that variable_exists works with array indices."""
        context = {"list": [1, 2, 3], "nested": {"items": [{"id": 1}, {"id": 2}]}}

        assert TemplateResolver.variable_exists("list[0]", context) is True
        assert TemplateResolver.variable_exists("list[2]", context) is True
        assert TemplateResolver.variable_exists("list[3]", context) is False
        assert TemplateResolver.variable_exists("nested.items[0].id", context) is True
        assert TemplateResolver.variable_exists("nested.items[10]", context) is False

    def test_complex_mixed_notation(self):
        """Test complex paths mixing dots and array indices."""
        context = {
            "api": {
                "responses": [
                    {
                        "data": {
                            "items": [
                                {"name": "item1", "values": [10, 20, 30]},
                                {"name": "item2", "values": [40, 50, 60]},
                            ]
                        }
                    }
                ]
            }
        }

        # Deep nested access with multiple array indices
        result = TemplateResolver.resolve_value("api.responses[0].data.items[1].values[2]", context)
        assert result == 60

        # Template string with complex path
        template = "Value: ${api.responses[0].data.items[0].values[0]}"
        assert TemplateResolver.resolve_string(template, context) == "Value: 10"
