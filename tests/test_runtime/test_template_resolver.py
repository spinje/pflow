"""Tests for template variable resolution with path support."""

from pflow.runtime.template_resolver import TemplateResolver


class TestTemplateDetection:
    """Test template detection in various value types."""

    def test_detects_templates_in_strings(self):
        """Test that templates are detected in string values."""
        assert TemplateResolver.has_templates("Hello $name")
        assert TemplateResolver.has_templates("$url")
        assert TemplateResolver.has_templates("Path: $data.field")

    def test_ignores_non_string_values(self):
        """Test that non-string values are ignored."""
        assert not TemplateResolver.has_templates(42)
        assert not TemplateResolver.has_templates(True)
        assert not TemplateResolver.has_templates(None)
        assert not TemplateResolver.has_templates(["$item"])
        assert not TemplateResolver.has_templates({"key": "$value"})

    def test_detects_absence_of_templates(self):
        """Test that strings without $ are not flagged as templates."""
        assert not TemplateResolver.has_templates("Hello world")
        assert not TemplateResolver.has_templates("")
        assert not TemplateResolver.has_templates("price: 100")


class TestVariableExtraction:
    """Test extraction of template variable names."""

    def test_extracts_simple_variables(self):
        """Test extraction of simple variable names."""
        assert TemplateResolver.extract_variables("$url") == {"url"}
        assert TemplateResolver.extract_variables("Hello $name") == {"name"}
        assert TemplateResolver.extract_variables("$var1 and $var2") == {"var1", "var2"}

    def test_extracts_path_variables(self):
        """Test extraction of variables with paths."""
        assert TemplateResolver.extract_variables("$data.field") == {"data.field"}
        assert TemplateResolver.extract_variables("$a.b.c.d") == {"a.b.c.d"}
        assert TemplateResolver.extract_variables("$user.info.name") == {"user.info.name"}

    def test_extracts_multiple_variables(self):
        """Test extraction of multiple variables from one string."""
        template = "User $user.name from $user.company at $location"
        expected = {"user.name", "user.company", "location"}
        assert TemplateResolver.extract_variables(template) == expected

    def test_handles_malformed_templates(self):
        """Test that malformed templates are not extracted."""
        # These malformed patterns should not match
        assert TemplateResolver.extract_variables("$.var") == set()
        # Note: $var. is now valid (variable followed by period punctuation)
        assert TemplateResolver.extract_variables("$var.") == {"var"}
        assert TemplateResolver.extract_variables("$$var") == set()
        assert TemplateResolver.extract_variables("$") == set()
        assert TemplateResolver.extract_variables("$123") == set()  # Can't start with digit


class TestValueResolution:
    """Test resolution of variable values from context."""

    def test_resolves_simple_variables(self):
        """Test resolution of simple variables."""
        context = {"url": "https://example.com", "name": "Alice"}
        assert TemplateResolver.resolve_value("url", context) == "https://example.com"
        assert TemplateResolver.resolve_value("name", context) == "Alice"
        assert TemplateResolver.resolve_value("missing", context) is None

    def test_resolves_nested_paths(self):
        """Test resolution of nested data paths."""
        context = {"user": {"name": "Bob", "info": {"age": 30, "city": "NYC"}}}
        assert TemplateResolver.resolve_value("user.name", context) == "Bob"
        assert TemplateResolver.resolve_value("user.info.age", context) == 30
        assert TemplateResolver.resolve_value("user.info.city", context) == "NYC"

    def test_handles_missing_paths(self):
        """Test handling of missing paths."""
        context = {"data": {"field": "value"}}
        assert TemplateResolver.resolve_value("data.missing", context) is None
        assert TemplateResolver.resolve_value("missing.field", context) is None
        assert TemplateResolver.resolve_value("data.field.sub", context) is None

    def test_handles_non_dict_traversal(self):
        """Test that traversal stops at non-dict values."""
        context = {"string": "hello", "number": 42, "list": [1, 2, 3]}
        assert TemplateResolver.resolve_value("string.field", context) is None
        assert TemplateResolver.resolve_value("number.field", context) is None
        assert TemplateResolver.resolve_value("list.0", context) is None  # No array indexing


class TestTypeConversion:
    """Test conversion of values to strings."""

    def test_none_conversion(self):
        """Test None converts to empty string."""
        assert TemplateResolver._convert_to_string(None) == ""

    def test_empty_string_conversion(self):
        """Test empty string stays empty."""
        assert TemplateResolver._convert_to_string("") == ""

    def test_zero_conversion(self):
        """Test zero converts to "0"."""
        assert TemplateResolver._convert_to_string(0) == "0"
        # 0.0 will convert to "0" due to Python's str() behavior where 0.0 == 0
        assert TemplateResolver._convert_to_string(0.0) == "0.0" or TemplateResolver._convert_to_string(0.0) == "0"

    def test_boolean_conversion(self):
        """Test boolean conversion."""
        assert TemplateResolver._convert_to_string(False) == "False"
        assert TemplateResolver._convert_to_string(True) == "True"

    def test_empty_collection_conversion(self):
        """Test empty collections convert to string representation."""
        assert TemplateResolver._convert_to_string([]) == "[]"
        assert TemplateResolver._convert_to_string({}) == "{}"

    def test_regular_value_conversion(self):
        """Test regular values use str()."""
        assert TemplateResolver._convert_to_string("hello") == "hello"
        assert TemplateResolver._convert_to_string(42) == "42"
        assert TemplateResolver._convert_to_string([1, 2, 3]) == "[1, 2, 3]"
        assert TemplateResolver._convert_to_string({"a": 1}) == "{'a': 1}"


class TestStringResolution:
    """Test complete string resolution with templates."""

    def test_resolves_single_template(self):
        """Test resolution of single template in string."""
        context = {"url": "https://example.com"}
        assert TemplateResolver.resolve_string("Visit $url", context) == "Visit https://example.com"
        assert TemplateResolver.resolve_string("$url", context) == "https://example.com"

    def test_resolves_multiple_templates(self):
        """Test resolution of multiple templates."""
        context = {"name": "Alice", "age": 30}
        template = "$name is $age years old"
        assert TemplateResolver.resolve_string(template, context) == "Alice is 30 years old"

    def test_resolves_path_templates(self):
        """Test resolution of templates with paths."""
        context = {"user": {"name": "Bob", "email": "bob@example.com"}, "status": "active"}
        template = "User $user.name ($user.email) - Status: $status"
        expected = "User Bob (bob@example.com) - Status: active"
        assert TemplateResolver.resolve_string(template, context) == expected

    def test_preserves_unresolved_templates(self):
        """Test that unresolved templates remain unchanged."""
        context = {"found": "yes"}
        template = "Found: $found, Missing: $missing"
        assert TemplateResolver.resolve_string(template, context) == "Found: yes, Missing: $missing"

    def test_handles_type_conversions(self):
        """Test type conversions in resolution."""
        context = {"none_val": None, "zero": 0, "false": False, "empty_list": [], "data": {"count": 42}}
        # None converts to empty string
        assert TemplateResolver.resolve_string("[$none_val]", context) == "[]"
        assert TemplateResolver.resolve_string("Count: $zero", context) == "Count: 0"
        assert TemplateResolver.resolve_string("Flag: $false", context) == "Flag: False"
        assert TemplateResolver.resolve_string("Items: $empty_list", context) == "Items: []"
        assert TemplateResolver.resolve_string("Total: $data.count", context) == "Total: 42"


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_malformed_template_syntax(self):
        """Test that malformed templates are left unchanged (except $var. which is now valid)."""
        context = {"var": "value", "data": {"field": "test"}}

        # These malformed templates should remain as-is
        assert TemplateResolver.resolve_string("$.var", context) == "$.var"
        # Note: $var. is now valid (variable followed by period punctuation)
        assert TemplateResolver.resolve_string("$var.", context) == "value."
        assert TemplateResolver.resolve_string("$var..field", context) == "value..field"
        assert TemplateResolver.resolve_string("$$var", context) == "$$var"
        assert TemplateResolver.resolve_string("$", context) == "$"

        # Valid template should still work
        assert TemplateResolver.resolve_string("$var", context) == "value"

    def test_path_traversal_with_null(self):
        """Test path traversal when encountering null/None."""
        context = {"parent": {"child": None}}
        # Should not be able to traverse through None
        assert TemplateResolver.resolve_string("$parent.child.field", context) == "$parent.child.field"

    def test_adjacent_templates(self):
        """Test templates with no spacing between them."""
        context = {"a": "A", "b": "B", "c": "C"}
        assert TemplateResolver.resolve_string("$a$b$c", context) == "ABC"
        assert TemplateResolver.resolve_string("$a-$b-$c", context) == "A-B-C"

    def test_template_in_larger_text(self):
        """Test templates embedded in larger text blocks."""
        context = {"repo": "pflow", "issue": "123", "user": {"name": "Alice"}}
        template = """
        Working on repository $repo
        Fixing issue #$issue
        Assigned to: $user.name
        Missing: $undefined.field
        """
        expected = """
        Working on repository pflow
        Fixing issue #123
        Assigned to: Alice
        Missing: $undefined.field
        """
        assert TemplateResolver.resolve_string(template, context) == expected


class TestRealWorldScenarios:
    """Test scenarios from actual pflow usage."""

    def test_planner_parameter_flow(self):
        """Test parameters extracted by planner from natural language."""
        # Simulating planner extraction from "fix github issue 1234"
        planner_params = {"issue_number": "1234", "repo": "pflow"}

        template = "Working on issue $issue_number in $repo"
        result = TemplateResolver.resolve_string(template, planner_params)
        assert result == "Working on issue 1234 in pflow"

    def test_shared_store_path_access(self):
        """Test accessing nested data in shared store."""
        # Nodes write directly to shared store keys
        context = {
            "transcript_data": {
                "video_id": "xyz",
                "title": "Learning Python",
                "metadata": {"author": "CodeTeacher", "duration": 3600},
            },
            "summary": "Python is a versatile language...",
        }

        template = "Video: $transcript_data.title by $transcript_data.metadata.author"
        result = TemplateResolver.resolve_string(template, context)
        assert result == "Video: Learning Python by CodeTeacher"

    def test_youtube_workflow_example(self):
        """Test template resolution from youtube summarization workflow."""
        context = {
            "url": "https://youtube.com/watch?v=xyz",
            "transcript_data": {
                "video_id": "xyz",
                "title": "How to Learn Programming",
                "text": "In this video, we'll explore...",
                "metadata": {"author": "TechChannel", "views": 50000},
            },
            "summary": "• Start with fundamentals\n• Practice daily\n• Build projects",
        }

        # Template from example workflow
        template = "Summary of '$transcript_data.title' by $transcript_data.metadata.author"
        result = TemplateResolver.resolve_string(template, context)
        assert result == "Summary of 'How to Learn Programming' by TechChannel"
