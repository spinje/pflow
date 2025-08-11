"""Tests for direct execution helper functions in CLI."""

from pflow.cli.main import infer_type, is_likely_workflow_name, parse_workflow_params


class TestInferType:
    """Test type inference from string values."""

    def test_boolean_true(self):
        """Test that 'true' variants are converted to boolean True."""
        assert infer_type("true") is True
        assert infer_type("True") is True
        assert infer_type("TRUE") is True

    def test_boolean_false(self):
        """Test that 'false' variants are converted to boolean False."""
        assert infer_type("false") is False
        assert infer_type("False") is False
        assert infer_type("FALSE") is False

    def test_integer(self):
        """Test integer detection."""
        assert infer_type("42") == 42
        assert infer_type("0") == 0
        assert infer_type("-10") == -10
        assert isinstance(infer_type("42"), int)

    def test_float(self):
        """Test float detection."""
        assert infer_type("3.14") == 3.14
        assert infer_type("-2.5") == -2.5
        assert infer_type("1e5") == 100000.0
        assert isinstance(infer_type("3.14"), float)

    def test_json_array(self):
        """Test JSON array parsing."""
        assert infer_type('["a", "b", "c"]') == ["a", "b", "c"]
        assert infer_type("[1, 2, 3]") == [1, 2, 3]
        assert infer_type("[]") == []

    def test_json_object(self):
        """Test JSON object parsing."""
        assert infer_type('{"key": "value"}') == {"key": "value"}
        assert infer_type('{"num": 42}') == {"num": 42}
        assert infer_type("{}") == {}

    def test_string_default(self):
        """Test that non-special strings remain strings."""
        assert infer_type("hello") == "hello"
        assert infer_type("data.csv") == "data.csv"
        assert infer_type("/path/to/file") == "/path/to/file"
        assert infer_type("true-but-not-boolean") == "true-but-not-boolean"

    def test_invalid_json_stays_string(self):
        """Test that invalid JSON stays as string."""
        assert infer_type("[invalid") == "[invalid"
        assert infer_type("{bad json}") == "{bad json}"


class TestParseWorkflowParams:
    """Test parameter parsing from command arguments."""

    def test_single_param(self):
        """Test parsing a single parameter."""
        result = parse_workflow_params(("input_file=data.csv",))
        assert result == {"input_file": "data.csv"}

    def test_multiple_params(self):
        """Test parsing multiple parameters."""
        args = ("input_file=data.csv", "output_dir=results/", "limit=100")
        result = parse_workflow_params(args)
        assert result == {
            "input_file": "data.csv",
            "output_dir": "results/",
            "limit": 100,  # Note: inferred as int
        }

    def test_no_params(self):
        """Test with no parameters."""
        assert parse_workflow_params(()) == {}
        assert parse_workflow_params(("no-equals-sign",)) == {}

    def test_type_inference_in_params(self):
        """Test that type inference works in parameter parsing."""
        args = ("verbose=true", "count=42", "ratio=3.14", "items=[1,2,3]", 'config={"key":"value"}')
        result = parse_workflow_params(args)
        assert result["verbose"] is True
        assert result["count"] == 42
        assert result["ratio"] == 3.14
        assert result["items"] == [1, 2, 3]
        assert result["config"] == {"key": "value"}

    def test_empty_value(self):
        """Test parameter with empty value."""
        result = parse_workflow_params(("key=",))
        assert result == {"key": ""}

    def test_multiple_equals_signs(self):
        """Test parameter value containing equals sign."""
        result = parse_workflow_params(("expression=a=b+c",))
        assert result == {"expression": "a=b+c"}


class TestIsLikelyWorkflowName:
    """Test workflow name detection heuristics."""

    def test_with_parameters(self):
        """Test that args with parameters are detected as workflow names."""
        assert is_likely_workflow_name("my-workflow", ("input=data.csv", "output=result"))
        assert is_likely_workflow_name("analyzer", ("file=test.txt",))
        # But not if it's CLI syntax with =>
        assert not is_likely_workflow_name("node1", ("=>", "node2"))
        assert not is_likely_workflow_name("read-file", ("--path=data.txt", "=>", "process"))

    def test_kebab_case(self):
        """Test that kebab-case names are detected."""
        assert is_likely_workflow_name("my-analyzer", ())
        assert is_likely_workflow_name("generate-report", ())
        assert is_likely_workflow_name("test-workflow-name", ())
        # But not if followed by CLI syntax
        assert not is_likely_workflow_name("read-file", ("=>", "process"))

    def test_natural_language(self):
        """Test that natural language is not detected as workflow name."""
        assert not is_likely_workflow_name("analyze the data", ())
        assert not is_likely_workflow_name("create a report from csv", ())
        assert not is_likely_workflow_name("process this file", ())

    def test_excluded_starters(self):
        """Test that common command starters are excluded."""
        # Single words without params are not treated as workflow names anymore
        assert not is_likely_workflow_name("analyze", ())
        assert not is_likely_workflow_name("create", ())
        assert not is_likely_workflow_name("generate", ())
        assert not is_likely_workflow_name("process", ())

    def test_single_word_workflow(self):
        """Test single word that could be workflow name."""
        # Single words without kebab-case or params are NOT workflow names
        assert not is_likely_workflow_name("myworkflow", ())
        assert not is_likely_workflow_name("reporter", ())
        assert not is_likely_workflow_name("analyze", ())
        # But they are if they have params
        assert is_likely_workflow_name("myworkflow", ("input=data.csv",))
        assert is_likely_workflow_name("reporter", ("format=pdf",))

    def test_edge_cases(self):
        """Test edge cases."""
        # Empty string
        assert not is_likely_workflow_name("", ())
        # Very long string without spaces (unlikely workflow name)
        long_name = "a" * 60
        assert not is_likely_workflow_name(long_name, ())
        # With spaces never a workflow name
        assert not is_likely_workflow_name("has spaces", ("param=value",))
