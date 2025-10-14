"""Tests for instruction resources exposed via MCP."""

from unittest.mock import patch

import pytest

from pflow.mcp_server.resources.instruction_resources import (
    MCP_AGENT_INSTRUCTIONS_PATH,
    SANDBOX_AGENT_INSTRUCTIONS_PATH,
    _regular_fallback_message,
    _sandbox_fallback_message,
    get_instructions,
    get_sandbox_instructions,
)


class TestRegularInstructionResource:
    """Test the pflow://instructions resource (regular agents with full access)."""

    def test_resource_returns_content_when_file_exists(self):
        """Verify resource returns file content when available."""
        if MCP_AGENT_INSTRUCTIONS_PATH.exists():
            content = get_instructions()

            # Basic content checks
            assert len(content) > 1000, "Instructions should be substantial"
            assert "pflow" in content.lower(), "Should mention pflow"
            assert "workflow" in content.lower(), "Should mention workflows"
        else:
            pytest.skip(f"Instructions file not found at {MCP_AGENT_INSTRUCTIONS_PATH}")

    def test_resource_contains_key_sections(self):
        """Verify resource contains expected instructional content."""
        if not MCP_AGENT_INSTRUCTIONS_PATH.exists():
            pytest.skip(f"Instructions file not found at {MCP_AGENT_INSTRUCTIONS_PATH}")

        content = get_instructions()

        # Check for key sections
        expected_sections = [
            "discover",  # Discovery workflow
            "shell",  # Shell/jq patterns
            "template",  # Template syntax
            "workflow",  # Workflow building
            "node",  # Node information
        ]

        for section in expected_sections:
            assert section.lower() in content.lower(), f"Should contain {section} section"

    def test_resource_has_reasonable_size(self):
        """Verify resource size is within expected range."""
        if not MCP_AGENT_INSTRUCTIONS_PATH.exists():
            pytest.skip(f"Instructions file not found at {MCP_AGENT_INSTRUCTIONS_PATH}")

        content = get_instructions()

        # Instructions should be between 10KB and 500KB
        size = len(content.encode("utf-8"))
        assert 10_000 < size < 500_000, f"Size {size} bytes outside expected range"

    @patch("pflow.mcp_server.resources.instruction_resources.MCP_AGENT_INSTRUCTIONS_PATH")
    def test_resource_returns_fallback_when_file_missing(self, mock_path):
        """Verify graceful fallback when instructions file missing."""
        mock_path.exists.return_value = False

        content = get_instructions()

        # Should return fallback message
        assert "Not Available" in content
        assert "Alternative Resources" in content
        assert "pflow workflow discover" in content
        assert "pflow settings set-env" in content  # Regular agents have settings

    def test_regular_fallback_message_structure(self):
        """Verify regular fallback message provides helpful guidance."""
        fallback = _regular_fallback_message()

        # Check for helpful sections
        assert "Alternative Resources" in fallback
        assert "Discovery Commands" in fallback
        assert "Settings & Configuration" in fallback  # Regular agents have this
        assert "Manual Setup" in fallback
        assert "Troubleshooting" in fallback

    def test_regular_fallback_includes_settings_commands(self):
        """Verify regular fallback includes settings commands."""
        fallback = _regular_fallback_message()

        # Regular agents should have settings commands
        assert "pflow settings set-env" in fallback
        assert "pflow --trace" in fallback
        assert "Store credentials" in fallback.lower() or "settings" in fallback.lower()

    @patch("pflow.mcp_server.resources.instruction_resources.MCP_AGENT_INSTRUCTIONS_PATH")
    def test_resource_handles_read_error_gracefully(self, mock_path):
        """Verify graceful handling of file read errors."""
        mock_path.exists.return_value = True
        mock_path.read_text.side_effect = OSError("Permission denied")

        content = get_instructions()

        # Should return fallback message instead of crashing
        assert "Not Available" in content
        assert len(content) > 100


class TestSandboxInstructionResource:
    """Test the pflow://instructions/sandbox resource (sandboxed agents with restricted access)."""

    def test_sandbox_resource_returns_content_when_file_exists(self):
        """Verify sandbox resource returns file content when available."""
        if SANDBOX_AGENT_INSTRUCTIONS_PATH.exists():
            content = get_sandbox_instructions()

            # Basic content checks
            assert len(content) > 1000, "Sandbox instructions should be substantial"
            assert "pflow" in content.lower(), "Should mention pflow"
            assert "workflow" in content.lower(), "Should mention workflows"
        else:
            pytest.skip(f"Sandbox instructions file not found at {SANDBOX_AGENT_INSTRUCTIONS_PATH}")

    @patch("pflow.mcp_server.resources.instruction_resources.SANDBOX_AGENT_INSTRUCTIONS_PATH")
    def test_sandbox_resource_returns_fallback_when_file_missing(self, mock_path):
        """Verify graceful fallback when sandbox instructions file missing."""
        mock_path.exists.return_value = False

        content = get_sandbox_instructions()

        # Should return fallback message
        assert "Sandbox" in content
        assert "Not Available" in content

    def test_sandbox_fallback_exists(self):
        """Verify sandbox fallback message exists and provides guidance."""
        fallback = _sandbox_fallback_message()

        # Basic checks - has content and is about sandbox
        assert len(fallback) > 100
        assert "Sandbox" in fallback
        assert "Not Available" in fallback

    def test_sandbox_docstring_mentions_restrictions(self):
        """Verify docstring clarifies sandboxed restrictions."""
        docstring = get_sandbox_instructions.__doc__

        assert docstring is not None
        assert "sandbox" in docstring.lower() or "isolated" in docstring.lower()
        assert "no access" in docstring.lower() or "restricted" in docstring.lower()
        assert "settings.json" in docstring.lower()

    def test_sandbox_docstring_lists_use_cases(self):
        """Verify sandbox docstring explains when to use it."""
        docstring = get_sandbox_instructions.__doc__

        # Should mention typical sandbox scenarios
        has_use_case = any(
            term in docstring.lower() for term in ["container", "web-based", "ci/cd", "multi-tenant", "isolated"]
        )
        assert has_use_case, "Docstring should mention sandbox use cases"

    @patch("pflow.mcp_server.resources.instruction_resources.SANDBOX_AGENT_INSTRUCTIONS_PATH")
    def test_sandbox_resource_handles_read_error_gracefully(self, mock_path):
        """Verify graceful handling of sandbox file read errors."""
        mock_path.exists.return_value = True
        mock_path.read_text.side_effect = OSError("Permission denied")

        content = get_sandbox_instructions()

        # Should return fallback message instead of crashing
        assert "Sandbox" in content
        assert "Not Available" in content
        assert len(content) > 100


class TestResourceDifferences:
    """Test that regular and sandbox resources are appropriately different."""

    def test_fallback_messages_are_different(self):
        """Verify regular and sandbox fallbacks have different content."""
        regular = _regular_fallback_message()
        sandbox = _sandbox_fallback_message()

        # Should be different messages
        assert regular != sandbox
        assert len(regular) > 100
        assert len(sandbox) > 100


class TestResourcePath:
    """Test the path resolution for instruction files."""

    def test_regular_path_structure(self):
        """Verify regular instructions path has correct structure."""
        path_str = str(MCP_AGENT_INSTRUCTIONS_PATH)
        assert ".pflow" in path_str
        assert "instructions" in path_str
        assert "MCP-AGENT_INSTRUCTIONS.md" in path_str

    def test_sandbox_path_structure(self):
        """Verify sandbox instructions path has correct structure."""
        path_str = str(SANDBOX_AGENT_INSTRUCTIONS_PATH)
        assert ".pflow" in path_str
        assert "instructions" in path_str
        assert "MCP-SANDBOX-AGENT_INSTRUCTIONS.md" in path_str

    def test_paths_point_to_different_files(self):
        """Verify regular and sandbox use different files."""
        assert MCP_AGENT_INSTRUCTIONS_PATH != SANDBOX_AGENT_INSTRUCTIONS_PATH
        assert MCP_AGENT_INSTRUCTIONS_PATH.name != SANDBOX_AGENT_INSTRUCTIONS_PATH.name
