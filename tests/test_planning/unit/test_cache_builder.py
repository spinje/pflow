"""Test cache builder utilities for cross-session caching.

This test suite validates:
1. Cache block builder functions create correct structures
2. should_use_caching logic works correctly
3. Static/dynamic content extraction functions
4. Cache metrics formatting
"""

from typing import Any

import pytest

from pflow.planning.utils.cache_builder import (
    build_component_cache_blocks,
    build_discovery_cache_blocks,
    build_metadata_cache_blocks,
    build_simple_cache_blocks,
    extract_static_from_prompt,
    format_cache_metrics,
    should_use_caching,
)


class TestDiscoveryCacheBuilder:
    """Test build_discovery_cache_blocks function."""

    def test_builds_cache_block_with_valid_content(self):
        """Discovery context is wrapped in cache block with ephemeral control."""
        discovery_context = "A" * 200  # Long enough to be cached
        
        blocks = build_discovery_cache_blocks(discovery_context)
        
        assert len(blocks) == 1
        assert blocks[0]["text"] == discovery_context
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}

    def test_skips_caching_for_short_content(self):
        """Content under 100 chars is not cached (too small to be worth it)."""
        discovery_context = "Short content"
        
        blocks = build_discovery_cache_blocks(discovery_context)
        
        assert len(blocks) == 0

    def test_handles_empty_content(self):
        """Empty or None content returns empty blocks list."""
        assert build_discovery_cache_blocks("") == []
        assert build_discovery_cache_blocks(None) == []


class TestComponentCacheBuilder:
    """Test build_component_cache_blocks function."""

    def test_builds_multiple_cache_blocks(self):
        """Creates separate blocks for nodes, workflows, and prompt."""
        nodes_context = "N" * 200
        workflows_context = "W" * 200
        prompt_template = "P" * 600
        
        blocks = build_component_cache_blocks(
            nodes_context=nodes_context,
            workflows_context=workflows_context,
            prompt_template=prompt_template
        )
        
        assert len(blocks) == 3
        
        # Block 1: Nodes
        assert "## Available Nodes" in blocks[0]["text"]
        assert nodes_context in blocks[0]["text"]
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}
        
        # Block 2: Workflows
        assert "## Available Workflows" in blocks[1]["text"]
        assert workflows_context in blocks[1]["text"]
        assert blocks[1]["cache_control"] == {"type": "ephemeral"}
        
        # Block 3: Prompt
        assert blocks[2]["text"] == prompt_template
        assert blocks[2]["cache_control"] == {"type": "ephemeral"}

    def test_skips_small_content_blocks(self):
        """Only includes blocks that are substantial enough to cache."""
        nodes_context = "N" * 50  # Too short
        workflows_context = "W" * 200  # Good
        prompt_template = "P" * 300  # Too short (< 500)
        
        blocks = build_component_cache_blocks(
            nodes_context=nodes_context,
            workflows_context=workflows_context,
            prompt_template=prompt_template
        )
        
        # Only workflows should be included
        assert len(blocks) == 1
        assert "## Available Workflows" in blocks[0]["text"]

    def test_limits_to_three_blocks_maximum(self):
        """Never returns more than 3 blocks (Anthropic limit is 4)."""
        # Create 4 potential blocks (all large enough)
        nodes_context = "N" * 200
        workflows_context = "W" * 200
        prompt_template = "P" * 600
        
        blocks = build_component_cache_blocks(
            nodes_context=nodes_context,
            workflows_context=workflows_context,
            prompt_template=prompt_template
        )
        
        # Should cap at 3 blocks
        assert len(blocks) == 3

    def test_handles_missing_contexts(self):
        """Handles None or empty contexts gracefully."""
        blocks = build_component_cache_blocks(
            nodes_context=None,
            workflows_context="W" * 200,
            prompt_template=None
        )
        
        assert len(blocks) == 1
        assert "## Available Workflows" in blocks[0]["text"]


class TestSimpleCacheBuilder:
    """Test build_simple_cache_blocks function."""

    def test_builds_cache_block_from_prompt_only(self):
        """Creates cache block from static prompt alone."""
        static_prompt = "S" * 600
        
        blocks = build_simple_cache_blocks(static_prompt)
        
        assert len(blocks) == 1
        assert blocks[0]["text"] == static_prompt
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}

    def test_combines_prompt_and_context(self):
        """Combines static context and prompt when both provided."""
        static_prompt = "S" * 300
        static_context = "C" * 300
        
        blocks = build_simple_cache_blocks(static_prompt, static_context)
        
        assert len(blocks) == 1
        expected = f"{static_context}\n\n{static_prompt}"
        assert blocks[0]["text"] == expected
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}

    def test_skips_small_content(self):
        """Content under 500 chars is not cached."""
        static_prompt = "Short"
        
        blocks = build_simple_cache_blocks(static_prompt)
        
        assert len(blocks) == 0

    def test_handles_none_values(self):
        """Handles None values gracefully."""
        assert build_simple_cache_blocks(None) == []
        assert build_simple_cache_blocks("", None) == []


class TestMetadataCacheBuilder:
    """Test build_metadata_cache_blocks function."""

    def test_builds_cache_block_with_prompt_only(self):
        """Creates cache block from static prompt alone."""
        static_prompt = "M" * 600
        
        blocks = build_metadata_cache_blocks(static_prompt)
        
        assert len(blocks) == 1
        assert blocks[0]["text"] == static_prompt
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}

    def test_includes_node_descriptions(self):
        """Adds node descriptions as reference material."""
        static_prompt = "M" * 400  # Increased to ensure combined > 500
        node_descriptions = {
            "read-file": "Reads a file from disk",
            "write-file": "Writes content to a file",
        }
        
        blocks = build_metadata_cache_blocks(static_prompt, node_descriptions)
        
        assert len(blocks) == 1
        text = blocks[0]["text"]
        
        # Check structure
        assert static_prompt in text
        assert "## Node Reference" in text
        assert "**read-file**: Reads a file from disk" in text
        assert "**write-file**: Writes content to a file" in text

    def test_skips_small_content(self):
        """Content under 500 chars is not cached."""
        static_prompt = "Short"
        
        blocks = build_metadata_cache_blocks(static_prompt)
        
        assert len(blocks) == 0


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