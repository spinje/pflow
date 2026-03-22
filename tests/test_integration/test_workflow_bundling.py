"""Integration tests for workflow bundling on save.

Tests the full end-to-end flow: create a workflow with file dependencies,
save it via WorkflowManager, verify the bundle contains all dependency files,
and verify the saved workflow can be loaded back.
"""

from pathlib import Path
from typing import Any

import pytest

from pflow.core.workflow.dependency_discovery import discover_dependencies
from pflow.core.workflow.manager import WorkflowManager
from pflow.core.workflow.save_service import save_workflow_with_options
from tests.shared.markdown_utils import ir_to_markdown


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a project directory simulating a user's workspace."""
    d = tmp_path / "project"
    d.mkdir()
    return d


@pytest.fixture
def workflows_dir(tmp_path: Path) -> Path:
    """Create an isolated workflows directory for saving."""
    d = tmp_path / "saved-workflows"
    return d  # WorkflowManager.save() creates it


def _make_manager(workflows_dir: Path) -> WorkflowManager:
    """Create a WorkflowManager pointed at an explicit temp directory."""
    return WorkflowManager(workflows_dir=workflows_dir)


def _discover_and_save(
    wm: WorkflowManager,
    name: str,
    ir: dict,
    markdown: str,
    base_dir: Path,
) -> Path:
    """Helper: discover deps from IR, then save with bundling.

    Uses the same relative_to() path computation as the production code
    in save_service.py:_discover_and_bundle_deps().

    Returns the bundle directory (workflows_dir / name).
    """
    parent_base = base_dir.resolve()
    deps = discover_dependencies(ir, parent_base)
    dependencies: list[tuple[str, Path]] = []
    for dep in deps:
        try:
            rel = str(dep.absolute_path.relative_to(parent_base))
        except ValueError:
            rel = dep.relative_path
        dependencies.append((rel, dep.absolute_path))
    wm.save(name, markdown, dependencies=dependencies)
    return wm.workflows_dir / name


class TestSaveBundlesFileReferences:
    """Verify that file references in node params are bundled."""

    def test_save_bundles_prompt_file_reference(self, project_dir: Path, workflows_dir: Path) -> None:
        """When a workflow has `prompt: ./prompts/foo.md`, saving bundles it."""
        # Arrange: create prompt file on disk
        prompts_dir = project_dir / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "foo.md").write_text("You are a helpful assistant")

        ir = {
            "nodes": [
                {
                    "id": "ask",
                    "type": "llm",
                    "params": {"prompt": "./prompts/foo.md", "model": "test-model"},
                }
            ],
            "edges": [],
        }
        markdown = ir_to_markdown(ir, title="Prompt Workflow")

        # Act
        wm = _make_manager(workflows_dir)
        bundle_dir = _discover_and_save(wm, "prompt-wf", ir, markdown, project_dir)

        # Assert: entry point exists
        assert (bundle_dir / "prompt-wf.pflow.md").exists()

        # Assert: dependency file is bundled preserving relative path
        assert (bundle_dir / "prompts" / "foo.md").exists()
        assert (bundle_dir / "prompts" / "foo.md").read_text() == "You are a helpful assistant"


class TestSaveBundlesSubWorkflows:
    """Verify that sub-workflow file references are bundled."""

    def test_save_bundles_sub_workflow(self, project_dir: Path, workflows_dir: Path) -> None:
        """When a workflow has `workflow: ./sub.pflow.md`, saving bundles it."""
        # Arrange: create sub-workflow file
        sub_ir = {
            "nodes": [
                {
                    "id": "step1",
                    "type": "shell",
                    "params": {"command": "echo sub-output"},
                }
            ],
            "edges": [],
        }
        sub_path = project_dir / "sub.pflow.md"
        sub_path.write_text(ir_to_markdown(sub_ir, title="Sub Workflow"))

        parent_ir = {
            "nodes": [
                {
                    "id": "run-sub",
                    "type": "workflow",
                    "params": {"workflow": "./sub.pflow.md"},
                }
            ],
            "edges": [],
        }
        markdown = ir_to_markdown(parent_ir, title="Parent Workflow")

        # Act
        wm = _make_manager(workflows_dir)
        bundle_dir = _discover_and_save(wm, "parent-wf", parent_ir, markdown, project_dir)

        # Assert
        assert (bundle_dir / "parent-wf.pflow.md").exists()
        assert (bundle_dir / "sub.pflow.md").exists()
        # Verify the sub-workflow content is intact
        sub_content = (bundle_dir / "sub.pflow.md").read_text()
        assert "step1" in sub_content


class TestSavePreservesRelativeStructure:
    """Verify directory structure is preserved in the bundle."""

    def test_multiple_nested_directories_preserved(self, project_dir: Path, workflows_dir: Path) -> None:
        """Files in different subdirs keep their relative paths in the bundle."""
        # Arrange: create files in two different subdirectories
        (project_dir / "prompts").mkdir()
        (project_dir / "prompts" / "system.md").write_text("System prompt content")

        (project_dir / "scripts").mkdir()
        (project_dir / "scripts" / "helper.py").write_text("print('hello')")

        ir = {
            "nodes": [
                {
                    "id": "llm-step",
                    "type": "llm",
                    "params": {
                        "prompt": "./prompts/system.md",
                        "model": "test-model",
                    },
                },
                {
                    "id": "code-step",
                    "type": "python",
                    "params": {"code": "./scripts/helper.py"},
                },
            ],
            "edges": [{"from": "llm-step", "to": "code-step"}],
        }
        markdown = ir_to_markdown(ir, title="Multi-Dep Workflow")

        # Act
        wm = _make_manager(workflows_dir)
        bundle_dir = _discover_and_save(wm, "multi-dep", ir, markdown, project_dir)

        # Assert: directory structure is preserved
        assert (bundle_dir / "prompts" / "system.md").exists()
        assert (bundle_dir / "scripts" / "helper.py").exists()

        # Verify file contents
        assert (bundle_dir / "prompts" / "system.md").read_text() == "System prompt content"
        assert (bundle_dir / "scripts" / "helper.py").read_text() == "print('hello')"


class TestSavedWorkflowLoadsCorrectly:
    """Verify a bundled workflow can be loaded back."""

    def test_load_returns_valid_ir(self, project_dir: Path, workflows_dir: Path) -> None:
        """After saving with deps, load() returns the full metadata with valid IR."""
        # Arrange
        (project_dir / "prompts").mkdir()
        (project_dir / "prompts" / "sys.md").write_text("Be concise.")

        ir = {
            "nodes": [
                {
                    "id": "ask",
                    "type": "llm",
                    "params": {"prompt": "./prompts/sys.md", "model": "test-model"},
                }
            ],
            "edges": [],
        }
        markdown = ir_to_markdown(ir, title="Loadable Workflow")

        wm = _make_manager(workflows_dir)
        _discover_and_save(wm, "loadable-wf", ir, markdown, project_dir)

        # Act: load via WorkflowManager
        loaded = wm.load("loadable-wf")

        # Assert: IR is structurally valid
        assert "ir" in loaded
        loaded_ir = loaded["ir"]
        assert len(loaded_ir["nodes"]) == 1
        assert loaded_ir["nodes"][0]["id"] == "ask"
        assert loaded_ir["nodes"][0]["type"] == "llm"
        assert loaded_ir["nodes"][0]["params"]["prompt"] == "./prompts/sys.md"

        # Assert: metadata fields present
        assert loaded.get("created_at") is not None
        assert loaded.get("version") == "1.0.0"


class TestForceSaveReplacesEntireBundle:
    """Verify force-save replaces the entire bundle directory."""

    def test_force_save_removes_old_deps_adds_new(self, project_dir: Path, workflows_dir: Path) -> None:
        """Force-saving v2 removes dep A from v1 and adds dep B."""
        wm = _make_manager(workflows_dir)

        # --- Save v1 with dep A ---
        (project_dir / "prompts").mkdir(exist_ok=True)
        (project_dir / "prompts" / "v1-prompt.md").write_text("Version 1 prompt")

        ir_v1 = {
            "nodes": [
                {
                    "id": "ask",
                    "type": "llm",
                    "params": {
                        "prompt": "./prompts/v1-prompt.md",
                        "model": "test-model",
                    },
                }
            ],
            "edges": [],
        }
        md_v1 = ir_to_markdown(ir_v1, title="Workflow V1")
        _discover_and_save(wm, "force-test", ir_v1, md_v1, project_dir)

        bundle_dir = wm.workflows_dir / "force-test"
        assert (bundle_dir / "prompts" / "v1-prompt.md").exists()

        # --- Force-save v2 with dep B (no dep A) ---
        (project_dir / "scripts").mkdir(exist_ok=True)
        (project_dir / "scripts" / "v2-code.py").write_text("print('v2')")

        ir_v2 = {
            "nodes": [
                {
                    "id": "run",
                    "type": "python",
                    "params": {"code": "./scripts/v2-code.py"},
                }
            ],
            "edges": [],
        }
        md_v2 = ir_to_markdown(ir_v2, title="Workflow V2")

        # Delete the old bundle to simulate force-save
        wm.delete("force-test")
        _discover_and_save(wm, "force-test", ir_v2, md_v2, project_dir)

        # Assert: old dep A is gone
        assert not (bundle_dir / "prompts" / "v1-prompt.md").exists()

        # Assert: new dep B exists
        assert (bundle_dir / "scripts" / "v2-code.py").exists()
        assert (bundle_dir / "scripts" / "v2-code.py").read_text() == "print('v2')"

        # Assert: entry point updated
        entry = (bundle_dir / "force-test.pflow.md").read_text()
        assert "run" in entry  # v2 node id


class TestSaveNoDependencies:
    """Verify saving a workflow with no file refs produces a clean folder."""

    def test_bundle_contains_only_entry_point(
        self,
        workflows_dir: Path,
    ) -> None:
        """A workflow with no file refs creates a folder with just the entry point."""
        ir = {
            "nodes": [
                {
                    "id": "greet",
                    "type": "shell",
                    "params": {"command": "echo hello"},
                }
            ],
            "edges": [],
        }
        markdown = ir_to_markdown(ir, title="Simple Workflow")

        wm = _make_manager(workflows_dir)
        wm.save("simple-wf", markdown)

        bundle_dir = wm.workflows_dir / "simple-wf"
        # Only the entry point file should exist
        all_files = list(bundle_dir.rglob("*"))
        regular_files = [f for f in all_files if f.is_file()]
        assert len(regular_files) == 1
        assert regular_files[0].name == "simple-wf.pflow.md"


class TestSaveWorkflowWithOptionsBundles:
    """Verify save_workflow_with_options() performs dependency discovery and bundling."""

    def test_service_layer_discovers_and_bundles(self, project_dir: Path, tmp_path: Path) -> None:
        """save_workflow_with_options() with source_path discovers deps and returns bundled list."""
        # Arrange
        (project_dir / "prompts").mkdir()
        (project_dir / "prompts" / "agent.md").write_text("You are a coding assistant")

        ir = {
            "nodes": [
                {
                    "id": "ask",
                    "type": "llm",
                    "params": {"prompt": "./prompts/agent.md", "model": "test-model"},
                }
            ],
            "edges": [],
        }
        workflow_path = project_dir / "bundle-test.pflow.md"
        markdown = ir_to_markdown(ir, title="Bundle Test")
        workflow_path.write_text(markdown)

        # Act: use the service-layer function with an explicit WorkflowManager path
        # save_workflow_with_options uses WorkflowManager() with default path,
        # which is patched by isolate_pflow_config to use a temp dir.
        saved_path, bundled_files = save_workflow_with_options(
            name="bundle-svc",
            markdown_content=markdown,
            source_path=workflow_path,
        )

        # Assert: saved path exists
        assert saved_path.exists()

        # Assert: bundled_files list includes the discovered dependency
        assert len(bundled_files) >= 1
        assert any("prompts/agent.md" in f for f in bundled_files)

        # Assert: the actual bundled file exists on disk alongside the entry point
        bundle_dir = saved_path.parent
        assert (bundle_dir / "prompts" / "agent.md").exists()
        assert (bundle_dir / "prompts" / "agent.md").read_text() == "You are a coding assistant"

    def test_service_layer_no_source_path_no_bundling(
        self,
        tmp_path: Path,
    ) -> None:
        """save_workflow_with_options() without source_path skips dependency discovery."""
        ir = {
            "nodes": [
                {
                    "id": "greet",
                    "type": "shell",
                    "params": {"command": "echo hi"},
                }
            ],
            "edges": [],
        }
        markdown = ir_to_markdown(ir, title="No Source Workflow")

        saved_path, bundled_files = save_workflow_with_options(
            name="no-source",
            markdown_content=markdown,
        )

        assert saved_path.exists()
        assert bundled_files == []


class TestFileReferencesResolveFromBundle:
    """Verify the critical chain: save → load → resolve_file_references from bundle dir.

    This is the core guarantee of bundling — file references in a saved workflow
    must resolve from the bundle directory, not from the original project.
    """

    def test_file_ref_resolves_from_saved_bundle(self, project_dir: Path, workflows_dir: Path) -> None:
        """File reference in a saved workflow resolves content from the bundle directory.

        Tests the chain: save with bundled files → load IR → resolve_file_references
        using get_path().parent as base_dir → file content substituted from bundle.
        """
        from pflow.core.file_resolver import resolve_file_references

        # Arrange: create a project with a prompt file
        (project_dir / "prompts").mkdir()
        (project_dir / "prompts" / "system.md").write_text("You are a test assistant")

        ir: dict[str, Any] = {
            "nodes": [
                {
                    "id": "ask",
                    "type": "llm",
                    "params": {"prompt": "./prompts/system.md", "model": "test-model"},
                }
            ],
            "edges": [],
        }
        markdown = ir_to_markdown(ir, title="Resolvable Workflow")

        # Act: save with bundling
        wm = _make_manager(workflows_dir)
        _discover_and_save(wm, "resolve-test", ir, markdown, project_dir)

        # Now simulate what happens at execution time:
        # 1. Load the IR from the saved workflow
        loaded_ir = wm.load_ir("resolve-test")

        # 2. Derive base_dir the same way the runtime does:
        #    base_dir = Path(wm.get_path(name)).parent
        base_dir = Path(wm.get_path("resolve-test")).parent

        # 3. Resolve file references (this is what compile_ir_to_flow does)
        resolve_file_references(loaded_ir, base_dir)

        # Assert: the file content was substituted into the IR
        resolved_prompt = loaded_ir["nodes"][0]["params"]["prompt"]
        assert resolved_prompt == "You are a test assistant"

    def test_sub_workflow_in_subdir_with_own_file_refs(self, project_dir: Path, workflows_dir: Path) -> None:
        """Sub-workflow in a subdirectory has its own file refs — all land at correct paths.

        Project structure:
            project/
            ├── parent.pflow.md         # references ./sub/child.pflow.md
            └── sub/
                ├── child.pflow.md      # references ./data/prompt.md
                └── data/
                    └── prompt.md

        Bundle must have:
            nested-test/
            ├── nested-test.pflow.md
            ├── sub/
            │   ├── child.pflow.md
            │   └── data/
            │       └── prompt.md
        """
        from pflow.core.file_resolver import resolve_file_references
        from pflow.core.markdown_parser import parse_markdown as pm

        # Arrange: create nested project structure
        sub_dir = project_dir / "sub"
        sub_dir.mkdir()
        data_dir = sub_dir / "data"
        data_dir.mkdir()
        (data_dir / "prompt.md").write_text("Nested prompt content")

        # Child workflow references ./data/prompt.md (relative to itself)
        child_ir: dict[str, Any] = {
            "nodes": [
                {
                    "id": "child-step",
                    "type": "llm",
                    "params": {"prompt": "./data/prompt.md", "model": "test-model"},
                }
            ],
            "edges": [],
        }
        (sub_dir / "child.pflow.md").write_text(ir_to_markdown(child_ir, title="Child Workflow"))

        # Parent workflow references the child by relative path
        parent_ir: dict[str, Any] = {
            "nodes": [
                {
                    "id": "run-child",
                    "type": "workflow",
                    "params": {"workflow": "./sub/child.pflow.md"},
                }
            ],
            "edges": [],
        }
        parent_markdown = ir_to_markdown(parent_ir, title="Parent Workflow")

        # Act: discover deps and save (using explicit workflows_dir)
        wm = _make_manager(workflows_dir)
        parent_base = project_dir.resolve()
        deps = discover_dependencies(parent_ir, parent_base)

        # Compute bundle-relative paths (same logic as save_service.py)
        dependencies = []
        for dep in deps:
            try:
                rel = str(dep.absolute_path.relative_to(parent_base))
            except ValueError:
                rel = dep.relative_path
            dependencies.append((rel, dep.absolute_path))

        bundled_files = [rel for rel, _ in dependencies]
        wm.save("nested-test", parent_markdown, dependencies=dependencies)

        bundle_dir = wm.workflows_dir / "nested-test"

        # Assert: child workflow is at correct relative path
        assert (bundle_dir / "sub" / "child.pflow.md").exists()

        # Assert: child's file reference is at correct relative path
        # (relative to the child's location in the bundle)
        assert (bundle_dir / "sub" / "data" / "prompt.md").exists()
        assert (bundle_dir / "sub" / "data" / "prompt.md").read_text() == "Nested prompt content"

        # Assert: bundled_files list shows paths relative to bundle root
        assert "sub/child.pflow.md" in bundled_files
        assert "sub/data/prompt.md" in bundled_files

        # Verify the child's file ref resolves correctly at runtime:
        # child is at bundle/sub/child.pflow.md, its base_dir = bundle/sub/
        # ./data/prompt.md resolves to bundle/sub/data/prompt.md
        child_content = (bundle_dir / "sub" / "child.pflow.md").read_text()
        child_parsed = pm(child_content)
        child_base = bundle_dir / "sub"
        resolve_file_references(child_parsed.ir, child_base)
        assert child_parsed.ir["nodes"][0]["params"]["prompt"] == "Nested prompt content"

    def test_file_ref_resolves_via_service_layer(
        self,
        project_dir: Path,
    ) -> None:
        """End-to-end via save_workflow_with_options: save → load → resolve from bundle."""
        from pflow.core.file_resolver import resolve_file_references

        # Arrange
        (project_dir / "scripts").mkdir()
        (project_dir / "scripts" / "setup.sh").write_text("#!/bin/bash\necho setup")

        ir: dict[str, Any] = {
            "nodes": [
                {
                    "id": "setup",
                    "type": "shell",
                    "params": {"command": "./scripts/setup.sh"},
                }
            ],
            "edges": [],
        }
        markdown = ir_to_markdown(ir, title="Script Workflow")
        workflow_path = project_dir / "my-workflow.pflow.md"
        workflow_path.write_text(markdown)

        # Act: save via service layer (uses isolate_pflow_config temp dir)
        _saved_path, _bundled_files = save_workflow_with_options(
            name="script-resolve",
            markdown_content=markdown,
            source_path=workflow_path,
        )

        # Verify: load and resolve from the bundle
        wm = WorkflowManager()
        loaded_ir = wm.load_ir("script-resolve")
        base_dir = Path(wm.get_path("script-resolve")).parent
        resolve_file_references(loaded_ir, base_dir)

        assert loaded_ir["nodes"][0]["params"]["command"] == "#!/bin/bash\necho setup"


class TestRawContentSaveGuard:
    """Verify that raw-content saves (no source path) are rejected when they contain file refs."""

    def test_raw_content_with_sub_workflow_ref_rejected(self) -> None:
        """MCP-style save of raw markdown with sub-workflow file ref is rejected.

        Regression: has_file_references() only checked FILE_RESOLVABLE_PARAMS,
        missing workflow params. A workflow with only sub-workflow file refs
        would silently save without bundling, producing a broken workflow.
        """
        from pflow.core.exceptions import WorkflowValidationError

        ir: dict[str, Any] = {
            "nodes": [
                {
                    "id": "run-sub",
                    "type": "workflow",
                    "params": {"workflow": "./sub.pflow.md"},
                }
            ],
            "edges": [],
        }
        markdown = ir_to_markdown(ir, title="Sub-Workflow Only")

        with pytest.raises(WorkflowValidationError, match="file references"):
            save_workflow_with_options(
                name="sub-only-test",
                markdown_content=markdown,
                # No source_path — simulates MCP raw-content save
            )

    def test_raw_content_with_prompt_file_ref_rejected(self) -> None:
        """MCP-style save of raw markdown with prompt file ref is rejected."""
        from pflow.core.exceptions import WorkflowValidationError

        ir: dict[str, Any] = {
            "nodes": [
                {
                    "id": "ask",
                    "type": "llm",
                    "params": {"prompt": "./prompts/foo.md"},
                }
            ],
            "edges": [],
        }
        markdown = ir_to_markdown(ir, title="Prompt Ref Only")

        with pytest.raises(WorkflowValidationError, match="file references"):
            save_workflow_with_options(
                name="prompt-only-test",
                markdown_content=markdown,
            )

    def test_raw_content_without_file_refs_succeeds(self) -> None:
        """MCP-style save of raw markdown WITHOUT file refs succeeds normally."""
        ir: dict[str, Any] = {
            "nodes": [
                {
                    "id": "greet",
                    "type": "shell",
                    "params": {"command": "echo hello"},
                }
            ],
            "edges": [],
        }
        markdown = ir_to_markdown(ir, title="No Refs")

        saved_path, bundled = save_workflow_with_options(
            name="no-refs-test",
            markdown_content=markdown,
        )
        assert saved_path.exists()
        assert bundled == []


class TestSubWorkflowParseErrorPropagation:
    """Verify that non-parse errors during sub-workflow scanning propagate instead of being swallowed."""

    def test_permission_error_propagates(self, project_dir: Path, workflows_dir: Path) -> None:
        """PermissionError reading a sub-workflow aborts discovery, not silent skip.

        Regression: broad except Exception swallowed PermissionError, producing
        a bundle where the sub-workflow file existed but its own dependencies
        were missing — causing confusing runtime errors.
        """
        # Create a sub-workflow file
        sub_path = project_dir / "sub.pflow.md"
        sub_path.write_text(
            ir_to_markdown(
                {"nodes": [{"id": "s", "type": "shell", "params": {"command": "echo"}}], "edges": []},
            )
        )

        parent_ir: dict[str, Any] = {
            "nodes": [
                {
                    "id": "run-sub",
                    "type": "workflow",
                    "params": {"workflow": "./sub.pflow.md"},
                }
            ],
            "edges": [],
        }

        # Make the sub-workflow unreadable after discovery finds it
        from unittest.mock import patch

        original_read = Path.read_text

        def failing_read(self: Path, *args: Any, **kwargs: Any) -> str:
            if self.name == "sub.pflow.md" and "project" in str(self):
                raise PermissionError(f"Permission denied: {self}")
            return original_read(self, *args, **kwargs)

        with patch.object(Path, "read_text", failing_read), pytest.raises(PermissionError, match="Permission denied"):
            discover_dependencies(parent_ir, project_dir)
