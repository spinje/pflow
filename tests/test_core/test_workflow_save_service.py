"""Tests for workflow save service - shared business logic for CLI and MCP.

This module tests the core business logic extracted from CLI and MCP implementations.
These tests act as guardrails for AI refactoring by catching real bugs in:
1. Name validation logic (edge cases and security)
2. Multi-source workflow loading (dict/file/name resolution)
3. Force overwrite handling (delete-before-save pattern)
4. Metadata generation (LLM integration)
5. Draft deletion security (path traversal protection)

Critical: These tests validate BUSINESS LOGIC, not UI/UX behavior.
CLI tests validate command-line interface, these test the underlying functions.

Updated for Task 107: Markdown workflow format (.pflow.md). File loading uses
parse_markdown(), save uses markdown_content string instead of IR dict.
"""

from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from pflow.core.exceptions import WorkflowValidationError
from pflow.core.workflow_save_service import (
    RESERVED_WORKFLOW_NAMES,
    delete_draft_safely,
    generate_workflow_metadata,
    load_and_validate_workflow,
    save_workflow_with_options,
    validate_workflow_name,
)
from tests.shared.markdown_utils import ir_to_markdown, write_workflow_file


class TestValidateWorkflowName:
    """Test validate_workflow_name() - unified name validation.

    Prevents regression in unified validator that merges CLI (50 chars) and MCP (30 chars) rules.
    """

    def test_valid_simple_name(self) -> None:
        """REGRESSION GUARD: Simple valid names must pass.

        Bug prevented: Breaking basic functionality during validator refactoring.
        """
        # Note: "test" is reserved, so not in this list
        valid_names = ["myworkflow", "testing", "a", "workflow123", "my-workflow-v2"]

        for name in valid_names:
            is_valid, error = validate_workflow_name(name)
            assert is_valid, f"'{name}' should be valid, got error: {error}"
            assert error is None

    def test_reject_empty_name(self) -> None:
        """EMPTY STRING: Must reject empty workflow name.

        Bug prevented: Empty name could bypass validation, creating invisible workflows.
        """
        is_valid, error = validate_workflow_name("")
        assert not is_valid
        assert "cannot be empty" in error.lower()

    def test_reject_leading_hyphen(self) -> None:
        """PATTERN EDGE: Must reject names starting with hyphen.

        Bug prevented: `-workflow` could create hidden files in some filesystems.
        """
        is_valid, error = validate_workflow_name("-workflow")
        assert not is_valid
        assert "must start and end with alphanumeric" in error.lower()

    def test_reject_trailing_hyphen(self) -> None:
        """PATTERN EDGE: Must reject names ending with hyphen.

        Bug prevented: Trailing hyphens cause ambiguity in shell completion.
        """
        is_valid, error = validate_workflow_name("workflow-")
        assert not is_valid
        assert "must start and end with alphanumeric" in error.lower()

    def test_reject_consecutive_hyphens(self) -> None:
        """PATTERN EDGE: Must reject double hyphens (--).

        Bug prevented: Double hyphens look like CLI flags, cause confusion.
        """
        is_valid, error = validate_workflow_name("my--workflow")
        assert not is_valid
        assert "no consecutive hyphens" in error.lower()

    def test_reject_uppercase(self) -> None:
        """CASE SENSITIVITY: Must reject uppercase letters.

        Bug prevented: Case-insensitive filesystems could create collisions (My-workflow vs my-workflow).
        """
        is_valid, error = validate_workflow_name("MyWorkflow")
        assert not is_valid
        assert "lowercase" in error.lower()

    def test_reject_special_characters(self) -> None:
        """SECURITY: Must reject special characters (shell injection prevention).

        Bug prevented: Special chars like $, ;, |, & could enable shell injection.
        """
        invalid_chars = ["my_workflow", "my.workflow", "my$workflow", "my;workflow", "my|workflow"]

        for name in invalid_chars:
            is_valid, error = validate_workflow_name(name)
            assert not is_valid, f"'{name}' should be rejected but was accepted"
            assert "lowercase letters, numbers, and single hyphens" in error.lower()

    def test_reject_reserved_names_case_insensitive(self) -> None:
        """RESERVED NAMES: Must reject reserved names regardless of case.

        Bug prevented: "Test" could bypass check while "test" is reserved (case confusion).
        """
        # Test actual reserved names
        for reserved in RESERVED_WORKFLOW_NAMES:
            is_valid, error = validate_workflow_name(reserved)
            assert not is_valid, f"Reserved name '{reserved}' should be rejected"
            assert "reserved" in error.lower()

            # Test uppercase version
            is_valid, error = validate_workflow_name(reserved.upper())
            assert not is_valid, f"Reserved name '{reserved.upper()}' should be rejected (case insensitive)"
            assert "reserved" in error.lower()

    def test_max_length_boundary_50_chars(self) -> None:
        """LENGTH BOUNDARY: 50 chars exactly must pass, 51 must fail.

        Bug prevented: Off-by-one error in length check (CLI baseline is 50, not MCP's 30).
        Critical: This unifies CLI and MCP validators - must use CLI's 50 char limit.
        """
        # Exactly 50 characters (boundary case)
        name_50 = "a" * 50
        is_valid, error = validate_workflow_name(name_50)
        assert is_valid, "50 characters exactly should be valid (CLI baseline)"
        assert error is None

        # 51 characters (over limit)
        name_51 = "a" * 51
        is_valid, error = validate_workflow_name(name_51)
        assert not is_valid, "51 characters should be rejected"
        assert "50 characters" in error.lower()

    def test_numbers_at_start_allowed(self) -> None:
        """PATTERN FLEXIBILITY: Numbers at start of name are allowed.

        Bug prevented: Rejecting "2fa-workflow" when it's a valid pattern.
        """
        is_valid, error = validate_workflow_name("123workflow")
        assert is_valid
        assert error is None

        is_valid, error = validate_workflow_name("2fa-workflow")
        assert is_valid
        assert error is None


class TestLoadAndValidateWorkflow:
    """Test load_and_validate_workflow() - multi-source loading with validation.

    Prevents regression in workflow resolution order: dict → file → workflow name.
    """

    @pytest.fixture
    def sample_ir(self) -> dict[str, Any]:
        """Valid workflow IR for testing."""
        return {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo test"}}],
            "edges": [],
        }

    def test_load_from_dict_direct_ir(self, sample_ir: dict[str, Any]) -> None:
        """DICT SOURCE: Load from dict containing direct IR.

        Bug prevented: Dict input not recognized, forcing unnecessary file writes.
        """
        result = load_and_validate_workflow(sample_ir)

        assert result == sample_ir
        assert "ir_version" in result
        assert "nodes" in result

    def test_load_from_dict_metadata_wrapper(self, sample_ir: dict[str, Any]) -> None:
        """DICT SOURCE: Extract IR from metadata wrapper {"ir": {...}}.

        Bug prevented: CLI saves with metadata wrapper, MCP needs to extract IR from it.
        Critical: WorkflowManager.save() wraps IR, must extract correctly.
        """
        wrapped = {
            "name": "test",
            "description": "Test",
            "ir": sample_ir,
            "created_at": "2025-01-01T00:00:00Z",
        }

        result = load_and_validate_workflow(wrapped)

        assert result == sample_ir
        assert "ir" not in result  # Extracted IR, not wrapper
        assert "name" not in result  # Extracted IR, not wrapper

    def test_load_from_file_path(self, sample_ir: dict[str, Any], tmp_path: Path) -> None:
        """FILE SOURCE: Load from .pflow.md file path on filesystem.

        Bug prevented: File resolution broken, forcing workflow name lookups to fail.
        """
        file_path = tmp_path / "test.pflow.md"
        write_workflow_file(sample_ir, file_path)

        result = load_and_validate_workflow(str(file_path))

        assert result["nodes"][0]["id"] == "test"

    def test_load_from_workflow_name(self, sample_ir: dict[str, Any], tmp_path: Path) -> None:
        """NAME SOURCE: Load via WorkflowManager by name.

        Bug prevented: Name resolution broken, stored workflows inaccessible.
        """
        from pflow.core.workflow_manager import WorkflowManager

        # Temporarily use tmp_path as workflow directory
        with patch(
            "pflow.core.workflow_manager.WorkflowManager.__init__",
            lambda self: setattr(self, "workflows_dir", tmp_path),
        ):
            manager = WorkflowManager()
            markdown_content = ir_to_markdown(sample_ir)
            manager.save("test-workflow", markdown_content)

            result = load_and_validate_workflow("test-workflow")

            assert result["nodes"][0]["id"] == "test"

    def test_auto_normalize_adds_missing_fields(self) -> None:
        """AUTO-NORMALIZE: Add missing ir_version and edges fields.

        Bug prevented: Workflows without ir_version fail validation unnecessarily.
        Critical: This enables backwards compatibility with older workflows.
        """
        minimal_ir = {"nodes": [{"id": "test", "type": "shell", "params": {"command": "echo"}}]}

        result = load_and_validate_workflow(minimal_ir, auto_normalize=True)

        assert "ir_version" in result, "Should add missing ir_version"
        assert "edges" in result, "Should add missing edges"
        assert result["ir_version"] == "0.1.0"
        assert result["edges"] == []
        assert result["nodes"][0]["id"] == "test", "Should preserve original nodes"

    def test_auto_normalize_disabled(self) -> None:
        """AUTO-NORMALIZE OFF: Validation fails without normalization.

        Bug prevented: auto_normalize=False not respected, always normalizing.
        """
        minimal_ir = {"nodes": [{"id": "test", "type": "shell", "params": {"command": "echo"}}]}

        with pytest.raises((ValueError, WorkflowValidationError)):
            load_and_validate_workflow(minimal_ir, auto_normalize=False)

    def test_reject_invalid_markdown_in_file(self, tmp_path: Path) -> None:
        """FILE ERROR: Reject malformed markdown with clear error.

        Bug prevented: Parse errors surface as generic exceptions, no guidance.
        """
        file_path = tmp_path / "bad.pflow.md"
        file_path.write_text("This is not a valid workflow — no ## Steps section")

        assert file_path.exists(), "Test file should be created"

        with pytest.raises(ValueError, match=r"Invalid workflow|Missing"):
            load_and_validate_workflow(str(file_path))

    def test_reject_nonexistent_file(self) -> None:
        """FILE ERROR: Clear error for missing file.

        Bug prevented: Generic error when file doesn't exist, no suggestion about workflow names.
        """
        with pytest.raises(ValueError, match="not found"):
            load_and_validate_workflow("/nonexistent/file.pflow.md")

    def test_reject_nonexistent_workflow_name(self) -> None:
        """NAME ERROR: Clear error for missing workflow name.

        Bug prevented: Unclear which name was searched for, no suggestions.
        """
        with pytest.raises(ValueError, match="not found"):
            load_and_validate_workflow("nonexistent-workflow-name")

    def test_reject_invalid_workflow_structure(self) -> None:
        """VALIDATION: Reject IR with structural errors.

        Bug prevented: Invalid workflows pass through, fail later during execution.
        """
        invalid_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"type": "shell"}],  # Missing required 'id' field
            "edges": [],
        }

        with pytest.raises((ValueError, WorkflowValidationError)):
            load_and_validate_workflow(invalid_ir)

    def test_reject_invalid_output_sources(self, tmp_path: Path) -> None:
        """SEMANTIC VALIDATION: Reject workflows with invalid output sources.

        Bug prevented: Workflows with invalid output.source fields pass validation,
        get saved to library, then fail at runtime with cryptic errors.

        This is an INTEGRATION test ensuring WorkflowValidator.validate() is called
        during workflow save, not just structural IR validation.

        Critical: This test would have caught the bug where only validate_ir() was
        called but not WorkflowValidator.validate() in the save service.
        """
        invalid_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "reader", "type": "read-file", "params": {"file_path": "test.txt"}}],
            "edges": [],
            "outputs": {
                "content": {
                    "source": "nonexistent_node.output",
                    "description": "Content from a nonexistent node",
                }
            },
        }

        file_path = tmp_path / "invalid_output.pflow.md"
        write_workflow_file(invalid_ir, file_path)

        # Should reject due to output source validation
        with pytest.raises(WorkflowValidationError, match="nonexistent_node"):
            load_and_validate_workflow(str(file_path))

    def test_accept_valid_output_sources(self, tmp_path: Path) -> None:
        """SEMANTIC VALIDATION: Accept workflows with valid output sources.

        Bug prevented: Over-aggressive validation rejecting valid output references.

        This ensures the output source validation doesn't have false positives.
        """
        valid_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "reader", "type": "read-file", "params": {"file_path": "test.txt"}},
                {"id": "processor", "type": "llm", "params": {"prompt": "analyze"}},
            ],
            "edges": [{"from": "reader", "to": "processor"}],
            "outputs": {
                "content": {
                    "source": "reader.content",
                    "description": "Raw file content",
                },
                "analysis": {
                    "source": "processor.response",
                    "description": "LLM analysis result",
                },
                "raw": {
                    "source": "reader",
                    "description": "Full reader output",
                },
            },
        }

        file_path = tmp_path / "valid_output.pflow.md"
        write_workflow_file(valid_ir, file_path)

        # Should accept without error
        result = load_and_validate_workflow(str(file_path))
        assert result is not None
        assert len(result["outputs"]) == 3


class TestSaveWorkflowWithOptions:
    """Test save_workflow_with_options() - save with force overwrite handling.

    Prevents regression in delete-before-save pattern and force flag behavior.
    """

    @pytest.fixture
    def sample_ir(self) -> dict[str, Any]:
        """Valid workflow IR for testing."""
        return {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo test"}}],
            "edges": [],
        }

    def test_save_new_workflow_without_force(self, sample_ir: dict[str, Any], tmp_path: Path) -> None:
        """SAVE NEW: Save non-existent workflow (normal case).

        Bug prevented: Force flag required even for new workflows.
        """
        markdown_content = ir_to_markdown(sample_ir)

        # Mock WorkflowManager to use tmp_path
        with patch("pflow.core.workflow_save_service.WorkflowManager") as mock_wm_class:
            mock_wm = Mock()
            mock_wm.exists.return_value = False
            mock_wm.save.return_value = str(tmp_path / "new-workflow.pflow.md")
            mock_wm_class.return_value = mock_wm

            path = save_workflow_with_options("new-workflow", markdown_content, force=False)

            mock_wm.exists.assert_called_once_with("new-workflow")
            mock_wm.save.assert_called_once_with("new-workflow", markdown_content, None)
            mock_wm.delete.assert_not_called()
            assert path == Path(str(tmp_path / "new-workflow.pflow.md"))

    def test_save_existing_with_force_deletes_first(self, sample_ir: dict[str, Any], tmp_path: Path) -> None:
        """FORCE OVERWRITE: Must delete existing before saving.

        Bug prevented: Force flag doesn't delete, causing WorkflowManager to reject save.
        Critical: WorkflowManager.save() raises if file exists - MUST delete first.
        """
        markdown_content = ir_to_markdown(sample_ir)

        # Mock WorkflowManager
        with patch("pflow.core.workflow_save_service.WorkflowManager") as mock_wm_class:
            mock_wm = Mock()
            mock_wm.exists.return_value = True
            mock_wm.save.return_value = str(tmp_path / "existing.pflow.md")
            mock_wm_class.return_value = mock_wm

            path = save_workflow_with_options("existing", markdown_content, force=True)

            # Verify delete was called before save
            mock_wm.delete.assert_called_once_with("existing")
            mock_wm.save.assert_called_once_with("existing", markdown_content, None)
            assert path == Path(str(tmp_path / "existing.pflow.md"))

    def test_save_existing_without_force_raises(self, sample_ir: dict[str, Any], tmp_path: Path) -> None:
        """OVERWRITE PROTECTION: Reject overwrite without force flag.

        Bug prevented: Silent overwrite of existing workflows, data loss risk.
        """
        markdown_content = ir_to_markdown(sample_ir)

        # Mock WorkflowManager to simulate existing workflow
        with patch("pflow.core.workflow_save_service.WorkflowManager") as mock_wm_class:
            mock_wm = Mock()
            mock_wm.exists.return_value = True  # Workflow already exists
            mock_wm_class.return_value = mock_wm

            # Try to save without force - should fail
            with pytest.raises(FileExistsError, match="already exists"):
                save_workflow_with_options("existing", markdown_content, force=False)

            # Verify existence was checked
            mock_wm.exists.assert_called_once_with("existing")
            # Verify delete was NOT called (no force)
            mock_wm.delete.assert_not_called()
            # Verify save was NOT called (rejected before save)
            mock_wm.save.assert_not_called()

    def test_save_with_metadata(self, sample_ir: dict[str, Any], tmp_path: Path) -> None:
        """METADATA: Pass metadata to WorkflowManager.save().

        Bug prevented: Metadata parameter ignored, CLI-generated metadata lost.
        """
        markdown_content = ir_to_markdown(sample_ir)
        metadata = {"keywords": ["test"], "capabilities": ["testing"]}

        # Mock WorkflowManager
        with patch("pflow.core.workflow_save_service.WorkflowManager") as mock_wm_class:
            mock_wm = Mock()
            mock_wm.exists.return_value = False
            mock_wm.save.return_value = str(tmp_path / "with-metadata.pflow.md")
            mock_wm_class.return_value = mock_wm

            path = save_workflow_with_options("with-metadata", markdown_content, metadata=metadata)

            # Verify metadata was passed to save()
            mock_wm.save.assert_called_once_with("with-metadata", markdown_content, metadata)
            assert path == Path(str(tmp_path / "with-metadata.pflow.md"))

    def test_delete_failure_raises_clear_error(self, sample_ir: dict[str, Any], tmp_path: Path) -> None:
        """DELETE ERROR: Clear error when delete fails during force overwrite.

        Bug prevented: Delete failure surfaces as generic error, unclear which workflow.
        """
        markdown_content = ir_to_markdown(sample_ir)

        # Mock WorkflowManager with delete failure
        with patch("pflow.core.workflow_save_service.WorkflowManager") as mock_wm_class:
            mock_wm = Mock()
            mock_wm.exists.return_value = True
            mock_wm.delete.side_effect = Exception("Disk full")
            mock_wm_class.return_value = mock_wm

            with pytest.raises(WorkflowValidationError, match="Failed to delete"):
                save_workflow_with_options("existing", markdown_content, force=True)

    def test_re_enriches_skill_after_save(self, sample_ir: dict[str, Any], tmp_path: Path) -> None:
        """SKILL RE-ENRICHMENT: Calls re_enrich_if_skill after successful save.

        Bug prevented: Workflow published as skill loses enrichment after save --force.
        Task 119: The re-enrichment hook restores name/description frontmatter and ## Usage section.
        """
        markdown_content = ir_to_markdown(sample_ir)

        with (
            patch("pflow.core.workflow_save_service.WorkflowManager") as mock_wm_class,
            patch("pflow.core.skill_service.re_enrich_if_skill") as mock_re_enrich,
        ):
            mock_wm = Mock()
            mock_wm.exists.return_value = False
            mock_wm.save.return_value = str(tmp_path / "my-workflow.pflow.md")
            mock_wm_class.return_value = mock_wm

            save_workflow_with_options("my-workflow", markdown_content, force=False)

            # Verify re-enrich was called with workflow name
            mock_re_enrich.assert_called_once_with("my-workflow")

    def test_re_enrich_failure_does_not_fail_save(self, sample_ir: dict[str, Any], tmp_path: Path) -> None:
        """SKILL RE-ENRICHMENT ERROR: Re-enrichment failure doesn't block save.

        Bug prevented: Skill enrichment failure causes entire save to fail.
        Critical: Enrichment is best-effort, save must succeed regardless.
        """
        markdown_content = ir_to_markdown(sample_ir)

        with (
            patch("pflow.core.workflow_save_service.WorkflowManager") as mock_wm_class,
            patch("pflow.core.skill_service.re_enrich_if_skill") as mock_re_enrich,
        ):
            mock_wm = Mock()
            mock_wm.exists.return_value = False
            mock_wm.save.return_value = str(tmp_path / "my-workflow.pflow.md")
            mock_wm_class.return_value = mock_wm

            # Make re-enrichment fail
            mock_re_enrich.side_effect = Exception("Enrichment failed")

            # Save should still succeed
            path = save_workflow_with_options("my-workflow", markdown_content, force=False)

            assert path == Path(str(tmp_path / "my-workflow.pflow.md"))


class TestGenerateWorkflowMetadata:
    """Test generate_workflow_metadata() - LLM-based metadata generation.

    Prevents regression in metadata generation integration (CLI-only feature).
    """

    def test_successful_metadata_generation(self) -> None:
        """LLM SUCCESS: Generate metadata successfully.

        Bug prevented: Metadata generation broken, CLI --generate-metadata flag useless.
        """
        sample_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo test"}}],
            "edges": [],
        }

        expected_metadata = {
            "keywords": ["shell", "command", "echo"],
            "capabilities": ["Execute shell commands"],
            "typical_use_cases": ["Run system commands"],
        }

        # Mock MetadataGenerationNode where it's imported (lazy import inside function)
        with patch("pflow.planning.nodes.MetadataGenerationNode") as mock_node_class:
            mock_node = Mock()
            mock_node_class.return_value = mock_node

            # Simulate node populating shared store
            def mock_run(shared):
                shared["workflow_metadata"] = expected_metadata

            mock_node.run.side_effect = mock_run

            result = generate_workflow_metadata(sample_ir)

            assert result == expected_metadata
            assert "keywords" in result
            assert "capabilities" in result

    def test_returns_none_on_failure(self) -> None:
        """LLM FAILURE: Return None gracefully on error (no crash).

        Bug prevented: Metadata generation failure crashes entire save operation.
        Critical: Metadata is optional, failures must not block saves.
        """
        sample_ir = {"ir_version": "0.1.0", "nodes": [], "edges": []}

        # Mock MetadataGenerationNode to raise exception (lazy import location)
        with patch("pflow.planning.nodes.MetadataGenerationNode", side_effect=Exception("LLM API error")):
            result = generate_workflow_metadata(sample_ir)

            assert result is None, "Should return None on failure, not crash"

    def test_returns_none_on_empty_metadata(self) -> None:
        """LLM EMPTY: Return None if node doesn't populate workflow_metadata.

        Bug prevented: Empty metadata dict saved instead of None, causes downstream issues.
        """
        sample_ir = {"ir_version": "0.1.0", "nodes": [], "edges": []}

        # Mock at lazy import location
        with patch("pflow.planning.nodes.MetadataGenerationNode") as mock_node_class:
            mock_node = Mock()
            mock_node_class.return_value = mock_node

            # Node runs but doesn't set workflow_metadata
            mock_node.run.return_value = None

            result = generate_workflow_metadata(sample_ir)

            assert result is None


class TestDeleteDraftSafely:
    """Test delete_draft_safely() - security-aware draft deletion.

    Prevents regression in path traversal protection and symlink security.
    """

    def test_delete_in_home_pflow_workflows(self, tmp_path: Path) -> None:
        """SAFE DELETE: Delete file in home .pflow/workflows/.

        Bug prevented: Safe directories not recognized, legitimate deletions blocked.
        """
        # Simulate home directory
        home_dir = tmp_path / "home"
        pflow_dir = home_dir / ".pflow" / "workflows"
        pflow_dir.mkdir(parents=True)

        draft = pflow_dir / "draft.json"
        draft.write_text("{}")

        assert draft.exists(), "Draft file should exist before deletion"

        with patch("pflow.core.workflow_save_service.Path.home", return_value=home_dir):
            result = delete_draft_safely(str(draft))

            assert result is True, "Should successfully delete file in safe directory"
            assert not draft.exists(), "Draft file should be deleted"

    def test_delete_in_cwd_pflow_workflows(self, tmp_path: Path) -> None:
        """SAFE DELETE: Delete file in cwd .pflow/workflows/.

        Bug prevented: CWD .pflow/workflows not recognized as safe, project drafts can't be deleted.
        """
        pflow_dir = tmp_path / ".pflow" / "workflows"
        pflow_dir.mkdir(parents=True)

        draft = pflow_dir / "draft.json"
        draft.write_text("{}")

        assert draft.exists(), "Draft file should exist before deletion"

        with patch("pflow.core.workflow_save_service.Path.cwd", return_value=tmp_path):
            result = delete_draft_safely(str(draft))

            assert result is True, "Should successfully delete file in safe directory"
            assert not draft.exists(), "Draft file should be deleted"

    def test_refuse_delete_outside_safe_directories(self, tmp_path: Path) -> None:
        """SECURITY: Refuse to delete files outside .pflow/workflows/.

        Bug prevented: Path traversal allows deleting arbitrary user files.
        Critical: Prevents accidental deletion of important files (~/Documents, etc.).
        """
        unsafe_file = tmp_path / "important.json"
        unsafe_file.write_text("{}")

        with patch("pflow.core.workflow_save_service.Path.home", return_value=tmp_path):
            result = delete_draft_safely(str(unsafe_file))

            assert result is False
            assert unsafe_file.exists(), "File outside safe dir should NOT be deleted"

    def test_refuse_delete_symlinks(self, tmp_path: Path) -> None:
        """SECURITY: Refuse to delete symlinks (defense in depth).

        Bug prevented: Symlink manipulation could delete files outside safe dirs via link.
        Critical: Attacker could symlink ~/important.txt → .pflow/workflows/draft.json.
        """
        pflow_dir = tmp_path / ".pflow" / "workflows"
        pflow_dir.mkdir(parents=True)

        # Create target file outside safe dir
        target = tmp_path / "target.json"
        target.write_text("{}")

        # Create symlink inside safe dir pointing to target
        symlink = pflow_dir / "draft.json"
        symlink.symlink_to(target)

        with patch("pflow.core.workflow_save_service.Path.home", return_value=tmp_path):
            result = delete_draft_safely(str(symlink))

            assert result is False
            assert symlink.exists(), "Symlink should NOT be deleted"
            assert target.exists(), "Target file should be safe"

    def test_path_traversal_protection(self, tmp_path: Path) -> None:
        """SECURITY: Block path traversal attacks (../../etc/passwd).

        Bug prevented: Attacker uses ../ to escape safe directory and delete system files.
        Critical: is_relative_to() check prevents directory escape.
        """
        home_dir = tmp_path / "home"
        pflow_dir = home_dir / ".pflow" / "workflows"
        pflow_dir.mkdir(parents=True)

        # Try to delete file outside via path traversal
        target = tmp_path / "secret.txt"
        target.write_text("important data")

        # Create traversal path: .pflow/workflows/../../secret.txt
        traversal_path = str(pflow_dir / ".." / ".." / ".." / "secret.txt")

        with patch("pflow.core.workflow_save_service.Path.home", return_value=home_dir):
            result = delete_draft_safely(traversal_path)

            assert result is False
            assert target.exists(), "Path traversal should be blocked"

    def test_handle_deletion_failure_gracefully(self, tmp_path: Path) -> None:
        """ERROR HANDLING: Return False on deletion failure (no crash).

        Bug prevented: Permission errors or locked files crash the save operation.
        """
        home_dir = tmp_path
        pflow_dir = home_dir / ".pflow" / "workflows"
        pflow_dir.mkdir(parents=True)

        draft = pflow_dir / "draft.json"
        draft.write_text("{}")

        assert draft.exists(), "Draft file should exist before deletion attempt"

        with (
            patch("pflow.core.workflow_save_service.Path.home", return_value=home_dir),
            patch.object(Path, "unlink", side_effect=PermissionError("Access denied")),
        ):
            result = delete_draft_safely(str(draft))

            assert result is False, "Should return False on deletion failure, not crash"

    def test_handle_invalid_path_gracefully(self) -> None:
        """ERROR HANDLING: Return False for invalid paths (no crash).

        Bug prevented: Invalid paths crash the save operation.
        """
        result = delete_draft_safely("/path/with/\x00/null/byte.json")

        assert result is False, "Should handle invalid paths gracefully"
