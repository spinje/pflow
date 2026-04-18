"""Tests for WorkflowValidator._validate_sub_workflows() (step 8).

Validates recursive sub-workflow validation: parse error bubbling, required
input checking, cycle detection, inline IR validation, and saved workflow
name resolution.
"""

from pathlib import Path

import pytest

from pflow.core.workflow.validator import WorkflowValidator
from pflow.registry import Registry
from tests.shared.diagnostic_helpers import split_validator_diagnostics


def write_pflow_md(path: Path, content: str) -> None:
    """Write raw markdown content to a .pflow.md file."""
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Helper: minimal valid parent IR that references a child workflow file
# ---------------------------------------------------------------------------


def _parent_ir(child_ref: str, provided_params: dict | None = None) -> dict:
    """Build a parent IR with one workflow node referencing `child_ref`.

    `provided_params` are extra keys in the node's params dict
    (treated as child inputs by the validator because they are not reserved).
    """
    params: dict = {"workflow": child_ref}
    if provided_params:
        # If the caller explicitly set an ``inputs`` key (dict or opaque template
        # string), use it verbatim — otherwise wrap the bare mapping as the
        # child-input dict.
        if "inputs" in provided_params:
            params.update(provided_params)
        else:
            params["inputs"] = dict(provided_params)
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "child-step",
                "type": "workflow",
                "params": params,
            }
        ],
        "edges": [],
    }


# ---------------------------------------------------------------------------
# 1. Broken sub-workflow caught at validation
# ---------------------------------------------------------------------------


class TestBrokenSubWorkflow:
    def test_broken_sub_workflow_caught_at_validation(self, tmp_path: Path) -> None:
        """When a child .pflow.md has a step missing its description,
        the parse error should surface in the parent's validation errors."""
        broken_child = tmp_path / "broken-child.pflow.md"
        write_pflow_md(
            broken_child,
            """\
# Broken Child

This child workflow has a broken step.

## Steps

### process
- type: llm
- prompt: Echo back
""",
        )

        parent_ir = _parent_ir(str(broken_child))
        errors, _warnings = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            registry=None,
            skip_node_types=True,
        )

        # Parser should complain about the missing description
        assert any("missing a description" in d.message.lower() for d in errors), (
            f"Expected 'missing a description' error, got: {errors}"
        )
        # Error should mention it comes from a sub-workflow
        assert any("sub-workflow" in d.message.lower() or "in sub-workflow" in d.message.lower() for d in errors), (
            f"Expected sub-workflow attribution, got: {errors}"
        )


# ---------------------------------------------------------------------------
# 2. Valid sub-workflow passes
# ---------------------------------------------------------------------------


class TestValidSubWorkflow:
    def test_valid_sub_workflow_passes(self, tmp_path: Path) -> None:
        """A parent referencing a valid child should produce no sub-workflow errors."""
        valid_child = tmp_path / "valid-child.pflow.md"
        write_pflow_md(
            valid_child,
            """\
# Valid Child

A perfectly fine child workflow.

## Steps

### greet

This step greets the user nicely.

- type: shell
- command: echo hello
""",
        )

        parent_ir = _parent_ir(str(valid_child))
        errors, _warnings = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            registry=None,
            skip_node_types=True,
        )

        # No errors at all (structural + sub-workflow)
        assert errors == [], f"Expected no errors, got: {errors}"


# ---------------------------------------------------------------------------
# 3. Nested sub-workflow validation (3 levels)
# ---------------------------------------------------------------------------


class TestNestedSubWorkflow:
    def test_nested_sub_workflow_validation(self, tmp_path: Path) -> None:
        """Parent -> middle -> broken grandchild.  Error should carry the
        full nesting path so the user can locate the root cause."""
        # Grandchild: broken (missing description)
        grandchild = tmp_path / "grandchild.pflow.md"
        write_pflow_md(
            grandchild,
            """\
# Grandchild

A broken grandchild.

## Steps

### bad-step
- type: shell
- command: echo broken
""",
        )

        # Middle: valid itself, references grandchild
        middle = tmp_path / "middle.pflow.md"
        write_pflow_md(
            middle,
            f"""\
# Middle

A valid middle workflow.

## Steps

### delegate

Delegate to the grandchild workflow.

- type: workflow
- workflow: {grandchild}
""",
        )

        parent_ir = _parent_ir(str(middle))
        errors, _warnings = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            registry=None,
            skip_node_types=True,
        )

        # Should see the grandchild parse error
        assert any("missing a description" in d.message.lower() for d in errors), (
            f"Expected grandchild parse error, got: {errors}"
        )
        # Error attribution should show nesting: both middle and grandchild mentioned
        nested_errors = [d for d in errors if "sub-workflow" in d.message.lower()]
        assert len(nested_errors) >= 1, f"Expected nested attribution, got: {errors}"


# ---------------------------------------------------------------------------
# 4. Circular reference terminates without error
# ---------------------------------------------------------------------------


class TestCircularReference:
    def test_circular_reference_no_infinite_loop(self, tmp_path: Path) -> None:
        """A -> B -> A should not cause infinite recursion.  The validator
        should skip already-seen workflows and terminate cleanly."""
        a_path = tmp_path / "a.pflow.md"
        b_path = tmp_path / "b.pflow.md"

        write_pflow_md(
            a_path,
            f"""\
# Workflow A

First workflow in the cycle.

## Steps

### call-b

This step delegates to workflow B.

- type: workflow
- workflow: {b_path}
""",
        )

        write_pflow_md(
            b_path,
            f"""\
# Workflow B

Second workflow in the cycle.

## Steps

### call-a

This step delegates to workflow A.

- type: workflow
- workflow: {a_path}
""",
        )

        parent_ir = _parent_ir(str(a_path))
        # Must terminate without hanging or raising
        errors, _warnings = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            registry=None,
            skip_node_types=True,
        )

        # Cycles are gracefully skipped — no "infinite" error expected
        # There should be no error specifically about the cycle
        cycle_errors = [
            d
            for d in errors
            if "cycle" in d.message.lower() or "circular" in d.message.lower() or "infinite" in d.message.lower()
        ]
        assert cycle_errors == [], f"Unexpected cycle error: {cycle_errors}"


# ---------------------------------------------------------------------------
# 5. Missing required input detected
# ---------------------------------------------------------------------------


class TestMissingRequiredInput:
    def test_missing_required_input_detected(self, tmp_path: Path) -> None:
        """When the child declares required inputs that the parent doesn't
        provide, the validator should report the missing ones."""
        child = tmp_path / "child.pflow.md"
        write_pflow_md(
            child,
            """\
# Child With Inputs

A child that needs two inputs.

## Inputs

### text

The text to process for the child.

- type: string
- required: true

### count

The number of times to repeat.

- type: integer
- required: true

## Steps

### do-it

Perform the configured operation now.

- type: shell
- command: echo done
""",
        )

        # Parent only provides 'text', not 'count'
        parent_ir = _parent_ir(str(child), provided_params={"text": "hello"})
        errors, _warnings = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            registry=None,
            skip_node_types=True,
        )

        assert any("count" in d.message for d in errors), f"Expected missing 'count' error, got: {errors}"
        # 'text' is provided, so it should NOT be flagged
        missing_text_errors = [d for d in errors if "input 'text'" in d.message and "not provided" in d.message]
        assert missing_text_errors == [], f"'text' should not be flagged as missing: {errors}"


# ---------------------------------------------------------------------------
# 6. Template workflow reference gracefully skipped
# ---------------------------------------------------------------------------


class TestTemplateWorkflowRef:
    def test_template_workflow_ref_skipped(self, tmp_path: Path) -> None:
        """When the workflow param is a template like ${dynamic_path}, the
        validator cannot resolve it statically and should skip it gracefully."""
        parent_ir = _parent_ir("${dynamic_path}")
        errors, _warnings = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            registry=None,
            skip_node_types=True,
        )

        # No sub-workflow errors from the template reference
        sub_wf_errors = [d for d in errors if "sub-workflow" in d.message.lower()]
        assert sub_wf_errors == [], f"Template ref should be skipped, got: {sub_wf_errors}"


# ---------------------------------------------------------------------------
# 7. Saved workflow name validated
# ---------------------------------------------------------------------------


class TestSavedWorkflowName:
    def test_saved_workflow_name_validated(self) -> None:
        """Save a workflow by name via WorkflowManager, then validate a
        parent referencing it by name.  The child's forward-reference error
        should surface in the parent's validation.

        We use raw markdown (not ir_to_markdown) because ir_to_markdown
        doesn't emit edges, and we need a forward reference error that
        survives the round-trip through save/load.
        """
        from pflow.core.workflow.manager import WorkflowManager

        # Raw markdown: step 'a' references ${b.stdout} but comes before 'b'
        # in document order.  The parser infers execution order from step order,
        # producing a forward-reference data-flow error.
        md_content = """\
# Broken Saved Child

A saved workflow with a forward reference.

## Steps

### a

First step referencing future step.

- type: shell
- command: echo ${b.stdout}

### b

Second step used by first step.

- type: shell
- command: echo hello
"""

        wm = WorkflowManager()
        wm.save("broken-saved-child", md_content)

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "saved-ref",
                    "type": "workflow",
                    "params": {"workflow": "broken-saved-child"},
                }
            ],
            "edges": [],
        }

        errors, _warnings = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            registry=None,
            skip_node_types=True,
        )

        # The saved child's forward-reference error should surface
        assert any("after" in d.message.lower() or "forward" in d.message.lower() for d in errors), (
            f"Expected forward-reference error from saved child, got: {errors}"
        )
        assert any("sub-workflow" in d.message.lower() for d in errors), (
            f"Expected sub-workflow attribution, got: {errors}"
        )


# ---------------------------------------------------------------------------
# 9. Sub-workflow unknown node type caught (with registry)
# ---------------------------------------------------------------------------


class TestSubWorkflowUnknownNodeType:
    def test_sub_workflow_unknown_node_type_caught(self, tmp_path: Path) -> None:
        """When a child workflow has an unknown node type and we pass
        skip_node_types=False with a real Registry, the error should
        propagate through the parent's validation."""
        child = tmp_path / "child-unknown-type.pflow.md"
        write_pflow_md(
            child,
            """\
# Child Unknown Type

Child with a made-up node type.

## Steps

### bad-node

This step uses a nonexistent node type.

- type: totally-fake-node-type
- foo: bar
""",
        )

        parent_ir = _parent_ir(str(child))
        registry = Registry()
        registry.load()

        errors, _warnings = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            registry=registry,
            skip_node_types=False,
        )

        assert any("unknown node type" in d.message.lower() for d in errors), (
            f"Expected unknown node type error, got: {errors}"
        )
        assert any("totally-fake-node-type" in d.message for d in errors), (
            f"Expected 'totally-fake-node-type' in error, got: {errors}"
        )


# ---------------------------------------------------------------------------
# 10. Sub-workflow data flow error caught
# ---------------------------------------------------------------------------


class TestSubWorkflowDataFlowError:
    def test_sub_workflow_data_flow_error_caught(self, tmp_path: Path) -> None:
        """A child workflow with a non-existent node reference should produce
        a data-flow error visible in the parent's validation."""
        child = tmp_path / "bad-ref-child.pflow.md"
        # Write a child with a reference to a non-existent node
        write_pflow_md(
            child,
            """\
# Bad Ref Child

A child that references a non-existent node.

## Steps

### step-a

First step that references a non-existent node.

- type: shell
- command: echo ${nonexistent-node.stdout}
""",
        )

        parent_ir = _parent_ir(str(child))
        errors, _warnings = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            registry=None,
            skip_node_types=True,
        )

        assert any("non-existent" in d.message.lower() or "nonexistent" in d.message.lower() for d in errors), (
            f"Expected non-existent node error from child, got: {errors}"
        )


# ---------------------------------------------------------------------------
# 11. Required: false input not flagged
# ---------------------------------------------------------------------------


class TestOptionalInputNotFlagged:
    def test_required_false_input_not_flagged(self, tmp_path: Path) -> None:
        """When a child declares an input with required: false and no default,
        the parent omitting it should NOT trigger an error."""
        child = tmp_path / "optional-input-child.pflow.md"
        write_pflow_md(
            child,
            """\
# Optional Input Child

Child with an optional input.

## Inputs

### maybe-param

An optional input parameter here.

- type: string
- required: false

## Steps

### do-it

Execute the main operation now.

- type: shell
- command: echo done
""",
        )

        # Parent provides nothing for the optional input
        parent_ir = _parent_ir(str(child))
        errors, _warnings = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            registry=None,
            skip_node_types=True,
        )

        missing_input_errors = [d for d in errors if "maybe-param" in d.message and "not provided" in d.message]
        assert missing_input_errors == [], f"Optional input should not be flagged as missing: {errors}"


# ---------------------------------------------------------------------------
# 12. Sub-workflow file not found
# ---------------------------------------------------------------------------


class TestSubWorkflowFileNotFound:
    def test_sub_workflow_file_not_found(self, tmp_path: Path) -> None:
        """When the parent references a .pflow.md file that doesn't exist,
        the validator should report a clear 'file not found' error."""
        nonexistent = str(tmp_path / "does-not-exist.pflow.md")
        parent_ir = _parent_ir(nonexistent)

        errors, _warnings = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            registry=None,
            skip_node_types=True,
        )

        assert any("not found" in d.message.lower() for d in errors), f"Expected 'file not found' error, got: {errors}"
        assert any("does-not-exist.pflow.md" in d.message for d in errors), (
            f"Expected file name in error message, got: {errors}"
        )


class TestDuplicateSubWorkflowReference:
    def test_second_reference_missing_input_still_caught(self, tmp_path: Path) -> None:
        """Two parent nodes reference the same child file with different params.

        The first node provides all required inputs; the second omits one.
        The missing input error on the second node must still be caught,
        even though the child file was already validated via the first node.
        """
        child = tmp_path / "child.pflow.md"
        write_pflow_md(
            child,
            "# Child\n\nA child workflow.\n\n## Inputs\n\n### text\n\nThe text.\n\n"
            "- type: string\n\n### count\n\nThe count.\n\n- type: integer\n\n"
            "## Steps\n\n### do-work\n\nProcess the input text.\n\n"
            "- type: shell\n- command: echo done\n",
        )

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "step-a",
                    "type": "workflow",
                    "params": {"workflow": str(child), "inputs": {"text": "hello", "count": "5"}},
                },
                {
                    "id": "step-b",
                    "type": "workflow",
                    "params": {"workflow": str(child), "inputs": {"text": "world"}},
                    # Missing "count" — should be caught
                },
            ],
            "edges": [{"from": "step-a", "to": "step-b"}],
        }

        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        # step-a should pass (provides both text and count)
        assert not any("step-a" in d.message.lower() and "not provided" in d.message for d in errors), (
            f"step-a should not have missing input errors: {errors}"
        )
        # step-b should fail (missing count)
        assert any("step-b" in d.message and "count" in d.message and "not provided" in d.message for d in errors), (
            f"Expected missing 'count' error for step-b, got: {errors}"
        )

    def test_cross_nesting_reference_missing_input_caught(self, tmp_path: Path) -> None:
        """Grandchild validated via child recursion, then parent directly references it
        with missing inputs.

        Parent node A → child.pflow.md → grandchild.pflow.md (validated here)
        Parent node B → grandchild.pflow.md (missing 'count')

        The grandchild's IR must be available for the input check on node B
        even though it was first loaded during child's recursive validation.
        """
        grandchild = tmp_path / "grandchild.pflow.md"
        write_pflow_md(
            grandchild,
            "# Grandchild\n\nA grandchild workflow.\n\n## Inputs\n\n"
            "### text\n\nThe text input.\n\n- type: string\n\n"
            "### count\n\nThe count input.\n\n- type: integer\n\n"
            "## Steps\n\n### work\n\nDo the work.\n\n- type: shell\n- command: echo done\n",
        )

        child = tmp_path / "child.pflow.md"
        write_pflow_md(
            child,
            f"# Child\n\nA child that calls grandchild.\n\n## Steps\n\n"
            f"### delegate\n\nDelegate to grandchild.\n\n"
            f"- type: workflow\n- workflow: {grandchild}\n- inputs:\n    text: hello\n    count: 5\n",
        )

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "via-child",
                    "type": "workflow",
                    "params": {"workflow": str(child)},
                },
                {
                    "id": "direct-grandchild",
                    "type": "workflow",
                    "params": {"workflow": str(grandchild), "inputs": {"text": "world"}},
                    # Missing "count" — must be caught even though grandchild
                    # was already validated during child's recursion
                },
            ],
            "edges": [{"from": "via-child", "to": "direct-grandchild"}],
        }

        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        assert any(
            "direct-grandchild" in d.message and "count" in d.message and "not provided" in d.message for d in errors
        ), f"Expected missing 'count' error for direct-grandchild, got: {errors}"


# ---------------------------------------------------------------------------
# 15. Relative path without workflow_file produces warning (issue #166)
# ---------------------------------------------------------------------------


class TestRelativePathWithoutWorkflowFile:
    def test_relative_path_without_workflow_file_skipped_with_warning(self) -> None:
        """When workflow_file is None and a relative sub-workflow path is used,
        the validator should skip with a clear warning instead of resolving
        against CWD."""
        parent_ir = _parent_ir("./child.pflow.md")
        errors, _warnings = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            skip_node_types=True,
            workflow_file=None,
        )

        assert any("cannot resolve relative" in d.message.lower() for d in errors), (
            f"Expected 'cannot resolve relative' error, got: {errors}"
        )
        assert any("./child.pflow.md" in d.message for d in errors)
        assert any("use an absolute path" in d.message.lower() for d in errors)


# ---------------------------------------------------------------------------
# 16. Absolute path works without workflow_file
# ---------------------------------------------------------------------------


class TestAbsolutePathWithoutWorkflowFile:
    def test_absolute_path_works_without_workflow_file(self, tmp_path: Path) -> None:
        """Absolute sub-workflow paths should work even when workflow_file is None."""
        child = tmp_path / "child.pflow.md"
        write_pflow_md(
            child,
            """\
# Child

A valid child workflow here.

## Steps

### step

Execute the main step now.

- type: shell
- command: echo ok
""",
        )

        parent_ir = _parent_ir(str(child))  # absolute path
        errors, _warnings = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            skip_node_types=True,
            workflow_file=None,
        )

        # No errors about unresolvable paths
        assert not any("cannot resolve" in d.message.lower() for d in errors), f"Unexpected resolution error: {errors}"


# ---------------------------------------------------------------------------
# 17. Relative path resolves correctly with workflow_file (issue #166)
# ---------------------------------------------------------------------------


class TestRelativePathWithWorkflowFile:
    def test_relative_path_resolves_with_workflow_file(self, tmp_path: Path) -> None:
        """When workflow_file is provided, relative sub-workflow paths should
        resolve against the workflow file's directory."""
        child = tmp_path / "child.pflow.md"
        write_pflow_md(
            child,
            """\
# Child

A valid child workflow here.

## Steps

### step

Execute the main step now.

- type: shell
- command: echo ok
""",
        )

        parent_ir = _parent_ir("./child.pflow.md")  # relative path
        errors, _warnings = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            skip_node_types=True,
            workflow_file=tmp_path / "parent.pflow.md",
        )

        assert not any("cannot resolve" in d.message.lower() for d in errors), f"Unexpected resolution error: {errors}"
        assert errors == [], f"Expected no errors, got: {errors}"


# ---------------------------------------------------------------------------
# 18. save_service resolves relative sub-workflows via source_path (issue #166)
# ---------------------------------------------------------------------------


class TestSaveServiceSubWorkflowResolution:
    def test_save_service_resolves_relative_sub_workflow(self, tmp_path: Path) -> None:
        """When save_service validates a workflow from a file, relative
        sub-workflow references should resolve against the file's directory,
        not CWD."""
        from pflow.core.workflow.save_service import _load_from_file

        child = tmp_path / "child.pflow.md"
        write_pflow_md(
            child,
            """\
# Child

A valid child workflow here.

## Steps

### step

Execute the main step now.

- type: shell
- command: echo ok
""",
        )

        parent = tmp_path / "parent.pflow.md"
        write_pflow_md(
            parent,
            """\
# Parent

A parent workflow here.

## Steps

### delegate

Delegate work to child workflow.

- type: workflow
- workflow: ./child.pflow.md
""",
        )

        # This should succeed regardless of CWD
        ir = _load_from_file(parent, auto_normalize=True)
        assert ir is not None
        assert "nodes" in ir


class TestDeepNestedProvenance:
    """Task 147 regression: for parent → child → grandchild, the innermost
    sub-workflow provenance (closest to the error) must be preserved.

    ``_add_child_provenance`` previously overwrote ``sub_workflow_step`` and
    ``sub_workflow_path`` on each recursion unwind, so the OUTERMOST hop won
    while ``node_id`` and ``context['path']`` still pointed at the DEEPEST
    level. This made the structured provenance fields inconsistent with the
    location fields — a JSON consumer using ``sub_workflow_path`` to open the
    source file would land on the wrong file. First-write-wins keeps the
    structured fields aligned with the location fields.
    """

    def test_three_level_nesting_keeps_innermost_sub_workflow_provenance(self, tmp_path: Path) -> None:
        from pflow.core.diagnostic import Severity

        grandchild = tmp_path / "grandchild.pflow.md"
        write_pflow_md(
            grandchild,
            """\
# Grandchild

Deepest workflow with an unknown parameter typo.

## Steps

### grandchild-writer

Writes using a typoed parameter name.

- type: write-file
- file_pat: gc.txt
- content: from grandchild
""",
        )

        middle = tmp_path / "middle.pflow.md"
        write_pflow_md(
            middle,
            """\
# Middle

Middle workflow that invokes grandchild.

## Steps

### invoke-grandchild

Invokes the grandchild workflow.

- type: workflow
- workflow: ./grandchild.pflow.md
""",
        )

        parent = tmp_path / "parent.pflow.md"
        write_pflow_md(
            parent,
            """\
# Parent

Parent workflow that invokes middle.

## Steps

### invoke-middle

Invokes the middle workflow.

- type: workflow
- workflow: ./middle.pflow.md
""",
        )

        registry = Registry()
        registry.load()

        diagnostics = WorkflowValidator.validate(
            workflow_ir={
                "ir_version": "0.1.0",
                "nodes": [
                    {
                        "id": "invoke-middle",
                        "type": "workflow",
                        "params": {"workflow": str(middle)},
                    }
                ],
                "edges": [],
            },
            extracted_params={},
            registry=registry,
            skip_node_types=False,
            workflow_file=parent,
        )

        errors = [d for d in diagnostics if d.severity == Severity.ERROR]
        unknown_param_errors = [d for d in errors if "file_pat" in d.message]
        assert len(unknown_param_errors) >= 1, f"Expected unknown-param error, got: {[d.message for d in errors]}"

        diagnostic = unknown_param_errors[0]
        context = diagnostic.context or {}

        # Message chains through both hops.
        assert "invoke-middle" in diagnostic.message
        assert "invoke-grandchild" in diagnostic.message

        # node_id and path point at the DEEPEST level (the grandchild's node).
        assert diagnostic.node_id == "grandchild-writer"
        assert context.get("path") == "nodes[id=grandchild-writer].params.file_pat"

        # sub_workflow_step / sub_workflow_path must be the INNERMOST hop
        # (closest to the error), not the outermost. This is the regression
        # guard against the overwrite bug.
        assert context.get("sub_workflow_step") == "invoke-grandchild"
        assert "grandchild.pflow.md" in str(context.get("sub_workflow_path", ""))


# ---------------------------------------------------------------------------
# 12. inputs mapping skips required-input check (fixes #239)
# ---------------------------------------------------------------------------


class TestInputsMappingRequiredCheck:
    """When a parent uses ``inputs`` to forward values to a child workflow,
    the validator should check key coverage for dict mappings and skip the
    check entirely for opaque string templates."""

    def test_inputs_dict_mapping_satisfies_required_check(self, tmp_path: Path) -> None:
        """Parent with inputs: {name: ..., value: ...} should satisfy child requirements."""
        child = tmp_path / "child.pflow.md"
        write_pflow_md(
            child,
            """\
# Child With Required Inputs

A child workflow requiring name and value.

## Inputs

### name

The name field for the child.

- type: string
- required: true

### value

The value field for the child.

- type: integer
- required: true

## Steps

### echo-it

Echo the provided input values.

- type: shell
- command: echo "${name}=${value}"
""",
        )

        parent_ir = _parent_ir(
            str(child),
            provided_params={"inputs": {"name": "${upstream.name}", "value": "${upstream.value}"}},
        )
        errors, _warnings = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            registry=None,
            skip_node_types=True,
        )
        missing_input_errors = [e for e in errors if "requires input" in e.message]
        assert missing_input_errors == [], f"False-positive missing-input errors: {missing_input_errors}"

    def test_inputs_dict_partial_coverage_detected(self, tmp_path: Path) -> None:
        """Parent with inputs: {name: ...} but child needs name AND value should error."""
        child = tmp_path / "child.pflow.md"
        write_pflow_md(
            child,
            """\
# Child With Required Inputs

A child workflow requiring name and value.

## Inputs

### name

The name field for the child.

- type: string
- required: true

### value

The value field for the child.

- type: integer
- required: true

## Steps

### echo-it

Echo the provided input values.

- type: shell
- command: echo "${name}=${value}"
""",
        )

        # Only provide 'name' via inputs, not 'value'
        parent_ir = _parent_ir(
            str(child),
            provided_params={"inputs": {"name": "${upstream.name}"}},
        )
        errors, _warnings = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            registry=None,
            skip_node_types=True,
        )
        missing_value_errors = [e for e in errors if "requires input 'value'" in e.message]
        assert len(missing_value_errors) == 1, f"Expected error for missing 'value', got: {errors}"
        # 'name' should NOT be flagged
        missing_name_errors = [e for e in errors if "requires input 'name'" in e.message]
        assert missing_name_errors == [], f"Unexpected error for 'name': {missing_name_errors}"

    def test_inputs_template_mapping_skips_required_check(self, tmp_path: Path) -> None:
        """Parent with inputs: '${item}' (opaque template) should skip required-input check."""
        child = tmp_path / "child.pflow.md"
        write_pflow_md(
            child,
            """\
# Child With Required Inputs

A child workflow requiring name and value.

## Inputs

### name

The name field for the child.

- type: string
- required: true

### value

The value field for the child.

- type: integer
- required: true

## Steps

### echo-it

Echo the provided input values.

- type: shell
- command: echo "${name}=${value}"
""",
        )

        parent_ir = _parent_ir(str(child), provided_params={"inputs": "${item}"})
        errors, _warnings = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            registry=None,
            skip_node_types=True,
        )
        missing_input_errors = [e for e in errors if "requires input" in e.message]
        assert missing_input_errors == [], f"False-positive missing-input errors: {missing_input_errors}"


# ---------------------------------------------------------------------------
# Bug A — undeclared extras at parent→child boundary (silent-drop fix)
# ---------------------------------------------------------------------------


class TestUndeclaredExtras:
    """Every value crossing the parent→child boundary must be declared on the child.

    Symmetric with the child-side rule ("Declared input(s) never used as template
    variable: X"). Before Bug A was fixed, extras were silently dropped —
    typos like ``lyric:`` vs ``lyrics:`` passed validate, ran, and produced
    wrong output that the user discovered in production.
    """

    def _child_with_inputs(self, path: Path, *input_names: str) -> None:
        """Write a child workflow declaring the given required inputs."""
        inputs_block = "\n\n".join(
            f"### {name}\n\nInput {name}.\n\n- type: string\n- required: true" for name in input_names
        )
        refs = " ".join(f"${{{name}}}" for name in input_names)
        write_pflow_md(
            path,
            f"# Child\n\nA child declaring {', '.join(input_names)}.\n\n"
            f"## Inputs\n\n{inputs_block}\n\n"
            f"## Steps\n\n### echo\n\nUse all declared inputs.\n\n- type: shell\n- command: echo {refs}\n",
        )

    def test_workflow_extras_top_level_rejected(self, tmp_path: Path) -> None:
        """Unknown top-level field on a workflow node is rejected by Step 7.

        The workflow node's ALLOWED_PARAMS is {workflow, inputs, error_action,
        storage_mode, max_depth}. Anything else at the top level → parse error
        with a "did you mean" suggestion, same as every other node type.
        """
        child = tmp_path / "child.pflow.md"
        self._child_with_inputs(child, "a")

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "call-child",
                    "type": "workflow",
                    "params": {
                        "workflow": str(child),
                        "inputs": {"a": "hello"},
                        "random_top_level_field": "oops",
                    },
                }
            ],
            "edges": [],
        }

        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        extras = [e for e in errors if "random_top_level_field" in e.message]
        assert len(extras) >= 1, f"Expected Step-7 diagnostic for unknown top-level field, got: {errors}"
        assert any("Unknown parameter" in e.message and "random_top_level_field" in e.message for e in extras), (
            f"Expected 'Unknown parameter' wording, got: {[e.message for e in extras]}"
        )
        # The diagnostic should name the allowed fields so the agent can recover.
        first = extras[0]
        assert first.context is not None
        available = first.context.get("available_fields", [])
        assert "inputs" in available and "workflow" in available, (
            f"ALLOWED_PARAMS should surface as available_fields, got: {available}"
        )

    def test_workflow_extras_in_inputs_rejected(self, tmp_path: Path) -> None:
        """Unknown key inside ``inputs:`` is rejected by the sub-workflow validator.

        This is the core Bug A fix: ``lyric:`` when the child declares
        ``lyrics:`` now fails at parse time with a fuzzy suggestion instead of
        being silently forwarded and dropped.
        """
        child = tmp_path / "child.pflow.md"
        self._child_with_inputs(child, "lyrics", "concept_brief")

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "call-child",
                    "type": "workflow",
                    "params": {
                        "workflow": str(child),
                        "inputs": {
                            "lyrics": "hello world",
                            "concept_brief": "a brief",
                            "lyric": "typo",  # typo — child declares `lyrics`
                        },
                    },
                }
            ],
            "edges": [],
        }

        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        typo_errors = [e for e in errors if "'lyric'" in e.message and "does not declare input" in e.message]
        assert len(typo_errors) == 1, (
            f"Expected exactly one extras diagnostic for 'lyric' typo, got: {[e.message for e in errors]}"
        )
        diagnostic = typo_errors[0]
        # Structured context surfaces declared inputs + fuzzy suggestion for agent recovery.
        assert diagnostic.suggestions and "lyrics" in diagnostic.suggestions[0], (
            f"Expected 'Did you mean lyrics' suggestion, got: {diagnostic.suggestions}"
        )
        assert diagnostic.context is not None
        declared = diagnostic.context.get("available_fields", [])
        assert "lyrics" in declared and "concept_brief" in declared, (
            f"Diagnostic should list child's declared inputs, got: {declared}"
        )

    def test_workflow_extras_with_template_inputs_deferred(self, tmp_path: Path) -> None:
        """When ``inputs:`` is an opaque template (e.g. ``${item}``), parse-time
        extras check is skipped — keys aren't statically knowable. Runtime
        defense-in-depth catches mismatches once the template resolves.
        """
        child = tmp_path / "child.pflow.md"
        self._child_with_inputs(child, "known_field")

        parent_ir = _parent_ir(str(child), provided_params={"inputs": "${item}"})
        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        # No parse-time extras errors — opaque template defers to runtime.
        extras_errors = [e for e in errors if "does not declare input" in e.message]
        assert extras_errors == [], (
            f"Opaque ``inputs: ${{item}}`` template should skip parse-time extras check, got: {extras_errors}"
        )
        # And no shape error either — a template isn't a literal shape violation.
        shape_errors = [e for e in errors if "must be a dict" in e.message]
        assert shape_errors == [], (
            f"Opaque template should not trigger the non-dict shape diagnostic, got: {shape_errors}"
        )


class TestNonDictInputsShape:
    """Parse-time rejection of literal non-dict ``inputs:`` values.

    The canonical form is ``inputs:`` as a mapping. A literal string,
    list, number, or bool in that slot is a shape typo. Before this check,
    such values silently produced a misleading "missing required" error
    downstream that blamed the child, not the parent's ``inputs:`` shape.
    Opaque templates (``inputs: ${item}``) are deferred to runtime because
    the resolved shape can't be checked statically.
    """

    def _child_with_one_input(self, path: Path) -> None:
        write_pflow_md(
            path,
            "# Child\n\nA child.\n\n"
            "## Inputs\n\n### known_field\n\nInput.\n\n- type: string\n- required: true\n\n"
            "## Steps\n\n### echo\n\nEcho.\n\n- type: shell\n- command: echo ${known_field}\n",
        )

    def test_non_dict_inputs_literal_string_rejected(self, tmp_path: Path) -> None:
        """A plain string in place of the ``inputs:`` dict is a shape error."""
        child = tmp_path / "child.pflow.md"
        self._child_with_one_input(child)

        parent_ir = _parent_ir(str(child), provided_params={"inputs": "not-a-dict"})
        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        shape_errors = [e for e in errors if "must be a dict" in e.message]
        assert len(shape_errors) == 1, f"Expected one shape error, got: {[e.message for e in errors]}"
        diagnostic = shape_errors[0]
        assert "str" in diagnostic.message, f"Error should name the actual type: {diagnostic.message}"
        assert diagnostic.context is not None
        assert diagnostic.context.get("actual_type") == "str"

    def test_non_dict_inputs_list_rejected(self, tmp_path: Path) -> None:
        """A list in place of the ``inputs:`` dict is a shape error."""
        child = tmp_path / "child.pflow.md"
        self._child_with_one_input(child)

        parent_ir = _parent_ir(str(child), provided_params={"inputs": ["a", "b"]})
        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        shape_errors = [e for e in errors if "must be a dict" in e.message]
        assert len(shape_errors) == 1, f"Expected one shape error, got: {[e.message for e in errors]}"
        assert shape_errors[0].context is not None
        assert shape_errors[0].context.get("actual_type") == "list"


class TestBatchItemValidation:
    """Inline-static batch items get the same parent→child boundary check as
    non-batch static calls.

    Motivating pattern: heterogeneous batch fan-out
    (``workflow: ${item.workflow}`` + ``inputs: ${item.inputs}`` + inline
    ``items:`` list with concrete child paths and input dicts). Before this
    fix, ``resolve_sub_workflow`` saw ``${item.workflow}`` and bailed — the
    entire batch silently skipped validation even though every per-item
    workflow ref and input dict was statically knowable from the IR.
    """

    def _child_declaring(self, path: Path, *input_names: str) -> None:
        inputs_block = "\n\n".join(
            f"### {name}\n\nInput {name}.\n\n- type: string\n- required: true" for name in input_names
        )
        refs = " ".join(f"${{{name}}}" for name in input_names)
        write_pflow_md(
            path,
            f"# Child\n\nA child declaring {', '.join(input_names)}.\n\n"
            f"## Inputs\n\n{inputs_block}\n\n"
            f"## Steps\n\n### echo\n\nEcho inputs.\n\n- type: shell\n- command: echo {refs}\n",
        )

    def _hetero_batch_ir(self, items: list, alias: str = "item") -> dict:
        """Parent IR using the guide's heterogeneous-batch pattern."""
        batch: dict = {"items": items, "parallel": False}
        if alias != "item":
            batch["as"] = alias
        return {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "call-child",
                    "type": "workflow",
                    "params": {
                        "workflow": f"${{{alias}.workflow}}",
                        "inputs": f"${{{alias}.inputs}}",
                    },
                    "batch": batch,
                }
            ],
            "edges": [],
        }

    def test_inline_item_undeclared_input_rejected(self, tmp_path: Path) -> None:
        """The motivating bug: ``extra_field`` in a static batch item is caught
        at parse time with a diagnostic pointing at the specific item.
        """
        child = tmp_path / "child.pflow.md"
        self._child_declaring(child, "message")

        parent_ir = self._hetero_batch_ir(
            items=[
                {
                    "workflow": str(child),
                    "inputs": {"message": "hello", "extra_field": "bad"},
                }
            ],
        )

        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        extras = [e for e in errors if "'extra_field'" in e.message and "does not declare input" in e.message]
        assert len(extras) == 1, f"Expected exactly one extras diagnostic, got: {[e.message for e in errors]}"
        diag = extras[0]
        assert diag.context is not None
        assert diag.context.get("batch_item_index") == 0, (
            f"Diagnostic must carry batch_item_index for agent recovery, got: {diag.context}"
        )
        assert diag.context.get("path") == "nodes[id=call-child].batch.items[0].inputs.extra_field", (
            f"Path should point at the item, got: {diag.context.get('path')}"
        )

    def test_inline_item_missing_required_rejected(self, tmp_path: Path) -> None:
        """Symmetric direction: missing required input in a static batch item."""
        child = tmp_path / "child.pflow.md"
        self._child_declaring(child, "message", "topic")

        parent_ir = self._hetero_batch_ir(
            items=[
                {
                    "workflow": str(child),
                    "inputs": {"message": "hello"},  # missing `topic`
                }
            ],
        )

        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        missing = [e for e in errors if "requires input 'topic'" in e.message]
        assert len(missing) == 1, f"Expected missing-required diagnostic, got: {[e.message for e in errors]}"
        assert missing[0].context is not None
        assert missing[0].context.get("batch_item_index") == 0
        # Path must point at the specific item's inputs dict, not at params.inputs —
        # guards a mutation where the batch-path switch is dropped for missing-required.
        assert missing[0].context.get("path") == "nodes[id=call-child].batch.items[0].inputs"

    def test_heterogeneous_batch_validates_each_child(self, tmp_path: Path) -> None:
        """Two items, two different children, different violations per item —
        each item produces its own diagnostic tagged with the right index."""
        child_a = tmp_path / "child-a.pflow.md"
        child_b = tmp_path / "child-b.pflow.md"
        self._child_declaring(child_a, "a_input")
        self._child_declaring(child_b, "b_input")

        parent_ir = self._hetero_batch_ir(
            items=[
                {"workflow": str(child_a), "inputs": {"a_input": "v", "wrong_a": "x"}},
                {"workflow": str(child_b), "inputs": {"b_input": "v", "wrong_b": "x"}},
            ],
        )

        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        by_index = {
            e.context.get("batch_item_index"): e for e in errors if e.context and "does not declare input" in e.message
        }
        assert 0 in by_index and 1 in by_index, f"Expected diagnostics for both items, got indexes: {list(by_index)}"
        assert "'wrong_a'" in by_index[0].message
        assert "'wrong_b'" in by_index[1].message
        # see_also must survive batch + sub-workflow composition (dataclasses.replace
        # inside _add_child_provenance preserves it; regression pin for issue #311).
        assert by_index[0].see_also == ["sub-workflows"]
        assert by_index[1].see_also == ["sub-workflows"]

    def test_items_template_deferred(self, tmp_path: Path) -> None:
        """``items:`` as a template string (dynamic items from an upstream node)
        cannot be statically enumerated — defer the whole batch to runtime.
        """
        child = tmp_path / "child.pflow.md"
        self._child_declaring(child, "message")

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "call-child",
                    "type": "workflow",
                    "params": {
                        "workflow": "${item.workflow}",
                        "inputs": "${item.inputs}",
                    },
                    "batch": {"items": "${upstream.files}", "parallel": False},
                }
            ],
            "edges": [],
        }

        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        extras_errors = [e for e in errors if "does not declare input" in e.message]
        assert extras_errors == [], (
            f"Template-items batch should defer to runtime, got parse-time errors: {extras_errors}"
        )

    def test_mixed_static_and_template_items(self, tmp_path: Path) -> None:
        """Item 0 is fully static (bug → caught); item 1 has a template
        workflow ref (ref unresolvable → defer). Only the static item fires."""
        child = tmp_path / "child.pflow.md"
        self._child_declaring(child, "message")

        parent_ir = self._hetero_batch_ir(
            items=[
                {"workflow": str(child), "inputs": {"message": "hi", "bad_key": "x"}},
                # Item 1: workflow is a template referring outside the item ctx
                {"workflow": "${upstream.wf}", "inputs": {"message": "hi"}},
            ],
        )

        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        extras = [e for e in errors if "'bad_key'" in e.message]
        assert len(extras) == 1
        assert extras[0].context and extras[0].context.get("batch_item_index") == 0

        # No "does not declare" diagnostic for item 1 — ref unresolvable, deferred.
        other = [
            e
            for e in errors
            if e.context and e.context.get("batch_item_index") == 1 and "does not declare" in e.message
        ]
        assert other == []

    def test_custom_alias_honored(self, tmp_path: Path) -> None:
        """Custom ``batch.as:`` alias (e.g. ``songitem``) is used as the binding
        key in ``${alias.*}`` templates, matching runtime behavior."""
        child = tmp_path / "child.pflow.md"
        self._child_declaring(child, "message")

        parent_ir = self._hetero_batch_ir(
            items=[{"workflow": str(child), "inputs": {"message": "hi", "stray": "x"}}],
            alias="songitem",
        )

        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        extras = [e for e in errors if "'stray'" in e.message]
        assert len(extras) == 1, (
            f"Custom alias should bind ${{songitem.workflow}} → items[i]['workflow'], got: {[e.message for e in errors]}"
        )

    def test_invariant_inputs_batch_path_points_at_params_not_items(self, tmp_path: Path) -> None:
        """When ``params.inputs`` is a literal dict (not per-item), the bug is
        invariant across iterations — the diagnostic path must point at
        ``params.inputs.X``, not ``batch.items[0].inputs.X``. Otherwise dedup
        collapses N identical diagnostics into one misleadingly tagged to
        iteration 0.
        """
        child = tmp_path / "child.pflow.md"
        self._child_declaring(child, "message")

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "call-child",
                    "type": "workflow",
                    "params": {
                        "workflow": "${item}",  # item is scalar path
                        "inputs": {"message": "hi", "bad_key": "typo"},  # literal dict, not ${item.inputs}
                    },
                    "batch": {"items": [str(child), str(child)], "parallel": False},
                }
            ],
            "edges": [],
        }

        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        extras = [e for e in errors if "'bad_key'" in e.message]
        assert len(extras) == 1, (
            f"Invariant-inputs bug repeats across N iterations; dedup collapses to 1, got: {[e.message for e in errors]}"
        )
        diag = extras[0]
        assert diag.context is not None
        assert diag.context.get("path") == "nodes[id=call-child].params.inputs.bad_key", (
            f"Path must point at params.inputs (where the author wrote the bug), got: {diag.context.get('path')}"
        )
        assert "batch_item_index" not in (diag.context or {}), (
            f"Invariant-inputs bug shouldn't be tagged to any specific iteration, got: {diag.context}"
        )

    def test_two_items_same_bug_both_survive_runner_dedup(self, tmp_path: Path) -> None:
        """Regression for the dedup-collapse trap: two batch items failing in
        exactly the same way (same child, same undeclared key) must produce
        two distinct user-visible diagnostics after the runner's
        ``deduplicate_diagnostics`` pass. Without the per-item ``batch.items[N]``
        prefix in the message, ``Diagnostic.__hash__`` (which excludes context)
        collapses them into one — the user fixes item 0, reruns, then discovers
        item 1 was also broken.
        """
        from pflow.execution.runner import WorkflowRunner

        child = tmp_path / "child.pflow.md"
        self._child_declaring(child, "message")

        parent = tmp_path / "parent.pflow.md"
        parent.write_text(
            "# Parent\n\n"
            "## Steps\n\n"
            "### call-child\n\n"
            "Call child twice with same undeclared extra.\n\n"
            "- type: workflow\n"
            "- workflow: ${item.workflow}\n"
            "- inputs: ${item.inputs}\n\n"
            "```yaml batch\n"
            "items:\n"
            f"  - workflow: {child}\n"
            "    inputs:\n"
            '      message: "hi"\n'
            '      extra_field: "bad"\n'
            f"  - workflow: {child}\n"
            "    inputs:\n"
            '      message: "hi"\n'
            '      extra_field: "bad"\n'
            "parallel: false\n"
            "```\n\n"
            "## Outputs\n\n"
            "### result\n\n"
            "Output.\n\n"
            "- source: ${call-child.results[0].echoed}\n",
            encoding="utf-8",
        )

        vresult = WorkflowRunner().validate(str(parent), {})

        extras = [e for e in vresult.errors if "'extra_field'" in e.message and "does not declare" in e.message]
        assert len(extras) == 2, (
            f"Both items must remain visible after runner dedup; got {len(extras)} "
            f"extras diagnostic(s). All errors: {[e.message for e in vresult.errors]}"
        )
        # Distinct diagnostics tagged to distinct items
        indices = sorted(e.context.get("batch_item_index") for e in extras if e.context)
        assert indices == [0, 1], f"Expected batch_item_index 0 and 1, got: {indices}"
        # Core invariant: two distinct ``Diagnostic.__hash__`` buckets so the
        # runner's ``deduplicate_diagnostics`` can't collapse them. Assert on
        # hash identity rather than message substring so the test stays green
        # across harmless message-format refactors but fails the moment two
        # items produce the same hash (the bug the reviewer flagged).
        assert len({hash(e) for e in extras}) == 2, (
            f"Expected two distinct diagnostic hashes for the two items; got one — "
            f"dedup would collapse them. Messages: {[e.message for e in extras]}"
        )

    def test_item_load_error_carries_batch_item_index(self, tmp_path: Path) -> None:
        """A broken workflow ref inside ``batch.items[N]`` surfaces the index
        in the diagnostic context so an agent can locate the offending item.
        """
        good_child = tmp_path / "good.pflow.md"
        self._child_declaring(good_child, "message")

        parent_ir = self._hetero_batch_ir(
            items=[
                {"workflow": str(good_child), "inputs": {"message": "hi"}},
                {"workflow": str(tmp_path / "does-not-exist.pflow.md"), "inputs": {"message": "hi"}},
            ],
        )

        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        load_errors = [e for e in errors if "Sub-workflow file not found" in e.message or "failed to load" in e.message]
        assert len(load_errors) == 1, (
            f"Expected one load error for the missing child, got: {[e.message for e in errors]}"
        )
        assert load_errors[0].context is not None
        assert load_errors[0].context.get("batch_item_index") == 1, (
            f"Load-error diagnostic must carry batch_item_index, got: {load_errors[0].context}"
        )

    def test_hetero_workflows_with_invariant_inputs_checks_each_child(self, tmp_path: Path) -> None:
        """Regression for the ``inputs_check_done`` silent-bypass: when
        ``params.workflow`` varies per item but ``params.inputs`` is a literal
        dict, the invariant-inputs key set still has to be validated against
        EACH child — not just the first. Child A may declare exactly those
        keys while Child B declares something completely different.

        Before the fix, iter 0 validated against child_a (clean), iter 1
        short-circuited, and child_b's undeclared/missing violations were
        invisible until runtime.
        """
        child_a = tmp_path / "child-a.pflow.md"
        child_b = tmp_path / "child-b.pflow.md"
        self._child_declaring(child_a, "x")
        self._child_declaring(child_b, "y")

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "call",
                    "type": "workflow",
                    "params": {
                        "workflow": "${item.workflow}",
                        "inputs": {"x": "v"},  # literal, invariant across items
                    },
                    "batch": {
                        "items": [
                            {"workflow": str(child_a)},  # declares x ✓
                            {"workflow": str(child_b)},  # declares y only — x is extra, y missing
                        ],
                        "parallel": False,
                    },
                }
            ],
            "edges": [],
        }

        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        # child_b's contract is violated in both directions — x is extra, y is missing.
        b_extras = [e for e in errors if "'x'" in e.message and "does not declare" in e.message]
        b_missing = [e for e in errors if "requires input 'y'" in e.message]
        assert b_extras, (
            f"child_b's undeclared-extra 'x' must be caught at parse time — "
            f"silent bypass would show up as no extras diagnostic. All errors: "
            f"{[e.message for e in errors]}"
        )
        assert b_missing, (
            f"child_b's missing-required 'y' must be caught at parse time. All errors: {[e.message for e in errors]}"
        )
        # child_a is clean (x is exactly its declared input) — no diagnostic for it.
        a_errors = [e for e in errors if "child-a" in e.message]
        assert a_errors == [], f"child_a satisfies its contract; expected no errors, got: {a_errors}"

    def test_nested_batch_grandchild_bug_caught_with_provenance(self, tmp_path: Path) -> None:
        """Parent batch → child batch → grandchild with undeclared-input bug.
        Validator recurses through both batch layers; the deepest diagnostic
        carries the grandchild's ``batch.items[N]`` path AND the parent-step
        provenance (``In step 'X' sub-workflow:`` prefix).
        """
        from pflow.execution.runner import WorkflowRunner

        grandchild = tmp_path / "grandchild.pflow.md"
        self._child_declaring(grandchild, "greeting")

        middle = tmp_path / "middle.pflow.md"
        middle.write_text(
            "# Middle\n\nA middle workflow batching the grandchild.\n\n"
            "## Inputs\n\n### topic\n\nTopic.\n\n- type: string\n- required: true\n\n"
            "## Steps\n\n### fan-out\n\nFan out to grandchild.\n\n"
            "- type: workflow\n"
            "- workflow: ${item.workflow}\n"
            "- inputs: ${item.inputs}\n\n"
            "```yaml batch\n"
            "items:\n"
            f"  - workflow: {grandchild}\n"
            "    inputs:\n"
            '      wrong_grandchild_key: "bad"\n'
            "parallel: false\n"
            "```\n\n"
            "## Outputs\n\n### result\n\nResult.\n\n- source: ${fan-out.results[0].echoed}\n",
            encoding="utf-8",
        )

        parent = tmp_path / "parent.pflow.md"
        parent.write_text(
            "# Parent\n\n## Steps\n\n### call-middle\n\nCall middle.\n\n"
            "- type: workflow\n"
            "- workflow: ${item.workflow}\n"
            "- inputs: ${item.inputs}\n\n"
            "```yaml batch\n"
            "items:\n"
            f"  - workflow: {middle}\n"
            '    inputs: {topic: "T"}\n'
            "parallel: false\n"
            "```\n\n"
            "## Outputs\n\n### result\n\nResult.\n\n- source: ${call-middle.results[0].result}\n",
            encoding="utf-8",
        )

        vresult = WorkflowRunner().validate(str(parent), {})

        # Grandchild's undeclared-key bug surfaces through 2 levels of batch recursion.
        grand_errors = [e for e in vresult.errors if "wrong_grandchild_key" in e.message]
        assert len(grand_errors) == 1, (
            f"Expected grandchild bug surfaced via nested batch, got: {[e.message for e in vresult.errors]}"
        )
        # Provenance includes the deepest step (grandchild caller) wrapped by the
        # middle step's ``In step 'call-middle' sub-workflow:`` prefix.
        assert "call-middle" in grand_errors[0].message
        assert grand_errors[0].context is not None
        assert grand_errors[0].context.get("batch_item_index") == 0
        # Three-way interaction: see_also survives both batch-layer wraps via
        # _add_child_provenance's dataclasses.replace (regression pin for #311).
        assert grand_errors[0].see_also == ["sub-workflows"]

    def test_custom_alias_via_markdown_round_trip(self, tmp_path: Path) -> None:
        """Custom ``as: songitem`` written in actual markdown (not raw IR) wires
        up correctly through the parser → validator pipeline.
        """
        from pflow.execution.runner import WorkflowRunner

        child = tmp_path / "child.pflow.md"
        self._child_declaring(child, "message")

        parent = tmp_path / "parent.pflow.md"
        parent.write_text(
            "# Parent\n\n## Steps\n\n### call-child\n\nCall child with custom alias.\n\n"
            "- type: workflow\n"
            "- workflow: ${songitem.workflow}\n"
            "- inputs: ${songitem.inputs}\n\n"
            "```yaml batch\n"
            "as: songitem\n"
            "items:\n"
            f"  - workflow: {child}\n"
            "    inputs:\n"
            '      message: "hi"\n'
            '      stray_field: "bad"\n'
            "parallel: false\n"
            "```\n\n"
            "## Outputs\n\n### result\n\nResult.\n\n- source: ${call-child.results[0].echoed}\n",
            encoding="utf-8",
        )

        vresult = WorkflowRunner().validate(str(parent), {})
        extras = [e for e in vresult.errors if "'stray_field'" in e.message]
        assert len(extras) == 1, (
            f"Custom alias via markdown must bind ${{songitem.workflow}} → items[i]['workflow']; "
            f"got: {[e.message for e in vresult.errors]}"
        )
        assert extras[0].context.get("batch_item_index") == 0

    def test_empty_items_list_with_alias_refs_skips_validation(self, tmp_path: Path) -> None:
        """Documenting intended behavior: when ``items: []`` (empty inline list)
        AND ``params.workflow``/``inputs`` reference the alias, the enumerator
        yields zero child calls — matching runtime's "empty batch runs nothing"
        semantics. No validation fires for the referenced child. If this ever
        changes (e.g. to surface child-file parse errors proactively), this
        test should fail and the design decision re-examined.
        """
        child = tmp_path / "child.pflow.md"
        self._child_declaring(child, "message")

        parent_ir = self._hetero_batch_ir(items=[])
        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )
        # No child-related diagnostics — not loaded, not validated.
        sub_errors = [e for e in errors if e.context and e.context.get("sub_workflow_path")]
        assert sub_errors == [], (
            f"Empty items list with alias refs should skip child validation; got: {[e.message for e in sub_errors]}"
        )

    @pytest.mark.parametrize("alias", ["__index__", "workflow", "inputs", "item", "i"])
    def test_alias_collision_with_reserved_keys_does_not_crash(self, tmp_path: Path, alias: str) -> None:
        """Custom ``as:`` aliases that collide with reserved / framework keys
        (``__index__``, ``workflow``, ``inputs``) or single-character names
        (``i``) must not crash the validator. Behavioral parity with runtime
        for these edge cases is out of scope — this test pins "doesn't crash"
        as the load-bearing invariant so future alias-handling changes don't
        silently regress it.
        """
        child = tmp_path / "child.pflow.md"
        self._child_declaring(child, "message")

        parent_ir = self._hetero_batch_ir(
            items=[{"workflow": str(child), "inputs": {"message": "hi"}}],
            alias=alias,
        )

        # The contract is "this call succeeds and returns a list of diagnostics";
        # any unhandled exception would be a regression.
        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )
        assert isinstance(errors, list)

    def test_scalar_items_workflow_template_no_false_positive(self, tmp_path: Path) -> None:
        """Items that are plain strings (``items: ["./child.pflow.md"]`` with
        ``workflow: ${item}``) resolve the workflow ref but inputs stays as the
        raw ``${item.inputs}`` template — opaque → defer, no false extras.
        """
        child = tmp_path / "child.pflow.md"
        self._child_declaring(child, "message")

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "call-child",
                    "type": "workflow",
                    "params": {
                        "workflow": "${item}",
                        "inputs": "${item.inputs}",  # won't resolve — scalar item has no .inputs
                    },
                    "batch": {"items": [str(child)], "parallel": False},
                }
            ],
            "edges": [],
        }

        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        # Opaque inputs → no extras diagnostic; no missing-required (child path
        # loaded successfully so "failed to load" shouldn't fire either).
        assert [e for e in errors if "does not declare input" in e.message] == []
        assert [e for e in errors if "requires input" in e.message] == []


class TestSubWorkflowDiagnosticsCarrySeeAlso:
    """All three rule-class sub-workflow diagnostics point at the sub-workflows guide.

    The parent→child input boundary is the structural pattern the guide explains.
    These diagnostics teach the pattern, not just the one-off fix, so they earn
    the ``see_also`` pointer.
    """

    def _child_with_one_input(self, path: Path) -> None:
        write_pflow_md(
            path,
            "# Child\n\nA child.\n\n"
            "## Inputs\n\n### known_field\n\nInput.\n\n- type: string\n- required: true\n\n"
            "## Steps\n\n### echo\n\nEcho.\n\n- type: shell\n- command: echo ${known_field}\n",
        )

    def test_non_dict_inputs_diagnostic_see_also_sub_workflows(self, tmp_path: Path) -> None:
        child = tmp_path / "child.pflow.md"
        self._child_with_one_input(child)

        parent_ir = _parent_ir(str(child), provided_params={"inputs": "not-a-dict"})
        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        shape_errors = [e for e in errors if "must be a dict" in e.message]
        assert shape_errors and shape_errors[0].see_also == ["sub-workflows"]

    def test_missing_required_input_diagnostic_see_also_sub_workflows(self, tmp_path: Path) -> None:
        child = tmp_path / "child.pflow.md"
        self._child_with_one_input(child)

        # Provide inputs dict missing the required 'known_field'
        parent_ir = _parent_ir(str(child), provided_params={"inputs": {}})
        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        missing_errors = [e for e in errors if "requires input" in e.message]
        assert missing_errors and missing_errors[0].see_also == ["sub-workflows"]

    def test_undeclared_extras_diagnostic_see_also_sub_workflows(self, tmp_path: Path) -> None:
        child = tmp_path / "child.pflow.md"
        self._child_with_one_input(child)

        # Provide all required keys plus an extra
        parent_ir = _parent_ir(
            str(child),
            provided_params={"inputs": {"known_field": "ok", "extra_key": "nope"}},
        )
        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        extras = [e for e in errors if "does not declare input" in e.message]
        assert extras and extras[0].see_also == ["sub-workflows"]

    def test_child_parse_error_preserves_see_also_through_wrap(self, tmp_path: Path) -> None:
        """Grandchild's MarkdownParseError see_also survives the load-failure wrap.

        Regression guard: _load_child_workflow catches any Exception raised by
        the child parser, stringifies the error text into a new Diagnostic
        message, and previously dropped the inner exception's see_also. A
        grandchild routing error carries ``see_also=['branching']``; the
        wrapped parent-level diagnostic must carry the same list.
        """
        # Grandchild has a routing error (raises MarkdownParseError with
        # see_also=["branching"])
        grandchild = tmp_path / "grandchild.pflow.md"
        write_pflow_md(
            grandchild,
            "# GC\n\nA grandchild.\n\n## Steps\n\n"
            "### router\n\nRoute dynamically.\n\n- type: code\n\n"
            '```python code\nnext = "a"\nresult: int = 0\n```\n\n'
            "### a\n\nDownstream.\n\n- type: shell\n\n"
            "```shell command\necho a\n```\n",
        )

        parent_ir = _parent_ir(str(grandchild))
        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            workflow_file=tmp_path / "parent.pflow.md",
            skip_node_types=True,
        )

        load_errors = [e for e in errors if "routing target" in e.message]
        assert load_errors, f"Expected wrapped grandchild routing error, got: {[e.message for e in errors]}"
        assert load_errors[0].see_also == ["branching"], f"see_also lost through load-failure wrap: {load_errors[0]}"

    def test_saved_name_child_parse_error_preserves_see_also(self) -> None:
        """Saved-name reference: see_also survives the ``WorkflowValidationError`` wrap.

        Regression guard for the saved-name variant of the load-failure wrap.
        ``WorkflowManager.load_ir()`` catches ``MarkdownParseError`` and wraps
        it in ``WorkflowValidationError(validation_errors=e.to_diagnostics())``.
        The fix in ``_load_child_workflow`` must look inside
        ``e.validation_errors[0].see_also`` for this path since the outer
        ``WorkflowValidationError`` has no ``see_also`` attribute of its own.
        """
        from pflow.core.workflow.manager import WorkflowManager

        # Save a workflow with a routing error. WorkflowManager.save() only
        # validates the name, not the content, so this succeeds.
        md_content = (
            "# Broken\n\nA saved workflow with a routing error.\n\n## Steps\n\n"
            "### router\n\nDynamic route.\n\n- type: code\n\n"
            '```python code\nnext = "a"\nresult: int = 0\n```\n\n'
            "### a\n\nDownstream.\n\n- type: shell\n\n"
            "```shell command\necho a\n```\n"
        )

        wm = WorkflowManager()
        wm.save("broken-saved-branching", md_content)

        # Parent references it by saved name.
        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "saved-ref",
                    "type": "workflow",
                    "params": {"workflow": "broken-saved-branching"},
                }
            ],
            "edges": [],
        }
        errors, _ = split_validator_diagnostics(
            workflow_ir=parent_ir,
            extracted_params={},
            skip_node_types=True,
        )

        # Note: the WorkflowManager.load_ir() wrap produces
        # ``str(WorkflowValidationError) == "Invalid workflow '<name>'"`` —
        # the inner routing detail is NOT embedded in the message (that's
        # pre-existing, separate from see_also). What MUST survive is the
        # guide pointer itself, extracted from ``e.validation_errors[0]``.
        load_errors = [e for e in errors if "Invalid workflow" in e.message and "broken-saved-branching" in e.message]
        assert load_errors, f"Expected wrapped saved-name error, got: {[e.message for e in errors]}"
        assert load_errors[0].see_also == ["branching"], (
            f"see_also lost through WorkflowValidationError wrap: {load_errors[0]}"
        )
