"""Tests for instructions CLI commands."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from pflow.cli.instructions import create_instructions, instructions, usage_instructions


@pytest.fixture
def runner() -> CliRunner:
    """Create CLI runner for testing."""
    return CliRunner()


class TestInstructionsGroup:
    """Test the instructions command group."""

    def test_instructions_help(self, runner: CliRunner) -> None:
        """Test that instructions --help shows available commands."""
        result = runner.invoke(instructions, ["--help"])
        assert result.exit_code == 0
        assert "Get instructions for using pflow as an AI agent" in result.output
        assert "usage" in result.output
        assert "create" in result.output

    def test_instructions_without_subcommand(self, runner: CliRunner) -> None:
        """Test that instructions without subcommand shows help."""
        result = runner.invoke(instructions, [])
        # Click returns exit code 2 when no subcommand is provided
        assert result.exit_code == 2
        assert "Commands:" in result.output or "Missing command" in result.output


class TestUsageInstructions:
    """Test the usage instructions command."""

    def test_usage_instructions_success(self, runner: CliRunner) -> None:
        """Test that usage instructions command returns content."""
        result = runner.invoke(usage_instructions, [])
        assert result.exit_code == 0
        assert "pflow - Basic Usage Guide for AI Agents" in result.output
        assert "MANDATORY First Step" in result.output
        assert "pflow workflow discover" in result.output
        assert "Essential Commands" in result.output

    def test_usage_instructions_content_length(self, runner: CliRunner) -> None:
        """Test that usage instructions are focused and concise (~100-150 lines)."""
        result = runner.invoke(usage_instructions, [])
        assert result.exit_code == 0
        line_count = len(result.output.split("\n"))
        # Should be around 100-150 lines (streamlined version), allow reasonable variance
        assert 80 <= line_count <= 200, f"Expected ~100-150 lines, got {line_count}"

    def test_usage_instructions_key_sections(self, runner: CliRunner) -> None:
        """Test that usage instructions contain key sections."""
        result = runner.invoke(usage_instructions, [])
        assert result.exit_code == 0

        # Key sections that should be present in streamlined version
        expected_sections = [
            "MANDATORY First Step",
            "Essential Commands",
            "Workflow Discovery Commands",
            "Execute workflow by name",
            "Instructions for building workflows",
            "Node Commands",
            "Quick Decision Tree",
        ]

        for section in expected_sections:
            assert section in result.output, f"Expected section '{section}' not found"

    def test_usage_instructions_points_to_create(self, runner: CliRunner) -> None:
        """Test that usage instructions mention the create command."""
        result = runner.invoke(usage_instructions, [])
        assert result.exit_code == 0
        assert "pflow instructions create" in result.output

    def test_usage_instructions_help(self, runner: CliRunner) -> None:
        """Test usage command help."""
        result = runner.invoke(usage_instructions, ["--help"])
        assert result.exit_code == 0
        assert "Display basic pflow usage instructions" in result.output
        assert "~500 line guide" in result.output


class TestCreateInstructions:
    """Test the create instructions command."""

    def test_create_instructions_success(self, runner: CliRunner) -> None:
        """Test that create instructions command returns content."""
        result = runner.invoke(create_instructions, [])
        assert result.exit_code == 0
        assert "pflow Agent Instructions - Complete Guide" in result.output
        assert "Core Mission" in result.output
        assert "MANDATORY First Step" in result.output

    def test_create_instructions_content_length(self, runner: CliRunner) -> None:
        """Test that create instructions are comprehensive (~1600 lines)."""
        result = runner.invoke(create_instructions, [])
        assert result.exit_code == 0
        line_count = len(result.output.split("\n"))
        # Should be around 1600 lines, allow reasonable variance
        assert 1000 <= line_count <= 2000, f"Expected ~1600 lines, got {line_count}"

    def test_create_instructions_comprehensive_content(self, runner: CliRunner) -> None:
        """Test that create instructions contain comprehensive sections."""
        result = runner.invoke(create_instructions, [])
        assert result.exit_code == 0

        # Key comprehensive sections (using actual section names from the file)
        expected_sections = [
            "Part 1: Foundation & Mental Model",
            "Two Fundamental Concepts - Edges vs Templates",
            "What Workflows CANNOT Do",
            "Part 2: Node & Tool Selection Principles",
            "Part 3: The Complete Development Loop",
            "Part 4: Building Workflows - Technical Reference",
        ]

        for section in expected_sections:
            assert section in result.output, f"Expected section '{section}' not found"

    def test_create_instructions_help(self, runner: CliRunner) -> None:
        """Test create command help."""
        result = runner.invoke(create_instructions, ["--help"])
        assert result.exit_code == 0
        assert "comprehensive workflow creation instructions" in result.output


class TestInstructionFiles:
    """Test that instruction files exist and have correct structure."""

    def test_basic_usage_file_exists(self) -> None:
        """Test that cli-basic-usage.md file exists."""
        file_path = Path(__file__).parent.parent.parent / "src" / "pflow" / "cli" / "resources" / "cli-basic-usage.md"
        assert file_path.exists(), f"Expected file not found: {file_path}"

    def test_basic_usage_file_content(self) -> None:
        """Test that cli-basic-usage.md has expected content."""
        file_path = Path(__file__).parent.parent.parent / "src" / "pflow" / "cli" / "resources" / "cli-basic-usage.md"
        content = file_path.read_text(encoding="utf-8")

        assert "pflow - Basic Usage Guide for AI Agents" in content
        assert "MANDATORY First Step" in content
        assert "pflow workflow discover" in content
        assert "Essential Commands" in content

    def test_comprehensive_file_exists(self) -> None:
        """Test that cli-agent-instructions.md file exists."""
        file_path = (
            Path(__file__).parent.parent.parent / "src" / "pflow" / "cli" / "resources" / "cli-agent-instructions.md"
        )
        assert file_path.exists(), f"Expected file not found: {file_path}"

    def test_comprehensive_file_content(self) -> None:
        """Test that cli-agent-instructions.md has expected content."""
        file_path = (
            Path(__file__).parent.parent.parent / "src" / "pflow" / "cli" / "resources" / "cli-agent-instructions.md"
        )
        content = file_path.read_text(encoding="utf-8")

        assert "pflow Agent Instructions - Complete Guide" in content
        assert "Core Mission" in content
        assert "Two Fundamental Concepts" in content


class TestEndToEndInstructions:
    """Test instructions commands through main CLI."""

    def test_instructions_usage_via_main_cli(self, runner: CliRunner) -> None:
        """Test that 'pflow instructions usage' works through main CLI."""
        # Note: We can't easily test through main_wrapper without more complex setup
        # This test verifies the command group works standalone
        result = runner.invoke(instructions, ["usage"])
        assert result.exit_code == 0
        assert "pflow - Basic Usage Guide" in result.output

    def test_instructions_create_via_main_cli(self, runner: CliRunner) -> None:
        """Test that 'pflow instructions create' works through main CLI."""
        result = runner.invoke(instructions, ["create"])
        assert result.exit_code == 0
        assert "pflow Agent Instructions - Complete Guide" in result.output
