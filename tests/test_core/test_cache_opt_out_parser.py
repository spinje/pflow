"""Tests for per-node cache opt-out parsing."""

from pflow.core.markdown_parser import parse_markdown


class TestCacheOptOutParsing:
    """Test that - cache: false is extracted to top-level node dict."""

    def test_cache_false_extracted_to_top_level(self):
        """cache: false should be at node top level, not in params."""
        md = """# Test

## Steps

### get-branch

Get current branch.

- type: shell
- cache: false
- command: git branch --show-current
"""
        result = parse_markdown(md)
        node = result.ir["nodes"][0]
        assert node["cache"] is False
        assert "cache" not in node.get("params", {})

    def test_cache_true_extracted_to_top_level(self):
        """Explicit cache: true should also work."""
        md = """# Test

## Steps

### analyze

Analyze data.

- type: llm
- cache: true
- prompt: Analyze this
"""
        result = parse_markdown(md)
        node = result.ir["nodes"][0]
        assert node["cache"] is True
        assert "cache" not in node.get("params", {})

    def test_no_cache_param_means_absent(self):
        """When cache is not specified, it should not be in the node dict."""
        md = """# Test

## Steps

### echo

Say hello.

- type: shell
- command: echo hello
"""
        result = parse_markdown(md)
        node = result.ir["nodes"][0]
        assert "cache" not in node
