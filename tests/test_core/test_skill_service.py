"""Tests for skill service module."""

from pathlib import Path

import pytest
import yaml

from pflow.core.markdown_parser import parse_markdown
from pflow.core.skill_service import (
    _inject_or_replace_usage,
    create_skill_symlink,
    enrich_workflow,
    find_pflow_skills,
    find_skill_for_workflow,
    generate_usage_section,
    remove_skill,
)
from pflow.core.workflow_manager import WorkflowManager

# Sample workflow markdown for testing
SAMPLE_WORKFLOW_WITH_REQUIRED = """# Test Workflow

A test workflow with required inputs.

## Inputs

### repo

Repository name.

- type: string
- required: true

### branch

Branch name.

- type: string
- required: true

### verbose

Verbose output.

- type: boolean
- required: false
- default: false

## Steps

### fetch-data

Fetch data from repository.

- type: shell
- command: echo "hello"
"""

SAMPLE_WORKFLOW_NO_INPUTS = """# Test Workflow

A test workflow with no inputs.

## Steps

### fetch-data

Fetch data.

- type: shell
- command: echo "hello"
"""

SAMPLE_WORKFLOW_OPTIONAL_ONLY = """# Test Workflow

A test workflow with only optional inputs.

## Inputs

### verbose

Verbose output.

- type: boolean
- required: false
- default: false

### debug

Debug mode.

- type: boolean
- required: false
- default: false

## Steps

### fetch-data

Fetch data.

- type: shell
- command: echo "hello"
"""

SAMPLE_WORKFLOW_WITH_STDIN = """# Test Workflow

A test workflow with stdin input.

## Inputs

### content

Content to process (from stdin).

- type: string
- stdin: true
- required: true

### format

Output format.

- type: string
- required: true

## Steps

### process

Process the content.

- type: shell
- command: echo "processing"
"""


class TestGenerateUsageSection:
    """Test generate_usage_section function."""

    def test_generate_usage_with_required_inputs(self):
        """Test usage generation with required parameters."""
        ir = {
            "inputs": {
                "repo": {"type": "string", "required": True},
                "branch": {"type": "string", "required": True},
                "verbose": {"type": "boolean", "required": False, "default": False},
            }
        }

        usage = generate_usage_section("test-workflow", ir)

        # Should include required params in command
        assert "pflow test-workflow repo=<value> branch=<value>" in usage
        # Should not include optional params
        assert "verbose" not in usage
        # Should include standard sections
        assert "## Usage" in usage
        assert "If you are unsure this is exactly what the user wants" in usage
        assert "pflow instructions create" in usage
        # Should include history command hint
        assert "pflow workflow history test-workflow" in usage

    def test_generate_usage_with_no_inputs(self):
        """Test usage generation when workflow has no inputs."""
        ir = {"inputs": {}}

        usage = generate_usage_section("no-inputs", ir)

        # Command should have no parameters
        assert "pflow no-inputs" in usage
        assert "=<value>" not in usage
        # Standard sections should still be present
        assert "## Usage" in usage

    def test_generate_usage_with_optional_only(self):
        """Test usage generation with only optional inputs."""
        ir = {
            "inputs": {
                "verbose": {"type": "boolean", "required": False},
                "debug": {"type": "boolean", "required": False},
            }
        }

        usage = generate_usage_section("optional-workflow", ir)

        # Command should have no parameters (optional params omitted)
        assert "pflow optional-workflow" in usage
        assert "verbose" not in usage
        assert "debug" not in usage

    def test_generate_usage_skips_stdin_inputs(self):
        """Test that stdin: true inputs are excluded from CLI command."""
        ir = {
            "inputs": {
                "content": {"type": "string", "stdin": True, "required": True},
                "format": {"type": "string", "required": True},
            }
        }

        usage = generate_usage_section("stdin-workflow", ir)

        # Should include non-stdin required param
        assert "format=<value>" in usage
        # Should NOT include stdin param (it's piped, not CLI arg)
        assert "content" not in usage


class TestInjectOrReplaceUsage:
    """Test _inject_or_replace_usage function."""

    def test_inject_usage_before_first_section(self):
        """Test injecting usage section before first ## heading."""
        body = """A workflow description.

More details here.

## Inputs

### param1

Parameter description.
"""
        usage = "## Usage\n\nUsage instructions here."

        result = _inject_or_replace_usage(body, usage)

        # Usage should appear before ## Inputs
        assert "## Usage" in result
        usage_pos = result.find("## Usage")
        inputs_pos = result.find("## Inputs")
        assert usage_pos < inputs_pos
        # Original content should be preserved
        assert "## Inputs" in result
        assert "### param1" in result

    def test_replace_existing_usage(self):
        """Test replacing existing ## Usage section."""
        body = """A workflow description.

## Usage

Old usage instructions.

Some more old text.

## Inputs

### param1

Parameter description.
"""
        usage = "## Usage\n\nNew usage instructions."

        result = _inject_or_replace_usage(body, usage)

        # Should have new usage, not old
        assert "New usage instructions" in result
        assert "Old usage instructions" not in result
        assert "Some more old text" not in result
        # Should only have one ## Usage section
        assert result.count("## Usage") == 1
        # Other sections preserved
        assert "## Inputs" in result

    def test_inject_when_no_sections(self):
        """Test injecting usage when body has no ## sections."""
        body = """A workflow description.

Some more prose here.
"""
        usage = "## Usage\n\nUsage instructions."

        result = _inject_or_replace_usage(body, usage)

        # Usage should be appended
        assert "## Usage" in result
        assert result.endswith("Usage instructions.\n")
        # Original content preserved
        assert "A workflow description" in result


class TestEnrichWorkflow:
    """Test enrich_workflow function."""

    def test_enrich_adds_name_to_frontmatter(self, tmp_path):
        """Test that enrichment adds name field to YAML frontmatter."""
        wm = WorkflowManager(workflows_dir=tmp_path / "workflows")
        wm.save("test-workflow", SAMPLE_WORKFLOW_WITH_REQUIRED)

        workflow_path = Path(wm.get_path("test-workflow"))
        ir = wm.load_ir("test-workflow")

        # Enrich the workflow
        enrich_workflow(
            workflow_path=workflow_path,
            name="test-workflow",
            description="Test description",
            ir=ir,
        )

        # Read back and verify frontmatter
        content = workflow_path.read_text(encoding="utf-8")
        lines = content.split("---\n")
        frontmatter = yaml.safe_load(lines[1])

        assert frontmatter["name"] == "test-workflow"

    def test_enrich_adds_description_to_frontmatter(self, tmp_path):
        """Test that enrichment adds description field to frontmatter."""
        wm = WorkflowManager(workflows_dir=tmp_path / "workflows")
        wm.save("test-workflow", SAMPLE_WORKFLOW_WITH_REQUIRED)

        workflow_path = Path(wm.get_path("test-workflow"))
        ir = wm.load_ir("test-workflow")

        enrich_workflow(
            workflow_path=workflow_path,
            name="test-workflow",
            description="A comprehensive test description",
            ir=ir,
        )

        content = workflow_path.read_text(encoding="utf-8")
        lines = content.split("---\n")
        frontmatter = yaml.safe_load(lines[1])

        assert frontmatter["description"] == "A comprehensive test description"

    def test_enrich_injects_usage_section(self, tmp_path):
        """Test that enrichment injects ## Usage section into body."""
        wm = WorkflowManager(workflows_dir=tmp_path / "workflows")
        wm.save("test-workflow", SAMPLE_WORKFLOW_WITH_REQUIRED)

        workflow_path = Path(wm.get_path("test-workflow"))
        ir = wm.load_ir("test-workflow")

        enrich_workflow(
            workflow_path=workflow_path,
            name="test-workflow",
            description="Test description",
            ir=ir,
        )

        content = workflow_path.read_text(encoding="utf-8")
        # Extract body (after frontmatter)
        parts = content.split("---\n", 2)
        body = parts[2] if len(parts) > 2 else ""

        # Should have ## Usage section
        assert "## Usage" in body
        assert "pflow test-workflow" in body
        assert "repo=<value> branch=<value>" in body

    def test_enrich_preserves_other_frontmatter(self, tmp_path):
        """Test that enrichment preserves existing frontmatter fields."""
        wm = WorkflowManager(workflows_dir=tmp_path / "workflows")
        wm.save("test-workflow", SAMPLE_WORKFLOW_WITH_REQUIRED)

        workflow_path = Path(wm.get_path("test-workflow"))
        ir = wm.load_ir("test-workflow")

        # Get original frontmatter
        content_before = workflow_path.read_text(encoding="utf-8")
        lines_before = content_before.split("---\n")
        frontmatter_before = yaml.safe_load(lines_before[1])
        created_at_before = frontmatter_before["created_at"]
        version_before = frontmatter_before["version"]

        # Enrich
        enrich_workflow(
            workflow_path=workflow_path,
            name="test-workflow",
            description="Test description",
            ir=ir,
        )

        # Verify original fields preserved
        content_after = workflow_path.read_text(encoding="utf-8")
        lines_after = content_after.split("---\n")
        frontmatter_after = yaml.safe_load(lines_after[1])

        assert frontmatter_after["created_at"] == created_at_before
        assert frontmatter_after["version"] == version_before
        assert "updated_at" in frontmatter_after

    def test_enriched_workflow_still_parses(self, tmp_path):
        """Test that enriched workflow file can still be parsed and IR matches."""
        wm = WorkflowManager(workflows_dir=tmp_path / "workflows")
        wm.save("test-workflow", SAMPLE_WORKFLOW_WITH_REQUIRED)

        workflow_path = Path(wm.get_path("test-workflow"))
        ir_before = wm.load_ir("test-workflow")

        # Enrich
        enrich_workflow(
            workflow_path=workflow_path,
            name="test-workflow",
            description="Test description",
            ir=ir_before,
        )

        # Parse enriched file
        enriched_content = workflow_path.read_text(encoding="utf-8")
        parse_result = parse_markdown(enriched_content)
        ir_after = parse_result.ir

        # IR should still match (## Usage doesn't affect IR)
        assert len(ir_after["nodes"]) == len(ir_before["nodes"])
        assert ir_after["nodes"][0]["id"] == ir_before["nodes"][0]["id"]
        assert ir_after["nodes"][0]["type"] == ir_before["nodes"][0]["type"]

        # Inputs should match
        assert "repo" in ir_after.get("inputs", {})
        assert "branch" in ir_after.get("inputs", {})


class TestSkillEndToEnd:
    """End-to-end test for the full skill workflow."""

    def test_skill_symlink_readable_as_valid_skill(self, tmp_path):
        """Test that reading through the symlink produces valid skill content.

        This tests the actual agent experience:
        1. Workflow saved and enriched
        2. Skill symlink created
        3. Agent reads SKILL.md via symlink
        4. Content has name, description, ## Usage section
        5. Workflow is still executable (IR parses correctly)
        """
        wm = WorkflowManager(workflows_dir=tmp_path / "workflows")
        wm.save("release-notes", SAMPLE_WORKFLOW_WITH_REQUIRED)
        workflow_path = Path(wm.get_path("release-notes"))

        # Enrich workflow
        enrich_workflow(
            workflow_path=workflow_path,
            name="release-notes",
            description="Generate release notes",
            ir=wm.load_ir("release-notes"),
        )

        # Create skill symlink
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        symlink_path = create_skill_symlink(
            workflow_path=workflow_path,
            skill_name="release-notes",
            scope="project",
            project_dir=project_dir,
        )

        # Agent reads skill via symlink (this is what Claude Code does)
        skill_content = symlink_path.read_text(encoding="utf-8")

        # Skill has required metadata for Claude Code
        assert "name: release-notes" in skill_content
        assert "description: Generate release notes" in skill_content

        # Skill has Usage section with execution command
        assert "## Usage" in skill_content
        assert "pflow release-notes" in skill_content
        assert "pflow workflow history release-notes" in skill_content

        # Workflow is still valid and executable
        parse_result = parse_markdown(skill_content)
        assert len(parse_result.ir["nodes"]) > 0
        assert "repo" in parse_result.ir.get("inputs", {})


class TestCreateSkillSymlink:
    """Test create_skill_symlink function."""

    def test_create_skill_symlink_project(self, tmp_path):
        """Test creating skill symlink in project scope."""
        wm = WorkflowManager(workflows_dir=tmp_path / "workflows")
        wm.save("my-workflow", SAMPLE_WORKFLOW_WITH_REQUIRED)
        workflow_path = Path(wm.get_path("my-workflow"))

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        symlink_path = create_skill_symlink(
            workflow_path=workflow_path,
            skill_name="my-skill",
            scope="project",
            project_dir=project_dir,
        )

        # Verify symlink created at correct location
        expected_path = project_dir / ".claude" / "skills" / "my-skill" / "SKILL.md"
        assert symlink_path == expected_path
        assert symlink_path.is_symlink()
        assert symlink_path.resolve() == workflow_path.resolve()

    def test_create_skill_symlink_personal(self, tmp_path, monkeypatch):
        """Test creating skill symlink in personal scope."""
        # Mock home directory
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        wm = WorkflowManager(workflows_dir=tmp_path / "workflows")
        wm.save("my-workflow", SAMPLE_WORKFLOW_WITH_REQUIRED)
        workflow_path = Path(wm.get_path("my-workflow"))

        symlink_path = create_skill_symlink(
            workflow_path=workflow_path,
            skill_name="my-skill",
            scope="personal",
        )

        # Verify symlink created in home directory
        expected_path = fake_home / ".claude" / "skills" / "my-skill" / "SKILL.md"
        assert symlink_path == expected_path
        assert symlink_path.is_symlink()

    def test_create_skill_symlink_already_exists(self, tmp_path):
        """Test error when skill symlink already exists."""
        wm = WorkflowManager(workflows_dir=tmp_path / "workflows")
        wm.save("my-workflow", SAMPLE_WORKFLOW_WITH_REQUIRED)
        workflow_path = Path(wm.get_path("my-workflow"))

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create first symlink
        create_skill_symlink(
            workflow_path=workflow_path,
            skill_name="my-skill",
            scope="project",
            project_dir=project_dir,
        )

        # Try to create again - should raise FileExistsError
        with pytest.raises(FileExistsError, match="Skill 'my-skill' already exists"):
            create_skill_symlink(
                workflow_path=workflow_path,
                skill_name="my-skill",
                scope="project",
                project_dir=project_dir,
            )

    def test_remove_skill_deletes_symlink_and_dir(self, tmp_path):
        """Test that remove_skill deletes symlink and parent directory."""
        wm = WorkflowManager(workflows_dir=tmp_path / "workflows")
        wm.save("my-workflow", SAMPLE_WORKFLOW_WITH_REQUIRED)
        workflow_path = Path(wm.get_path("my-workflow"))

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create symlink
        symlink_path = create_skill_symlink(
            workflow_path=workflow_path,
            skill_name="my-skill",
            scope="project",
            project_dir=project_dir,
        )

        # Remove skill
        removed = remove_skill(
            skill_name="my-skill",
            scope="project",
            project_dir=project_dir,
        )

        assert removed is True
        assert not symlink_path.exists()
        # Parent directory should also be removed
        assert not symlink_path.parent.exists()


class TestFindPflowSkills:
    """Test find_pflow_skills function."""

    def test_find_pflow_skills_finds_project_skills(self, tmp_path):
        """Test finding skills in project scope."""
        wm = WorkflowManager(workflows_dir=tmp_path / "workflows")
        wm.save("workflow-1", SAMPLE_WORKFLOW_WITH_REQUIRED)
        wm.save("workflow-2", SAMPLE_WORKFLOW_NO_INPUTS)

        workflow_path_1 = Path(wm.get_path("workflow-1"))
        workflow_path_2 = Path(wm.get_path("workflow-2"))

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create two project skills (use target="claude" explicitly for test clarity)
        create_skill_symlink(workflow_path_1, "skill-1", "project", target="claude", project_dir=project_dir)
        create_skill_symlink(workflow_path_2, "skill-2", "project", target="claude", project_dir=project_dir)

        # Find skills
        skills = find_pflow_skills(
            project_dir=project_dir,
            workflows_dir=tmp_path / "workflows",
        )

        # Should find both project skills
        assert len(skills) == 2
        skill_names = {s.name for s in skills}
        assert skill_names == {"skill-1", "skill-2"}
        # All should be project scope and claude target
        assert all(s.scope == "project" for s in skills)
        assert all(s.target == "claude" for s in skills)

    def test_find_pflow_skills_finds_personal_skills(self, tmp_path, monkeypatch):
        """Test finding skills in personal scope."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        wm = WorkflowManager(workflows_dir=tmp_path / "workflows")
        wm.save("workflow-1", SAMPLE_WORKFLOW_WITH_REQUIRED)
        workflow_path = Path(wm.get_path("workflow-1"))

        # Create personal skill
        create_skill_symlink(workflow_path, "personal-skill", "personal", target="claude")

        # Find skills
        skills = find_pflow_skills(
            project_dir=tmp_path / "project",  # Different from home
            workflows_dir=tmp_path / "workflows",
        )

        # Should find personal skill
        assert len(skills) == 1
        assert skills[0].name == "personal-skill"
        assert skills[0].scope == "personal"
        assert skills[0].target == "claude"

    def test_find_pflow_skills_ignores_non_pflow(self, tmp_path):
        """Test that non-pflow skills are ignored."""
        wm = WorkflowManager(workflows_dir=tmp_path / "workflows")
        wm.save("workflow-1", SAMPLE_WORKFLOW_WITH_REQUIRED)
        workflow_path = Path(wm.get_path("workflow-1"))

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create pflow skill
        create_skill_symlink(workflow_path, "pflow-skill", "project", target="claude", project_dir=project_dir)

        # Create non-pflow skill (pointing to different location)
        non_pflow_dir = project_dir / ".claude" / "skills" / "other-skill"
        non_pflow_dir.mkdir(parents=True)
        non_pflow_file = tmp_path / "other.md"
        non_pflow_file.write_text("# Other Skill")
        (non_pflow_dir / "SKILL.md").symlink_to(non_pflow_file)

        # Create regular file (not symlink)
        regular_dir = project_dir / ".claude" / "skills" / "regular"
        regular_dir.mkdir(parents=True)
        (regular_dir / "SKILL.md").write_text("# Regular Skill")

        # Find skills
        skills = find_pflow_skills(
            project_dir=project_dir,
            workflows_dir=tmp_path / "workflows",
        )

        # Should only find pflow skill
        assert len(skills) == 1
        assert skills[0].name == "pflow-skill"

    def test_find_pflow_skills_detects_broken_links(self, tmp_path):
        """Test that broken symlinks are detected with is_valid=False."""
        wm = WorkflowManager(workflows_dir=tmp_path / "workflows")
        wm.save("workflow-1", SAMPLE_WORKFLOW_WITH_REQUIRED)
        workflow_path = Path(wm.get_path("workflow-1"))

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create valid skill
        create_skill_symlink(workflow_path, "valid-skill", "project", target="claude", project_dir=project_dir)

        # Create skill then delete the workflow (breaking symlink)
        wm.save("workflow-2", SAMPLE_WORKFLOW_NO_INPUTS)
        workflow_path_2 = Path(wm.get_path("workflow-2"))
        create_skill_symlink(workflow_path_2, "broken-skill", "project", target="claude", project_dir=project_dir)
        workflow_path_2.unlink()  # Break the symlink

        # Find skills
        skills = find_pflow_skills(
            project_dir=project_dir,
            workflows_dir=tmp_path / "workflows",
        )

        # Should find both, but broken one marked invalid
        assert len(skills) == 2
        skills_by_name = {s.name: s for s in skills}

        assert skills_by_name["valid-skill"].is_valid is True
        assert skills_by_name["broken-skill"].is_valid is False

    def test_find_skill_for_workflow(self, tmp_path):
        """Test finding skills filtered by workflow name."""
        wm = WorkflowManager(workflows_dir=tmp_path / "workflows")
        wm.save("workflow-1", SAMPLE_WORKFLOW_WITH_REQUIRED)
        wm.save("workflow-2", SAMPLE_WORKFLOW_NO_INPUTS)

        workflow_path_1 = Path(wm.get_path("workflow-1"))
        workflow_path_2 = Path(wm.get_path("workflow-2"))

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create two skills pointing to workflow-1
        create_skill_symlink(workflow_path_1, "skill-1a", "project", target="claude", project_dir=project_dir)
        create_skill_symlink(workflow_path_1, "skill-1b", "project", target="claude", project_dir=project_dir)

        # Create one skill pointing to workflow-2
        create_skill_symlink(workflow_path_2, "skill-2", "project", target="claude", project_dir=project_dir)

        # Find skills for workflow-1
        skills = find_skill_for_workflow(
            workflow_name="workflow-1",
            project_dir=project_dir,
            workflows_dir=tmp_path / "workflows",
        )

        # Should find only the two skills for workflow-1
        assert len(skills) == 2
        skill_names = {s.name for s in skills}
        assert skill_names == {"skill-1a", "skill-1b"}

    def test_find_pflow_skills_finds_all_targets(self, tmp_path):
        """Test finding skills across all tool targets."""
        wm = WorkflowManager(workflows_dir=tmp_path / "workflows")
        wm.save("workflow-1", SAMPLE_WORKFLOW_WITH_REQUIRED)
        workflow_path = Path(wm.get_path("workflow-1"))

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create skills in different targets
        create_skill_symlink(workflow_path, "skill-claude", "project", target="claude", project_dir=project_dir)
        create_skill_symlink(workflow_path, "skill-cursor", "project", target="cursor", project_dir=project_dir)
        create_skill_symlink(workflow_path, "skill-codex", "project", target="codex", project_dir=project_dir)
        create_skill_symlink(workflow_path, "skill-copilot", "project", target="copilot", project_dir=project_dir)

        # Find all skills
        skills = find_pflow_skills(
            project_dir=project_dir,
            workflows_dir=tmp_path / "workflows",
        )

        # Should find all 4 skills
        assert len(skills) == 4
        targets_found = {s.target for s in skills}
        assert targets_found == {"claude", "cursor", "codex", "copilot"}


class TestReEnrichment:
    """Test re-enrichment after workflow re-save."""

    def test_re_enrich_restores_usage_section_after_resave(self, tmp_path, monkeypatch):
        """Test that ## Usage section is restored after workflow save --force."""
        from unittest.mock import patch

        from pflow.core.skill_service import re_enrich_if_skill

        # Create workflows directory and workflow
        workflows_dir = tmp_path / "workflows"
        wm = WorkflowManager(workflows_dir=workflows_dir)
        wm.save("my-workflow", SAMPLE_WORKFLOW_WITH_REQUIRED)
        workflow_path = Path(wm.get_path("my-workflow"))

        # Create project directory and skill
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Enrich and create skill
        enrich_workflow(
            workflow_path=workflow_path,
            name="my-workflow",
            description="Test workflow",
            ir=wm.load_ir("my-workflow"),
        )
        create_skill_symlink(workflow_path, "my-workflow", "project", target="claude", project_dir=project_dir)

        # Verify enrichment exists
        content_before = workflow_path.read_text(encoding="utf-8")
        assert "## Usage" in content_before
        assert "name: my-workflow" in content_before

        # Simulate workflow save --force by overwriting the file
        # (This is what happens when save_workflow_with_options deletes + saves)
        wm_new = WorkflowManager(workflows_dir=workflows_dir)
        workflow_path.unlink()
        wm_new.save("my-workflow", SAMPLE_WORKFLOW_NO_INPUTS)

        # Verify enrichment is gone
        content_after_save = workflow_path.read_text(encoding="utf-8")
        assert "## Usage" not in content_after_save
        assert "name: my-workflow" not in content_after_save

        # Mock Path.cwd() and WorkflowManager to use our test directories
        monkeypatch.setattr(Path, "cwd", lambda: project_dir)

        # Patch WorkflowManager in skill_service to use our workflows_dir
        with patch(
            "pflow.core.skill_service.WorkflowManager",
            lambda workflows_dir=None: WorkflowManager(workflows_dir=workflows_dir or (tmp_path / "workflows")),
        ):
            # Call re-enrich
            re_enrich_if_skill("my-workflow")

        # Verify enrichment is restored
        content_after_reenrich = workflow_path.read_text(encoding="utf-8")
        assert "## Usage" in content_after_reenrich
        assert "name: my-workflow" in content_after_reenrich
        # New workflow has no inputs, so command should have no params
        assert "pflow my-workflow\n" in content_after_reenrich

    def test_re_enrich_replaces_usage_not_duplicates(self, tmp_path, monkeypatch):
        """Test that re-enrichment replaces ## Usage, doesn't duplicate it."""
        from unittest.mock import patch

        from pflow.core.skill_service import re_enrich_if_skill

        workflows_dir = tmp_path / "workflows"
        wm = WorkflowManager(workflows_dir=workflows_dir)
        wm.save("my-workflow", SAMPLE_WORKFLOW_WITH_REQUIRED)
        workflow_path = Path(wm.get_path("my-workflow"))

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Enrich and create skill
        ir = wm.load_ir("my-workflow")
        enrich_workflow(workflow_path, "my-workflow", "First description", ir)
        create_skill_symlink(workflow_path, "my-workflow", "project", target="claude", project_dir=project_dir)

        # Mock Path.cwd() and WorkflowManager
        monkeypatch.setattr(Path, "cwd", lambda: project_dir)

        with patch(
            "pflow.core.skill_service.WorkflowManager",
            lambda workflows_dir=None: WorkflowManager(workflows_dir=workflows_dir or (tmp_path / "workflows")),
        ):
            # Re-enrich multiple times
            re_enrich_if_skill("my-workflow")
            re_enrich_if_skill("my-workflow")
            re_enrich_if_skill("my-workflow")

        # Verify only one ## Usage section
        content = workflow_path.read_text(encoding="utf-8")
        usage_count = content.count("## Usage")
        assert usage_count == 1, f"Expected 1 ## Usage section, found {usage_count}"

    def test_re_enrich_no_op_when_no_skill(self, tmp_path, monkeypatch):
        """Test that re-enrich does nothing when workflow has no skill."""
        from unittest.mock import patch

        from pflow.core.skill_service import re_enrich_if_skill

        workflows_dir = tmp_path / "workflows"
        wm = WorkflowManager(workflows_dir=workflows_dir)
        wm.save("my-workflow", SAMPLE_WORKFLOW_WITH_REQUIRED)
        workflow_path = Path(wm.get_path("my-workflow"))

        # Don't create any skill

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        monkeypatch.setattr(Path, "cwd", lambda: project_dir)

        # Get original content
        content_before = workflow_path.read_text(encoding="utf-8")

        with patch(
            "pflow.core.skill_service.WorkflowManager",
            lambda workflows_dir=None: WorkflowManager(workflows_dir=workflows_dir or (tmp_path / "workflows")),
        ):
            # Re-enrich should be a no-op
            re_enrich_if_skill("my-workflow")

        # Content should be unchanged
        content_after = workflow_path.read_text(encoding="utf-8")
        assert content_before == content_after
