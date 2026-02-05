"""Tests for pflow skill CLI commands."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from pflow.cli.skills import skill


class TestSkillSaveCommand:
    """Tests for 'pflow skill save' command."""

    @patch("pflow.cli.skills.create_skill_symlink")
    @patch("pflow.cli.skills.enrich_workflow")
    @patch("pflow.cli.skills.find_skill_for_workflow")
    @patch("pflow.cli.skills.WorkflowManager")
    def test_skill_save_creates_symlink(
        self,
        mock_wm_cls: MagicMock,
        mock_find: MagicMock,
        mock_enrich: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Test successful skill save creates symlink and enriches workflow."""
        # Setup mocks
        mock_wm = MagicMock()
        mock_wm_cls.return_value = mock_wm
        mock_wm.exists.return_value = True
        mock_wm.load.return_value = {
            "description": "Test workflow description",
            "ir": {"inputs": {"param1": {"required": True}}, "nodes": []},
        }
        mock_wm.get_path.return_value = "/home/user/.pflow/workflows/test-workflow.pflow.md"
        mock_wm.workflows_dir = Path("/home/user/.pflow/workflows")
        mock_find.return_value = []  # No existing skills
        mock_create.return_value = Path("/home/user/project/.claude/skills/test-workflow/SKILL.md")

        runner = CliRunner()
        result = runner.invoke(skill, ["save", "test-workflow"])

        # Verify success
        assert result.exit_code == 0
        assert "Published 'test-workflow' to Claude Code" in result.output
        assert "Symlink: /home/user/project/.claude/skills/test-workflow/SKILL.md" in result.output
        assert "Source:  /home/user/.pflow/workflows/test-workflow.pflow.md" in result.output

        # Verify workflow was enriched
        mock_enrich.assert_called_once()
        call_kwargs = mock_enrich.call_args[1]
        assert call_kwargs["name"] == "test-workflow"
        assert call_kwargs["description"] == "Test workflow description"
        assert "inputs" in call_kwargs["ir"]

        # Verify symlink was created with default target (claude)
        mock_create.assert_called_once()
        create_kwargs = mock_create.call_args[1]
        assert create_kwargs["skill_name"] == "test-workflow"
        assert create_kwargs["scope"] == "project"
        assert create_kwargs["target"] == "claude"

    @patch("pflow.cli.skills.WorkflowManager")
    def test_skill_save_workflow_not_found(self, mock_wm_cls: MagicMock) -> None:
        """Test error message when workflow doesn't exist."""
        mock_wm = MagicMock()
        mock_wm_cls.return_value = mock_wm
        mock_wm.exists.return_value = False

        runner = CliRunner()
        result = runner.invoke(skill, ["save", "nonexistent-workflow"])

        # Verify error output
        assert result.exit_code == 1
        assert "Error: Workflow 'nonexistent-workflow' not found." in result.output
        assert "Save it first with: pflow workflow save" in result.output
        assert "nonexistent-workflow" in result.output

    @patch("pflow.cli.skills.create_skill_symlink")
    @patch("pflow.cli.skills.enrich_workflow")
    @patch("pflow.cli.skills.find_skill_for_workflow")
    @patch("pflow.cli.skills.WorkflowManager")
    def test_skill_save_updates_existing(
        self,
        mock_wm_cls: MagicMock,
        mock_find: MagicMock,
        mock_enrich: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Test saving when skill already exists re-enriches without creating new symlink."""
        # Setup mocks
        mock_wm = MagicMock()
        mock_wm_cls.return_value = mock_wm
        mock_wm.exists.return_value = True
        mock_wm.load.return_value = {
            "description": "Test workflow",
            "ir": {"inputs": {}, "nodes": []},
        }
        mock_wm.get_path.return_value = "/home/user/.pflow/workflows/test-workflow.pflow.md"
        mock_wm.workflows_dir = Path("/home/user/.pflow/workflows")

        # Mock existing skill
        from pflow.core.skill_service import SkillInfo

        existing_skill = SkillInfo(
            name="test-workflow",
            scope="project",
            target="claude",
            symlink_path=Path("/project/.claude/skills/test-workflow/SKILL.md"),
            target_path=Path("/home/user/.pflow/workflows/test-workflow.pflow.md"),
            is_valid=True,
        )
        mock_find.return_value = [existing_skill]

        runner = CliRunner()
        result = runner.invoke(skill, ["save", "test-workflow"])

        # Verify success with "Updated" message
        assert result.exit_code == 0
        assert "Updated 'test-workflow'" in result.output

        # Verify enrichment happened
        mock_enrich.assert_called_once()

        # Verify NO new symlink was created (skill already exists)
        mock_create.assert_not_called()

    @patch("pflow.cli.skills.create_skill_symlink")
    @patch("pflow.cli.skills.enrich_workflow")
    @patch("pflow.cli.skills.find_skill_for_workflow")
    @patch("pflow.cli.skills.WorkflowManager")
    def test_skill_save_personal_scope(
        self,
        mock_wm_cls: MagicMock,
        mock_find: MagicMock,
        mock_enrich: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Test saving skill to personal scope with --personal flag."""
        # Setup mocks
        mock_wm = MagicMock()
        mock_wm_cls.return_value = mock_wm
        mock_wm.exists.return_value = True
        mock_wm.load.return_value = {
            "description": "Personal workflow",
            "ir": {"inputs": {}, "nodes": []},
        }
        mock_wm.get_path.return_value = "/home/user/.pflow/workflows/my-workflow.pflow.md"
        mock_wm.workflows_dir = Path("/home/user/.pflow/workflows")
        mock_find.return_value = []
        mock_create.return_value = Path("/home/user/.claude/skills/my-workflow/SKILL.md")

        runner = CliRunner()
        result = runner.invoke(skill, ["save", "my-workflow", "--personal"])

        # Verify success with personal scope message
        assert result.exit_code == 0
        assert "Published 'my-workflow' to Claude Code" in result.output
        assert "~/.claude/skills/" in result.output

        # Verify correct scope was passed
        create_kwargs = mock_create.call_args[1]
        assert create_kwargs["scope"] == "personal"

    @patch("pflow.cli.skills.create_skill_symlink")
    @patch("pflow.cli.skills.enrich_workflow")
    @patch("pflow.cli.skills.find_skill_for_workflow")
    @patch("pflow.cli.skills.WorkflowManager")
    def test_skill_save_multiple_targets(
        self,
        mock_wm_cls: MagicMock,
        mock_find: MagicMock,
        mock_enrich: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Test saving skill to multiple targets with --cursor --copilot flags."""
        # Setup mocks
        mock_wm = MagicMock()
        mock_wm_cls.return_value = mock_wm
        mock_wm.exists.return_value = True
        mock_wm.load.return_value = {
            "description": "Multi-target workflow",
            "ir": {"inputs": {}, "nodes": []},
        }
        mock_wm.get_path.return_value = "/home/user/.pflow/workflows/my-workflow.pflow.md"
        mock_wm.workflows_dir = Path("/home/user/.pflow/workflows")
        mock_find.return_value = []
        mock_create.side_effect = [
            Path("/project/.cursor/skills/my-workflow/SKILL.md"),
            Path("/project/.github/skills/my-workflow/SKILL.md"),
        ]

        runner = CliRunner()
        result = runner.invoke(skill, ["save", "my-workflow", "--cursor", "--copilot"])

        # Verify success for both targets
        assert result.exit_code == 0
        assert "Published 'my-workflow' to Cursor" in result.output
        assert "Published 'my-workflow' to Copilot" in result.output

        # Verify symlinks created for both targets
        assert mock_create.call_count == 2
        call_targets = [call[1]["target"] for call in mock_create.call_args_list]
        assert "cursor" in call_targets
        assert "copilot" in call_targets


class TestSkillListCommand:
    """Tests for 'pflow skill list' command."""

    @patch("pflow.cli.skills.find_pflow_skills")
    def test_skill_list_shows_skills(self, mock_find: MagicMock) -> None:
        """Test listing skills shows all pflow-managed skills grouped by workflow."""
        from pflow.core.skill_service import SkillInfo

        mock_skills = [
            SkillInfo(
                name="analyze-logs",
                scope="project",
                target="claude",
                symlink_path=Path("/project/.claude/skills/analyze-logs/SKILL.md"),
                target_path=Path("/home/user/.pflow/workflows/analyze-logs.pflow.md"),
                is_valid=True,
            ),
            SkillInfo(
                name="analyze-logs",
                scope="personal",
                target="cursor",
                symlink_path=Path("/home/user/.cursor/skills/analyze-logs/SKILL.md"),
                target_path=Path("/home/user/.pflow/workflows/analyze-logs.pflow.md"),
                is_valid=True,
            ),
            SkillInfo(
                name="broken-skill",
                scope="project",
                target="copilot",
                symlink_path=Path("/project/.github/skills/broken-skill/SKILL.md"),
                target_path=Path("/home/user/.pflow/workflows/missing.pflow.md"),
                is_valid=False,
            ),
        ]
        mock_find.return_value = mock_skills

        runner = CliRunner()
        result = runner.invoke(skill, ["list"])

        # Verify output structure
        assert result.exit_code == 0
        assert "pflow skills:" in result.output

        # Check workflow grouping - analyze-logs should show both targets
        assert "analyze-logs" in result.output
        assert "→ Claude Code (project)" in result.output
        assert "→ Cursor (personal)" in result.output

        # Check broken link is marked and specific fix commands are shown
        assert "[broken link]" in result.output
        assert "source workflow 'missing' was deleted" in result.output
        assert "To restore: pflow workflow save <file> --name missing --force" in result.output
        assert "To remove:  pflow skill remove missing --copilot" in result.output

    @patch("pflow.cli.skills.find_pflow_skills")
    def test_skill_list_empty(self, mock_find: MagicMock) -> None:
        """Test list command with no skills shows helpful message."""
        mock_find.return_value = []

        runner = CliRunner()
        result = runner.invoke(skill, ["list"])

        # Verify empty state message
        assert result.exit_code == 0
        assert "No pflow skills found." in result.output


class TestSkillRemoveCommand:
    """Tests for 'pflow skill remove' command."""

    @patch("pflow.cli.skills.remove_skill_service")
    def test_skill_remove_deletes(self, mock_remove: MagicMock) -> None:
        """Test successful skill removal."""
        mock_remove.return_value = True

        runner = CliRunner()
        result = runner.invoke(skill, ["remove", "test-workflow"])

        # Verify success
        assert result.exit_code == 0
        assert "Removed skill 'test-workflow'" in result.output
        assert "Claude Code" in result.output

        # Verify service was called with correct scope and default target
        mock_remove.assert_called_once_with("test-workflow", "project", "claude")

    @patch("pflow.cli.skills.remove_skill_service")
    def test_skill_remove_not_found(self, mock_remove: MagicMock) -> None:
        """Test error message when skill doesn't exist."""
        mock_remove.return_value = False

        runner = CliRunner()
        result = runner.invoke(skill, ["remove", "nonexistent-skill"])

        # Verify error output
        assert result.exit_code == 1
        assert "Skill 'nonexistent-skill' not found" in result.output

    @patch("pflow.cli.skills.remove_skill_service")
    def test_skill_remove_personal_scope(self, mock_remove: MagicMock) -> None:
        """Test removing skill from personal scope with --personal flag."""
        mock_remove.return_value = True

        runner = CliRunner()
        result = runner.invoke(skill, ["remove", "my-skill", "--personal"])

        # Verify success with personal scope message
        assert result.exit_code == 0
        assert "Removed skill 'my-skill'" in result.output
        assert "~/.claude/skills/" in result.output

        # Verify correct scope was passed
        mock_remove.assert_called_once_with("my-skill", "personal", "claude")

    @patch("pflow.cli.skills.remove_skill_service")
    def test_skill_remove_multiple_targets(self, mock_remove: MagicMock) -> None:
        """Test removing skill from multiple targets."""
        mock_remove.return_value = True

        runner = CliRunner()
        result = runner.invoke(skill, ["remove", "my-skill", "--cursor", "--codex"])

        # Verify success
        assert result.exit_code == 0
        assert "Removed skill 'my-skill' from Cursor" in result.output
        assert "Removed skill 'my-skill' from Codex" in result.output

        # Verify service called for both targets
        assert mock_remove.call_count == 2


class TestSkillCommandGroup:
    """Tests for skill command group."""

    def test_skill_help(self) -> None:
        """Test that skill command group help shows supported tools."""
        runner = CliRunner()
        result = runner.invoke(skill, ["--help"])

        assert result.exit_code == 0
        # Check help text structure
        assert "Publish workflows as AI agent skills" in result.output
        assert "source of truth" in result.output
        # Check all tools are listed
        assert "Claude Code" in result.output
        assert "Cursor" in result.output
        assert "Codex" in result.output
        assert "Copilot" in result.output
        # Check subcommands
        assert "save" in result.output
        assert "list" in result.output
        assert "remove" in result.output

    def test_skill_without_subcommand(self) -> None:
        """Test that skill command without subcommand shows help."""
        runner = CliRunner()
        result = runner.invoke(skill)

        # Click shows usage/help text
        assert "Publish workflows as AI agent skills" in result.output or result.exit_code == 0
