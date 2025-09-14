"""Test cache builder utilities for cross-session caching.

This test suite validates:
1. should_use_caching logic works correctly
2. Static/dynamic content extraction functions
3. Cache metrics formatting

Note: The cache block builder functions (build_discovery_cache_blocks, etc.) 
were removed and replaced with prompt_cache_helper.py functionality.
"""

from typing import Any

import pytest

from pflow.planning.utils.cache_builder import (
    extract_static_from_prompt,
    format_cache_metrics,
    should_use_caching,
)


class TestExtractStaticFromPrompt:
    """Test extract_static_from_prompt function."""

    def test_separates_static_and_dynamic_content(self):
        """Correctly identifies and separates static from dynamic content."""
        full_prompt = """
        ## Instructions
        Here are the static instructions.
        
        These rules always apply:
        1. Rule one
        2. Rule two
        
        User Request:
        Build me a workflow
        
        Selected Components:
        - read-file
        - write-file
        """
        
        static, dynamic = extract_static_from_prompt(
            full_prompt,
            ["User Request:", "Selected Components:"]
        )
        
        # Static should have instructions
        assert "## Instructions" in static
        assert "These rules always apply:" in static
        assert "Rule one" in static
        
        # Dynamic should have user-specific content
        assert "User Request:" in dynamic
        assert "Build me a workflow" in dynamic
        assert "Selected Components:" in dynamic
        assert "read-file" in dynamic

    def test_handles_no_dynamic_markers(self):
        """When no dynamic markers found, everything is static."""
        full_prompt = "All static content here"
        
        static, dynamic = extract_static_from_prompt(
            full_prompt,
            ["User Request:", "Dynamic:"]
        )
        
        assert static == full_prompt
        assert dynamic == ""

    def test_handles_only_dynamic_content(self):
        """When prompt starts with dynamic marker, everything is dynamic."""
        full_prompt = """User Request:
        Everything here is dynamic
        Including this line"""
        
        static, dynamic = extract_static_from_prompt(
            full_prompt,
            ["User Request:"]
        )
        
        assert static == ""
        assert "User Request:" in dynamic
        assert "Everything here is dynamic" in dynamic


class TestShouldUseCaching:
    """Test should_use_caching logic."""

    def test_always_cache_nodes_override_flag(self):
        """Some nodes always cache regardless of flag."""
        # Planning and workflow-generator always cache
        assert should_use_caching(False, "planning") is True
        assert should_use_caching(False, "workflow-generator") is True
        assert should_use_caching(True, "planning") is True

    def test_other_nodes_respect_flag(self):
        """Non-special nodes respect the cache_planner flag."""
        assert should_use_caching(True, "discovery") is True
        assert should_use_caching(False, "discovery") is False
        assert should_use_caching(True, "browsing") is True
        assert should_use_caching(False, "browsing") is False

    def test_custom_always_cache_list(self):
        """Can provide custom list of always-cache nodes."""
        custom_list = ["my-special-node", "another-node"]
        
        assert should_use_caching(
            False, "my-special-node", always_cache_nodes=custom_list
        ) is True
        assert should_use_caching(
            False, "planning", always_cache_nodes=custom_list
        ) is False  # Not in custom list

    def test_handles_none_and_empty_node_names(self):
        """Handles edge cases gracefully."""
        assert should_use_caching(True, "") is True
        assert should_use_caching(False, "") is False
        assert should_use_caching(True, None) is True


class TestFormatCacheMetrics:
    """Test format_cache_metrics function."""

    def test_formats_cache_creation(self):
        """Formats cache creation metrics."""
        usage = {"cache_creation_input_tokens": 1000}
        
        result = format_cache_metrics(usage)
        
        assert result == "Cache: created 1000 tokens"

    def test_formats_cache_read(self):
        """Formats cache read metrics with savings note."""
        usage = {"cache_read_input_tokens": 5000}
        
        result = format_cache_metrics(usage)
        
        assert result == "Cache: read 5000 tokens (saved ~90% on cached content)"

    def test_formats_both_creation_and_read(self):
        """Formats both creation and read when both present."""
        usage = {
            "cache_creation_input_tokens": 1000,
            "cache_read_input_tokens": 5000
        }
        
        result = format_cache_metrics(usage)
        
        assert result == "Cache: created 1000 tokens, read 5000 tokens"

    def test_handles_no_caching(self):
        """Handles case when no caching occurred."""
        usage = {}
        
        result = format_cache_metrics(usage)
        
        assert result == "Cache: no caching occurred"

    def test_handles_zero_values(self):
        """Zero values are treated as no caching."""
        usage = {
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0
        }
        
        result = format_cache_metrics(usage)
        
        assert result == "Cache: no caching occurred"