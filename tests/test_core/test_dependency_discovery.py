"""Tests for workflow dependency discovery.

Validates that discover_dependencies() correctly identifies all file
dependencies in a workflow IR: sub-workflows, file-referenced params,
batch config files, and file refs within batch items. Also tests
cycle detection, missing-file errors, and recursive sub-workflow scanning.
"""

from pathlib import Path
from typing import Any

import pytest

from pflow.core.file_resolver import is_workflow_file_reference
from pflow.core.workflow.dependency_discovery import (
    Dependency,
    discover_dependencies,
)
from tests.shared.markdown_utils import ir_to_markdown

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ir(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Create a minimal IR dict with the given nodes."""
    return {"nodes": nodes, "edges": []}


def _dep_by_param(deps: list[Dependency], param: str) -> Dependency:
    """Find a dependency by its source_param value (for assertions)."""
    matches = [d for d in deps if d.source_param == param]
    assert len(matches) == 1, f"Expected 1 dep with param '{param}', found {len(matches)}: {matches}"
    return matches[0]


def _dep_by_type(deps: list[Dependency], dep_type: str) -> list[Dependency]:
    """Filter dependencies by dep_type."""
    return [d for d in deps if d.dep_type == dep_type]


# ---------------------------------------------------------------------------
# is_workflow_file_reference
# ---------------------------------------------------------------------------


class TestIsSubWorkflowFileRef:
    """Tests for the heuristic that distinguishes file paths from saved workflow names."""

    def test_dot_slash_path(self) -> None:
        assert is_workflow_file_reference("./sub.pflow.md") is True

    def test_slash_in_path(self) -> None:
        assert is_workflow_file_reference("workflows/sub.pflow.md") is True

    def test_backslash_in_path(self) -> None:
        assert is_workflow_file_reference("workflows\\sub.pflow.md") is True

    def test_pflow_md_extension(self) -> None:
        assert is_workflow_file_reference("sub.pflow.md") is True

    def test_dot_prefix(self) -> None:
        assert is_workflow_file_reference(".hidden-workflow") is True

    def test_bare_name_not_file(self) -> None:
        """A plain saved workflow name (no path indicators) is NOT a file ref."""
        assert is_workflow_file_reference("my-helper") is False

    def test_bare_name_with_hyphen(self) -> None:
        assert is_workflow_file_reference("generate-review") is False

    def test_empty_string(self) -> None:
        assert is_workflow_file_reference("") is False


# ---------------------------------------------------------------------------
# discover_dependencies — no dependencies
# ---------------------------------------------------------------------------


class TestNoDependencies:
    """IR with no file references returns empty list."""

    def test_no_file_refs_returns_empty(self, tmp_path: Path) -> None:
        """When no params contain file references, result is []."""
        ir = _make_ir([
            {"id": "step1", "type": "shell", "params": {"command": "echo hello"}},
        ])
        deps = discover_dependencies(ir, tmp_path)
        assert deps == []

    def test_empty_nodes_list(self, tmp_path: Path) -> None:
        ir: dict[str, Any] = {"nodes": []}
        deps = discover_dependencies(ir, tmp_path)
        assert deps == []

    def test_non_resolvable_param_ignored(self, tmp_path: Path) -> None:
        """Params like 'file_path' or 'url' are NOT in FILE_RESOLVABLE_PARAMS."""
        ir = _make_ir([
            {"id": "step1", "type": "read-file", "params": {"file_path": "./data.txt"}},
        ])
        deps = discover_dependencies(ir, tmp_path)
        assert deps == []


# ---------------------------------------------------------------------------
# discover_dependencies — file refs in params
# ---------------------------------------------------------------------------


class TestFileRefInParams:
    """File references in node params detected as dep_type='file_ref'."""

    def test_prompt_param(self, tmp_path: Path) -> None:
        """A prompt param pointing to a file is discovered."""
        prompt_dir = tmp_path / "prompts"
        prompt_dir.mkdir()
        (prompt_dir / "foo.md").write_text("You are a helpful assistant")

        ir = _make_ir([
            {"id": "ask", "type": "llm", "params": {"prompt": "./prompts/foo.md"}},
        ])
        deps = discover_dependencies(ir, tmp_path)

        assert len(deps) == 1
        dep = deps[0]
        assert dep.relative_path == "./prompts/foo.md"
        assert dep.absolute_path == (tmp_path / "prompts" / "foo.md").resolve()
        assert dep.source_node_id == "ask"
        assert dep.source_param == "prompt"
        assert dep.dep_type == "file_ref"

    def test_command_param(self, tmp_path: Path) -> None:
        """A command param pointing to a script is discovered."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "run.sh").write_text("#!/bin/bash\necho hi")

        ir = _make_ir([
            {"id": "run", "type": "shell", "params": {"command": "./scripts/run.sh"}},
        ])
        deps = discover_dependencies(ir, tmp_path)

        assert len(deps) == 1
        dep = deps[0]
        assert dep.relative_path == "./scripts/run.sh"
        assert dep.source_node_id == "run"
        assert dep.source_param == "command"
        assert dep.dep_type == "file_ref"

    def test_code_param(self, tmp_path: Path) -> None:
        """A code param pointing to a .py file is discovered."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "process.py").write_text("result = 42")

        ir = _make_ir([
            {"id": "compute", "type": "python", "params": {"code": "./scripts/process.py"}},
        ])
        deps = discover_dependencies(ir, tmp_path)

        assert len(deps) == 1
        dep = deps[0]
        assert dep.relative_path == "./scripts/process.py"
        assert dep.source_node_id == "compute"
        assert dep.source_param == "code"
        assert dep.dep_type == "file_ref"

    def test_source_param(self, tmp_path: Path) -> None:
        """A source param is also in FILE_RESOLVABLE_PARAMS."""
        (tmp_path / "template.md").write_text("template content")

        ir = _make_ir([
            {"id": "out", "type": "llm", "params": {"source": "./template.md"}},
        ])
        deps = discover_dependencies(ir, tmp_path)

        assert len(deps) == 1
        assert deps[0].source_param == "source"
        assert deps[0].dep_type == "file_ref"

    def test_inline_value_not_detected(self, tmp_path: Path) -> None:
        """An inline string (not a file path) is NOT discovered as a dependency."""
        ir = _make_ir([
            {"id": "ask", "type": "llm", "params": {"prompt": "Tell me about life"}},
        ])
        deps = discover_dependencies(ir, tmp_path)
        assert deps == []

    def test_template_variable_not_detected(self, tmp_path: Path) -> None:
        """Template variables like ${item.prompt} are NOT file references."""
        ir = _make_ir([
            {"id": "ask", "type": "llm", "params": {"prompt": "${prev.output}"}},
        ])
        deps = discover_dependencies(ir, tmp_path)
        assert deps == []


# ---------------------------------------------------------------------------
# discover_dependencies — sub-workflow file refs
# ---------------------------------------------------------------------------


class TestSubWorkflowFileRef:
    """Sub-workflow file references detected as dep_type='sub_workflow'."""

    def test_sub_workflow_discovered(self, tmp_path: Path) -> None:
        """A workflow param with a file path is discovered as sub_workflow."""
        sub_ir = {
            "nodes": [{"id": "inner", "type": "shell", "params": {"command": "echo inner"}}],
            "edges": [],
        }
        sub_path = tmp_path / "sub.pflow.md"
        sub_path.write_text(ir_to_markdown(sub_ir))

        ir = _make_ir([
            {"id": "outer", "type": "workflow", "params": {"workflow": "./sub.pflow.md"}},
        ])
        deps = discover_dependencies(ir, tmp_path)

        sub_deps = _dep_by_type(deps, "sub_workflow")
        assert len(sub_deps) == 1
        dep = sub_deps[0]
        assert dep.relative_path == "./sub.pflow.md"
        assert dep.absolute_path == sub_path.resolve()
        assert dep.source_node_id == "outer"
        assert dep.source_param == "workflow"
        assert dep.dep_type == "sub_workflow"

    def test_sub_workflow_by_name_not_bundled(self, tmp_path: Path) -> None:
        """A workflow param with a plain name (no path indicators) is NOT discovered."""
        ir = _make_ir([
            {"id": "outer", "type": "workflow", "params": {"workflow": "my-helper"}},
        ])
        deps = discover_dependencies(ir, tmp_path)
        assert deps == []

    def test_sub_workflow_by_name_no_dots_or_slashes(self, tmp_path: Path) -> None:
        """Names like 'generate-review' are saved workflows, not file refs."""
        ir = _make_ir([
            {"id": "outer", "type": "workflow", "params": {"workflow": "generate-review"}},
        ])
        deps = discover_dependencies(ir, tmp_path)
        assert deps == []


# ---------------------------------------------------------------------------
# discover_dependencies — recursive sub-workflow deps
# ---------------------------------------------------------------------------


class TestRecursiveSubWorkflowDeps:
    """Sub-workflows are recursively scanned; their deps are flattened."""

    def test_recursive_deps_flattened(self, tmp_path: Path) -> None:
        """When a sub-workflow itself has file refs, they appear in the result."""
        # Create the file that sub-workflow references
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "inner.md").write_text("inner prompt content")

        # Create sub-workflow that references a prompt file
        sub_ir = {
            "nodes": [
                {"id": "ask", "type": "llm", "params": {"prompt": "./prompts/inner.md"}},
            ],
            "edges": [],
        }
        sub_path = tmp_path / "sub.pflow.md"
        sub_path.write_text(ir_to_markdown(sub_ir))

        # Create parent workflow that references the sub-workflow
        ir = _make_ir([
            {"id": "outer", "type": "workflow", "params": {"workflow": "./sub.pflow.md"}},
        ])
        deps = discover_dependencies(ir, tmp_path)

        # Should have 2 deps: the sub-workflow itself + the prompt inside it
        assert len(deps) == 2

        sub_workflow_deps = _dep_by_type(deps, "sub_workflow")
        assert len(sub_workflow_deps) == 1
        assert sub_workflow_deps[0].relative_path == "./sub.pflow.md"

        file_ref_deps = _dep_by_type(deps, "file_ref")
        assert len(file_ref_deps) == 1
        assert file_ref_deps[0].relative_path == "./prompts/inner.md"
        assert file_ref_deps[0].source_node_id == "ask"

    def test_deeply_nested_sub_workflows(self, tmp_path: Path) -> None:
        """Three levels of nesting: parent -> child -> grandchild, all deps collected."""
        # Create grandchild prompt
        (tmp_path / "deep.md").write_text("deep content")

        # Create grandchild workflow referencing deep.md
        grandchild_ir = {
            "nodes": [{"id": "gc", "type": "llm", "params": {"prompt": "./deep.md"}}],
            "edges": [],
        }
        grandchild_path = tmp_path / "grandchild.pflow.md"
        grandchild_path.write_text(ir_to_markdown(grandchild_ir))

        # Create child workflow referencing grandchild
        child_ir = {
            "nodes": [{"id": "c", "type": "workflow", "params": {"workflow": "./grandchild.pflow.md"}}],
            "edges": [],
        }
        child_path = tmp_path / "child.pflow.md"
        child_path.write_text(ir_to_markdown(child_ir))

        # Create parent workflow referencing child
        parent_ir = _make_ir([
            {"id": "p", "type": "workflow", "params": {"workflow": "./child.pflow.md"}},
        ])
        deps = discover_dependencies(parent_ir, tmp_path)

        # Should have: child.pflow.md, grandchild.pflow.md, deep.md
        assert len(deps) == 3

        sub_workflows = _dep_by_type(deps, "sub_workflow")
        assert len(sub_workflows) == 2
        sub_paths = {d.relative_path for d in sub_workflows}
        assert "./child.pflow.md" in sub_paths
        assert "./grandchild.pflow.md" in sub_paths

        file_refs = _dep_by_type(deps, "file_ref")
        assert len(file_refs) == 1
        assert file_refs[0].relative_path == "./deep.md"


# ---------------------------------------------------------------------------
# discover_dependencies — batch config file
# ---------------------------------------------------------------------------


class TestBatchConfigFile:
    """Batch config as external file reference (top-level node key, not in params)."""

    def test_batch_config_discovered(self, tmp_path: Path) -> None:
        """A batch param with a file reference is discovered."""
        batch_content = "items:\n  - focus: ai\n    prompt: inline prompt\n"
        (tmp_path / "reviews.yaml").write_text(batch_content)

        ir = _make_ir([
            {"id": "review", "type": "llm", "batch": "./reviews.yaml", "params": {"prompt": "${item.prompt}"}},
        ])
        deps = discover_dependencies(ir, tmp_path)

        assert len(deps) == 1
        dep = deps[0]
        assert dep.relative_path == "./reviews.yaml"
        assert dep.absolute_path == (tmp_path / "reviews.yaml").resolve()
        assert dep.source_node_id == "review"
        assert dep.source_param == "batch"
        assert dep.dep_type == "file_ref"

    def test_batch_config_with_file_refs_in_items(self, tmp_path: Path) -> None:
        """Batch YAML file that itself contains file references in items."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "review.md").write_text("review prompt content")

        # The batch YAML file contains file references in items
        batch_content = "items:\n  - prompt: ./prompts/review.md\n    focus: quality\n"
        (tmp_path / "batch.yaml").write_text(batch_content)

        ir = _make_ir([
            {"id": "review", "type": "llm", "batch": "./batch.yaml", "params": {"prompt": "${item.prompt}"}},
        ])
        deps = discover_dependencies(ir, tmp_path)

        # Should have 2: the batch file itself + the prompt inside batch items
        assert len(deps) == 2
        batch_dep = _dep_by_param(deps, "batch")
        assert batch_dep.relative_path == "./batch.yaml"

        item_dep = _dep_by_param(deps, "batch.items[0].prompt")
        assert item_dep.relative_path == "./prompts/review.md"
        assert item_dep.dep_type == "file_ref"


# ---------------------------------------------------------------------------
# discover_dependencies — batch item file refs (inline batch dict)
# ---------------------------------------------------------------------------


class TestBatchItemFileRefs:
    """File references inside inline batch items are discovered."""

    def test_inline_batch_item_prompt(self, tmp_path: Path) -> None:
        """File refs in inline batch items (dict, not string) are discovered."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "ai.md").write_text("check for AI tells")
        (prompts_dir / "cliche.md").write_text("check for cliches")

        ir = _make_ir([
            {
                "id": "review",
                "type": "llm",
                "batch": {
                    "items": [
                        {"focus": "ai", "prompt": "./prompts/ai.md"},
                        {"focus": "cliche", "prompt": "./prompts/cliche.md"},
                    ],
                },
                "params": {"prompt": "${item.prompt}"},
            },
        ])
        deps = discover_dependencies(ir, tmp_path)

        assert len(deps) == 2
        dep0 = _dep_by_param(deps, "batch.items[0].prompt")
        assert dep0.relative_path == "./prompts/ai.md"
        assert dep0.source_node_id == "review"
        assert dep0.dep_type == "file_ref"

        dep1 = _dep_by_param(deps, "batch.items[1].prompt")
        assert dep1.relative_path == "./prompts/cliche.md"

    def test_non_file_ref_items_ignored(self, tmp_path: Path) -> None:
        """Inline values in batch items are not treated as file refs."""
        ir = _make_ir([
            {
                "id": "review",
                "type": "llm",
                "batch": {
                    "items": [
                        {"focus": "ai", "prompt": "Check for AI tells"},
                    ],
                },
                "params": {"prompt": "${item.prompt}"},
            },
        ])
        deps = discover_dependencies(ir, tmp_path)
        assert deps == []

    def test_non_resolvable_batch_item_keys_ignored(self, tmp_path: Path) -> None:
        """Keys not in FILE_RESOLVABLE_PARAMS are ignored even if value looks like a path."""
        (tmp_path / "data.txt").write_text("data")
        ir = _make_ir([
            {
                "id": "step",
                "type": "llm",
                "batch": {
                    "items": [{"file_path": "./data.txt", "label": "test"}],
                },
                "params": {},
            },
        ])
        deps = discover_dependencies(ir, tmp_path)
        assert deps == []


# ---------------------------------------------------------------------------
# discover_dependencies — cycle detection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    """Circular sub-workflow references don't cause infinite recursion."""

    def test_self_referencing_workflow(self, tmp_path: Path) -> None:
        """A workflow referencing itself is detected; no infinite loop."""
        # Create a workflow that references itself
        self_ir = {
            "nodes": [{"id": "self", "type": "workflow", "params": {"workflow": "./self.pflow.md"}}],
            "edges": [],
        }
        self_path = tmp_path / "self.pflow.md"
        self_path.write_text(ir_to_markdown(self_ir))

        # The parent IR also references self.pflow.md
        ir = _make_ir([
            {"id": "outer", "type": "workflow", "params": {"workflow": "./self.pflow.md"}},
        ])

        # Should not raise or hang — cycle is detected and skipped
        deps = discover_dependencies(ir, tmp_path)

        # The sub-workflow itself is discovered once (from the parent)
        sub_deps = _dep_by_type(deps, "sub_workflow")
        assert len(sub_deps) == 1
        assert sub_deps[0].relative_path == "./self.pflow.md"

    def test_mutual_reference_cycle(self, tmp_path: Path) -> None:
        """A references B which references A — no infinite loop, warning logged."""
        # Workflow A references B
        a_ir = {
            "nodes": [{"id": "go-b", "type": "workflow", "params": {"workflow": "./b.pflow.md"}}],
            "edges": [],
        }
        a_path = tmp_path / "a.pflow.md"
        a_path.write_text(ir_to_markdown(a_ir))

        # Workflow B references A
        b_ir = {
            "nodes": [{"id": "go-a", "type": "workflow", "params": {"workflow": "./a.pflow.md"}}],
            "edges": [],
        }
        b_path = tmp_path / "b.pflow.md"
        b_path.write_text(ir_to_markdown(b_ir))

        # Start from A
        ir = _make_ir([
            {"id": "start", "type": "workflow", "params": {"workflow": "./a.pflow.md"}},
        ])

        deps = discover_dependencies(ir, tmp_path)

        # Should discover a.pflow.md and b.pflow.md, but not loop
        sub_deps = _dep_by_type(deps, "sub_workflow")
        assert len(sub_deps) == 2
        paths = {d.relative_path for d in sub_deps}
        assert "./a.pflow.md" in paths
        assert "./b.pflow.md" in paths

    def test_cycle_logs_warning(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Cycle detection logs a warning with the circular path info."""
        caplog.set_level("WARNING", logger="pflow.core.workflow.dependency_discovery")

        # Create self-referencing workflow
        self_ir = {
            "nodes": [{"id": "loop", "type": "workflow", "params": {"workflow": "./self.pflow.md"}}],
            "edges": [],
        }
        self_path = tmp_path / "self.pflow.md"
        self_path.write_text(ir_to_markdown(self_ir))

        ir = _make_ir([
            {"id": "outer", "type": "workflow", "params": {"workflow": "./self.pflow.md"}},
        ])
        discover_dependencies(ir, tmp_path)

        # The cycle from self.pflow.md -> self.pflow.md should log a warning
        assert any("circular" in record.message.lower() for record in caplog.records)


# ---------------------------------------------------------------------------
# discover_dependencies — missing file error
# ---------------------------------------------------------------------------


class TestMissingFileError:
    """Non-existent file references raise FileNotFoundError."""

    def test_missing_prompt_file(self, tmp_path: Path) -> None:
        """Missing file in a param raises FileNotFoundError with node_id and param."""
        ir = _make_ir([
            {"id": "ask", "type": "llm", "params": {"prompt": "./nonexistent.md"}},
        ])

        with pytest.raises(FileNotFoundError) as exc_info:
            discover_dependencies(ir, tmp_path)

        msg = str(exc_info.value)
        assert "ask" in msg  # node_id
        assert "prompt" in msg  # param name
        assert "nonexistent.md" in msg  # file ref

    def test_missing_sub_workflow_file(self, tmp_path: Path) -> None:
        """Missing sub-workflow file raises FileNotFoundError."""
        ir = _make_ir([
            {"id": "outer", "type": "workflow", "params": {"workflow": "./missing.pflow.md"}},
        ])

        with pytest.raises(FileNotFoundError) as exc_info:
            discover_dependencies(ir, tmp_path)

        msg = str(exc_info.value)
        assert "outer" in msg
        assert "workflow" in msg
        assert "missing.pflow.md" in msg

    def test_missing_batch_config_file(self, tmp_path: Path) -> None:
        """Missing batch config file raises FileNotFoundError."""
        ir = _make_ir([
            {"id": "review", "type": "llm", "batch": "./missing.yaml", "params": {}},
        ])

        with pytest.raises(FileNotFoundError) as exc_info:
            discover_dependencies(ir, tmp_path)

        msg = str(exc_info.value)
        assert "review" in msg
        assert "batch" in msg

    def test_error_includes_resolved_and_base_paths(self, tmp_path: Path) -> None:
        """Error message includes resolved path and base directory for debugging."""
        ir = _make_ir([
            {"id": "n1", "type": "llm", "params": {"prompt": "./deep/missing.md"}},
        ])

        with pytest.raises(FileNotFoundError) as exc_info:
            discover_dependencies(ir, tmp_path)

        msg = str(exc_info.value)
        assert "Resolved to:" in msg
        assert "Relative to:" in msg

    def test_missing_file_inside_batch_items(self, tmp_path: Path) -> None:
        """Missing file referenced in inline batch items raises FileNotFoundError."""
        ir = _make_ir([
            {
                "id": "review",
                "type": "llm",
                "batch": {
                    "items": [{"prompt": "./missing-prompt.md"}],
                },
                "params": {"prompt": "${item.prompt}"},
            },
        ])

        with pytest.raises(FileNotFoundError) as exc_info:
            discover_dependencies(ir, tmp_path)

        msg = str(exc_info.value)
        assert "review" in msg
        assert "batch.items[0].prompt" in msg


# ---------------------------------------------------------------------------
# discover_dependencies — mixed dependencies
# ---------------------------------------------------------------------------


class TestMixedDependencies:
    """One workflow with sub-workflow + file refs + batch, all discovered."""

    def test_all_dep_types_discovered(self, tmp_path: Path) -> None:
        """A workflow with multiple dependency types has all of them discovered."""
        # Create sub-workflow
        sub_ir = {
            "nodes": [{"id": "inner", "type": "shell", "params": {"command": "echo inner"}}],
            "edges": [],
        }
        sub_path = tmp_path / "sub.pflow.md"
        sub_path.write_text(ir_to_markdown(sub_ir))

        # Create prompt file
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "system.md").write_text("system prompt")

        # Create script file
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "process.sh").write_text("#!/bin/bash\necho done")

        # Create batch config
        batch_content = "items:\n  - focus: quality\n    prompt: inline\n"
        (tmp_path / "batch.yaml").write_text(batch_content)

        ir = _make_ir([
            {"id": "orchestrate", "type": "workflow", "params": {"workflow": "./sub.pflow.md"}},
            {"id": "ask", "type": "llm", "params": {"prompt": "./prompts/system.md"}},
            {"id": "run", "type": "shell", "params": {"command": "./scripts/process.sh"}},
            {"id": "review", "type": "llm", "batch": "./batch.yaml", "params": {"prompt": "${item.prompt}"}},
        ])
        deps = discover_dependencies(ir, tmp_path)

        # 4 deps: sub-workflow + prompt + command + batch config
        assert len(deps) == 4

        # Verify sub-workflow
        sub_deps = _dep_by_type(deps, "sub_workflow")
        assert len(sub_deps) == 1
        assert sub_deps[0].relative_path == "./sub.pflow.md"
        assert sub_deps[0].source_node_id == "orchestrate"

        # Verify file refs
        file_deps = _dep_by_type(deps, "file_ref")
        assert len(file_deps) == 3
        file_paths = {d.relative_path for d in file_deps}
        assert "./prompts/system.md" in file_paths
        assert "./scripts/process.sh" in file_paths
        assert "./batch.yaml" in file_paths


# ---------------------------------------------------------------------------
# discover_dependencies — edge cases and robustness
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Robustness: malformed IR, missing keys, etc."""

    def test_node_without_params(self, tmp_path: Path) -> None:
        """Node with no params key doesn't crash."""
        ir = _make_ir([{"id": "n1", "type": "shell"}])
        deps = discover_dependencies(ir, tmp_path)
        assert deps == []

    def test_params_as_string_skipped(self, tmp_path: Path) -> None:
        """Malformed IR with params as string doesn't crash."""
        ir: dict[str, Any] = {
            "nodes": [{"id": "n1", "type": "shell", "params": "oops"}],
            "edges": [],
        }
        deps = discover_dependencies(ir, tmp_path)
        assert deps == []

    def test_non_dict_node_skipped(self, tmp_path: Path) -> None:
        """Non-dict entries in nodes list are skipped."""
        ir: dict[str, Any] = {"nodes": ["not-a-dict", 42, None]}
        deps = discover_dependencies(ir, tmp_path)
        assert deps == []

    def test_workflow_param_not_string_skipped(self, tmp_path: Path) -> None:
        """Non-string workflow param value is skipped gracefully."""
        ir = _make_ir([
            {"id": "n1", "type": "workflow", "params": {"workflow": 42}},
        ])
        deps = discover_dependencies(ir, tmp_path)
        assert deps == []

    def test_batch_dict_without_items(self, tmp_path: Path) -> None:
        """Inline batch dict without 'items' key doesn't crash."""
        ir = _make_ir([
            {"id": "n1", "type": "llm", "batch": {"parallel": True}, "params": {}},
        ])
        deps = discover_dependencies(ir, tmp_path)
        assert deps == []

    def test_batch_items_with_non_dict_entries(self, tmp_path: Path) -> None:
        """Non-dict entries in batch items list are skipped."""
        ir = _make_ir([
            {
                "id": "n1",
                "type": "llm",
                "batch": {"items": ["not-a-dict", 42]},
                "params": {},
            },
        ])
        deps = discover_dependencies(ir, tmp_path)
        assert deps == []

    def test_parent_directory_reference(self, tmp_path: Path) -> None:
        """../path references resolve correctly."""
        # Layout: tmp_path/workflows/ and tmp_path/prompts/
        workflows_dir = tmp_path / "workflows"
        prompts_dir = tmp_path / "prompts"
        workflows_dir.mkdir()
        prompts_dir.mkdir()
        (prompts_dir / "shared.md").write_text("shared prompt")

        ir = _make_ir([
            {"id": "ask", "type": "llm", "params": {"prompt": "../prompts/shared.md"}},
        ])
        deps = discover_dependencies(ir, workflows_dir)

        assert len(deps) == 1
        assert deps[0].relative_path == "../prompts/shared.md"
        assert deps[0].absolute_path == (prompts_dir / "shared.md").resolve()

    def test_multiple_file_refs_in_same_node(self, tmp_path: Path) -> None:
        """A node with multiple file-referenced params has all discovered."""
        (tmp_path / "prompt.md").write_text("prompt content")
        (tmp_path / "stdin.txt").write_text("stdin content")

        ir = _make_ir([
            {
                "id": "multi",
                "type": "llm",
                "params": {
                    "prompt": "./prompt.md",
                    "stdin": "./stdin.txt",
                    "model": "gpt-4",
                },
            },
        ])
        deps = discover_dependencies(ir, tmp_path)

        assert len(deps) == 2
        params = {d.source_param for d in deps}
        assert "prompt" in params
        assert "stdin" in params

    def test_seen_set_prevents_duplicate_sub_workflow(self, tmp_path: Path) -> None:
        """If two nodes reference the same sub-workflow, only the first is recursed into."""
        sub_ir = {
            "nodes": [{"id": "inner", "type": "shell", "params": {"command": "echo hi"}}],
            "edges": [],
        }
        sub_path = tmp_path / "shared.pflow.md"
        sub_path.write_text(ir_to_markdown(sub_ir))

        ir = _make_ir([
            {"id": "a", "type": "workflow", "params": {"workflow": "./shared.pflow.md"}},
            {"id": "b", "type": "workflow", "params": {"workflow": "./shared.pflow.md"}},
        ])
        deps = discover_dependencies(ir, tmp_path)

        # First reference is discovered; second is skipped (already in seen set)
        sub_deps = _dep_by_type(deps, "sub_workflow")
        assert len(sub_deps) == 1
        assert sub_deps[0].source_node_id == "a"
