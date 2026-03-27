"""Tests for WorkflowValidator._validate_sub_workflows() (step 8).

Validates recursive sub-workflow validation: parse error bubbling, required
input checking, cycle detection, inline IR validation, and saved workflow
name resolution.
"""

from pathlib import Path

from pflow.core.workflow.validator import WorkflowValidator
from pflow.registry import Registry


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
        params.update(provided_params)
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
        errors, _warnings = WorkflowValidator.validate(
            workflow_ir=parent_ir,
            extracted_params={"_pflow_workflow_file": str(tmp_path / "parent.pflow.md")},
            registry=None,
            skip_node_types=True,
        )

        # Parser should complain about the missing description
        assert any("missing a description" in e.lower() for e in errors), (
            f"Expected 'missing a description' error, got: {errors}"
        )
        # Error should mention it comes from a sub-workflow
        assert any("sub-workflow" in e.lower() or "in sub-workflow" in e.lower() for e in errors), (
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
        errors, _warnings = WorkflowValidator.validate(
            workflow_ir=parent_ir,
            extracted_params={"_pflow_workflow_file": str(tmp_path / "parent.pflow.md")},
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
        errors, _warnings = WorkflowValidator.validate(
            workflow_ir=parent_ir,
            extracted_params={"_pflow_workflow_file": str(tmp_path / "parent.pflow.md")},
            registry=None,
            skip_node_types=True,
        )

        # Should see the grandchild parse error
        assert any("missing a description" in e.lower() for e in errors), (
            f"Expected grandchild parse error, got: {errors}"
        )
        # Error attribution should show nesting: both middle and grandchild mentioned
        nested_errors = [e for e in errors if "sub-workflow" in e.lower()]
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
        errors, _warnings = WorkflowValidator.validate(
            workflow_ir=parent_ir,
            extracted_params={"_pflow_workflow_file": str(tmp_path / "parent.pflow.md")},
            registry=None,
            skip_node_types=True,
        )

        # Cycles are gracefully skipped — no "infinite" error expected
        # There should be no error specifically about the cycle
        cycle_errors = [e for e in errors if "cycle" in e.lower() or "circular" in e.lower() or "infinite" in e.lower()]
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
        errors, _warnings = WorkflowValidator.validate(
            workflow_ir=parent_ir,
            extracted_params={"_pflow_workflow_file": str(tmp_path / "parent.pflow.md")},
            registry=None,
            skip_node_types=True,
        )

        assert any("count" in e for e in errors), f"Expected missing 'count' error, got: {errors}"
        # 'text' is provided, so it should NOT be flagged
        missing_text_errors = [e for e in errors if "input 'text'" in e and "not provided" in e]
        assert missing_text_errors == [], f"'text' should not be flagged as missing: {errors}"


# ---------------------------------------------------------------------------
# 6. Template workflow reference gracefully skipped
# ---------------------------------------------------------------------------


class TestTemplateWorkflowRef:
    def test_template_workflow_ref_skipped(self, tmp_path: Path) -> None:
        """When the workflow param is a template like ${dynamic_path}, the
        validator cannot resolve it statically and should skip it gracefully."""
        parent_ir = _parent_ir("${dynamic_path}")
        errors, _warnings = WorkflowValidator.validate(
            workflow_ir=parent_ir,
            extracted_params={"_pflow_workflow_file": str(tmp_path / "parent.pflow.md")},
            registry=None,
            skip_node_types=True,
        )

        # No sub-workflow errors from the template reference
        sub_wf_errors = [e for e in errors if "sub-workflow" in e.lower()]
        assert sub_wf_errors == [], f"Template ref should be skipped, got: {sub_wf_errors}"


# ---------------------------------------------------------------------------
# 7. Inline workflow_ir validated
# ---------------------------------------------------------------------------


class TestInlineWorkflowIR:
    def test_inline_workflow_ir_validated(self) -> None:
        """When a workflow node uses an inline workflow_ir dict, the validator
        should recurse into it and catch errors (e.g., circular data flow)."""
        broken_child_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "a", "type": "test", "params": {"data": "${b.output}"}},
                {"id": "b", "type": "test", "params": {"data": "${a.output}"}},
            ],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "a"},
            ],
        }

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "inline-child",
                    "type": "workflow",
                    "params": {
                        "workflow_ir": broken_child_ir,
                    },
                }
            ],
            "edges": [],
        }

        errors, _warnings = WorkflowValidator.validate(
            workflow_ir=parent_ir,
            extracted_params={},
            registry=None,
            skip_node_types=True,
        )

        # Should catch the circular dependency from the inline IR
        assert any("circular" in e.lower() for e in errors), (
            f"Expected circular dependency error from inline IR, got: {errors}"
        )
        # Error should be attributed to the sub-workflow
        assert any("sub-workflow" in e.lower() for e in errors), f"Expected sub-workflow attribution, got: {errors}"


# ---------------------------------------------------------------------------
# 8. Saved workflow name validated
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

        errors, _warnings = WorkflowValidator.validate(
            workflow_ir=parent_ir,
            extracted_params={},
            registry=None,
            skip_node_types=True,
        )

        # The saved child's forward-reference error should surface
        assert any("after" in e.lower() or "forward" in e.lower() for e in errors), (
            f"Expected forward-reference error from saved child, got: {errors}"
        )
        assert any("sub-workflow" in e.lower() for e in errors), f"Expected sub-workflow attribution, got: {errors}"


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

        errors, _warnings = WorkflowValidator.validate(
            workflow_ir=parent_ir,
            extracted_params={"_pflow_workflow_file": str(tmp_path / "parent.pflow.md")},
            registry=registry,
            skip_node_types=False,
        )

        assert any("unknown node type" in e.lower() for e in errors), f"Expected unknown node type error, got: {errors}"
        assert any("totally-fake-node-type" in e for e in errors), (
            f"Expected 'totally-fake-node-type' in error, got: {errors}"
        )


# ---------------------------------------------------------------------------
# 10. Sub-workflow data flow error caught
# ---------------------------------------------------------------------------


class TestSubWorkflowDataFlowError:
    def test_sub_workflow_data_flow_error_caught(self, tmp_path: Path) -> None:
        """A child workflow with circular edges (A -> B -> A) should produce
        a data-flow error visible in the parent's validation."""
        child = tmp_path / "circular-child.pflow.md"
        # Write a child with circular next routing to produce a cycle
        write_pflow_md(
            child,
            """\
# Circular Child

A child with circular dependencies.

## Steps

### step-a

First step that references output of step-b.

- type: shell
- command: echo ${step-b.stdout}
- next: step-b

### step-b

Second step that references output of step-a.

- type: shell
- command: echo ${step-a.stdout}
- next: step-a
""",
        )

        parent_ir = _parent_ir(str(child))
        errors, _warnings = WorkflowValidator.validate(
            workflow_ir=parent_ir,
            extracted_params={"_pflow_workflow_file": str(tmp_path / "parent.pflow.md")},
            registry=None,
            skip_node_types=True,
        )

        assert any("circular" in e.lower() for e in errors), (
            f"Expected circular dependency error from child, got: {errors}"
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
        errors, _warnings = WorkflowValidator.validate(
            workflow_ir=parent_ir,
            extracted_params={"_pflow_workflow_file": str(tmp_path / "parent.pflow.md")},
            registry=None,
            skip_node_types=True,
        )

        missing_input_errors = [e for e in errors if "maybe-param" in e and "not provided" in e]
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

        errors, _warnings = WorkflowValidator.validate(
            workflow_ir=parent_ir,
            extracted_params={"_pflow_workflow_file": str(tmp_path / "parent.pflow.md")},
            registry=None,
            skip_node_types=True,
        )

        assert any("not found" in e.lower() for e in errors), f"Expected 'file not found' error, got: {errors}"
        assert any("does-not-exist.pflow.md" in e for e in errors), (
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
                    "params": {"workflow": str(child), "text": "hello", "count": "5"},
                },
                {
                    "id": "step-b",
                    "type": "workflow",
                    "params": {"workflow": str(child), "text": "world"},
                    # Missing "count" — should be caught
                },
            ],
            "edges": [{"from": "step-a", "to": "step-b"}],
        }

        errors, _ = WorkflowValidator.validate(
            workflow_ir=parent_ir,
            extracted_params={"_pflow_workflow_file": str(tmp_path / "parent.pflow.md")},
            skip_node_types=True,
        )

        # step-a should pass (provides both text and count)
        assert not any("step-a" in e.lower() and "not provided" in e for e in errors), (
            f"step-a should not have missing input errors: {errors}"
        )
        # step-b should fail (missing count)
        assert any("step-b" in e and "count" in e and "not provided" in e for e in errors), (
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
            f"- type: workflow\n- workflow: {grandchild}\n- text: hello\n- count: 5\n",
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
                    "params": {"workflow": str(grandchild), "text": "world"},
                    # Missing "count" — must be caught even though grandchild
                    # was already validated during child's recursion
                },
            ],
            "edges": [{"from": "via-child", "to": "direct-grandchild"}],
        }

        errors, _ = WorkflowValidator.validate(
            workflow_ir=parent_ir,
            extracted_params={"_pflow_workflow_file": str(tmp_path / "parent.pflow.md")},
            skip_node_types=True,
        )

        assert any("direct-grandchild" in e and "count" in e and "not provided" in e for e in errors), (
            f"Expected missing 'count' error for direct-grandchild, got: {errors}"
        )
