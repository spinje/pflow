"""Template variable validation for workflow execution.

This module is the orchestrator for template validation. It runs all
validation passes in sequence and aggregates errors/warnings.

Validation passes are split by concern into separate modules:
- path_validation: Pass 5 (path existence)
- type_validation: Passes 6+7+9 (type matching, shell command types, code-node annotations)
- batch_item_validation: Pass 8 (${item.field} validation)
- utils: Shared infrastructure

This module owns:
- The main entry point (validate_workflow_templates)
- Output extraction (building the node_outputs dict)
- Template extraction
- Simple passes (malformed syntax, unused inputs)
"""

import logging
import re
from collections.abc import Iterator
from typing import Any

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.suggestion_utils import find_similar_items
from pflow.registry import Registry
from pflow.runtime.template_resolver import TemplateResolver
from pflow.runtime.template_validation.batch_item_validation import validate_batch_item_fields
from pflow.runtime.template_validation.path_validation import validate_template_paths
from pflow.runtime.template_validation.type_validation import (
    validate_code_node_input_annotations,
    validate_shell_command_types,
    validate_template_types,
)
from pflow.runtime.template_validation.utils import get_node_ids

__all__ = ["extract_node_outputs", "validate_workflow_templates"]

logger = logging.getLogger(__name__)

# More permissive pattern to catch malformed templates for validation
# Supports array notation: ${node[0].field}, ${node.field[0].subfield}
# Also supports nested index templates: ${node[${__index__}].field}
# Also supports coalesce operator: ${a.field ?? b.field}
# Also supports literal operands (Optional A): ${a ?? 0}, ${a ?? "x"}, ${0}
_PERM_VAR = r"[a-zA-Z_][\w-]*(?:(?:\[(?:[\d]+|\$\{[^}]+\})\])?(?:\.[\w-]*(?:\[(?:[\d]+|\$\{[^}]+\})\])?)*)?"
# A coalesce operand is a literal OR a variable path. Literal sub-grammar is the
# same one runtime resolution uses (kept in sync via TemplateResolver).
_PERM_OPERAND = rf"(?:{TemplateResolver._LITERAL_PATTERN}|{_PERM_VAR})"
_PERMISSIVE_PATTERN = re.compile(rf"\$\{{({_PERM_OPERAND}(?:\s*\?\?\s*{_PERM_OPERAND})*)\}}")

# Batch output definitions matching PflowBatchNode.post() structure
BATCH_OUTPUTS: list[dict[str, str]] = [
    {"key": "results", "type": "array", "description": "Array of successful results (failed items filtered out)"},
    {"key": "count", "type": "number", "description": "Total items processed"},
    {"key": "success_count", "type": "number", "description": "Items that succeeded"},
    {"key": "error_count", "type": "number", "description": "Items that failed"},
    {"key": "errors", "type": "array", "description": "Error details (empty array when no failures)"},
    {"key": "batch_metadata", "type": "dict", "description": "Execution statistics"},
]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def validate_workflow_templates(
    workflow_ir: dict[str, Any], available_params: dict[str, Any], registry: Registry
) -> list[Diagnostic]:
    """
    Validates all template variables in a workflow.

    Uses the registry to determine which variables are written by nodes
    and validates that all template paths exist in the node outputs.
    Also validates that all declared inputs are actually used.

    Args:
        workflow_ir: The workflow IR containing nodes with template parameters
        available_params: Parameters available from workflow inputs or CLI
        registry: Registry instance with parsed node metadata

    Returns:
        Validation diagnostics. Severity distinguishes errors from warnings.
    """
    diagnostics: list[Diagnostic] = []

    # Check for malformed template syntax FIRST
    malformed_diagnostics = _validate_malformed_templates(workflow_ir)
    diagnostics.extend(malformed_diagnostics)

    # If malformed syntax found, return early with those errors
    if malformed_diagnostics:
        logger.error(
            f"Found {len(malformed_diagnostics)} malformed template(s)",
            extra={"errors": [d.message for d in malformed_diagnostics]},
        )
        return diagnostics

    # Extract all templates from workflow
    all_templates = _extract_all_templates(workflow_ir)
    cache_templates = _extract_cache_templates_for_unused_check(workflow_ir)

    if all_templates or cache_templates:
        logger.debug(
            f"Found {len(all_templates)} node-param + {len(cache_templates)} cache template(s) to validate",
            extra={"templates": sorted(all_templates), "cache_templates": sorted(cache_templates)},
        )
    else:
        logger.debug("No template variables found in workflow")

    # Check for unused inputs — the union ensures inputs declared ONLY for use
    # in ``## Cache`` aren't flagged as unused. Cache vars don't flow through
    # ``validate_template_paths`` below (their resolution is handled by
    # ``core/workflow/data_flow.py::_validate_cache_block`` with richer messages).
    unused_input_diagnostics = _validate_unused_inputs(workflow_ir, all_templates | cache_templates)
    diagnostics.extend(unused_input_diagnostics)

    # If no templates exist anywhere in the workflow, most template passes can
    # return early. Code-node annotation boundary checks still need to run,
    # because "input missing annotation" / "orphan annotation" are meaningful
    # even when inputs are literals or empty. Loop `while:` validation must also
    # run even with no extractable operands (an operator-only `while: ${x > 0}`
    # yields no template operand but must still be rejected — issue #445).
    has_loop = any(node.get("loop") for node in workflow_ir.get("nodes", []))
    if not all_templates and not has_loop:
        diagnostics.extend(validate_code_node_input_annotations(workflow_ir, {}))
        return diagnostics

    # Get full output structure from nodes
    node_outputs = extract_node_outputs(workflow_ir, registry, available_params)

    if not all_templates:
        # Only loop conditions remain to check (no node-param templates).
        diagnostics.extend(validate_code_node_input_annotations(workflow_ir, node_outputs))
        diagnostics.extend(_validate_loop_conditions(workflow_ir, node_outputs))
        diagnostics.extend(_validate_loop_carry_refs(workflow_ir, node_outputs))
        diagnostics.extend(_validate_loop_carry_prompt_usage(workflow_ir))
        diagnostics.extend(_validate_loop_carry_literal_fallback(workflow_ir))
        return diagnostics

    logger.debug(
        f"Extracted outputs from {len(node_outputs)} node variables", extra={"outputs": sorted(node_outputs.keys())}
    )

    # Pass 5: Validate each template path. Uses the field-checkable subset, NOT
    # all_templates: operands of a multi-operand ?? chain are excluded because
    # ?? falls through on a missing field at runtime (issue #441), so field-
    # checking them would hard-error on a legitimately-optional field. Their
    # root existence is still validated in core/workflow/data_flow.py.
    diagnostics.extend(
        validate_template_paths(
            _field_checkable_templates(workflow_ir), available_params, node_outputs, workflow_ir, registry
        )
    )

    # Pass 6: Validate template types match parameter expectations
    diagnostics.extend(validate_template_types(workflow_ir, node_outputs, registry))

    # Pass 7: Block structured data (dict/list) in shell command parameters
    diagnostics.extend(validate_shell_command_types(workflow_ir, node_outputs))

    # Pass 8: Validate batch item field access (${item.field} against inferred structure)
    diagnostics.extend(validate_batch_item_fields(workflow_ir, node_outputs))

    # Pass 9: Validate code-node input annotations against upstream template types
    diagnostics.extend(validate_code_node_input_annotations(workflow_ir, node_outputs))

    # Pass 10 (issue #445): Validate loop `while:`/`until:` conditions — typed-output gate
    # (reject known-string sources like ${shell.stdout}) + operator rejection
    # (reject ${x > 0} and arithmetic). Belt-and-suspenders with the runtime
    # str-condition raise in the engine.
    diagnostics.extend(_validate_loop_conditions(workflow_ir, node_outputs))
    diagnostics.extend(_validate_loop_carry_refs(workflow_ir, node_outputs))
    diagnostics.extend(_validate_loop_carry_prompt_usage(workflow_ir))
    diagnostics.extend(_validate_loop_carry_literal_fallback(workflow_ir))

    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    warnings = [d for d in diagnostics if d.severity != Severity.ERROR]

    if errors:
        logger.warning(
            f"Template validation found {len(errors)} errors", extra={"error_count": len(errors), "errors": errors}
        )
    elif warnings:
        logger.info(
            f"Template validation passed with {len(warnings)} runtime-validated template(s)",
            extra={"warning_count": len(warnings)},
        )
    else:
        logger.info("Template validation passed")

    return diagnostics


# ---------------------------------------------------------------------------
# Loop condition validation (issue #445)
# ---------------------------------------------------------------------------

# Operator / arithmetic characters that never appear in a valid pflow variable
# path or a coalesce expression. Their presence inside a `while:` means the
# author wrote a comparison/arithmetic expression — which the truthiness-only
# condition model does not support. Hyphen (`-`) is intentionally EXCLUDED
# because node IDs legitimately contain it (e.g. ${run-cycle.x}).
_LOOP_OPERATOR_CHARS = frozenset(">=<!+*/%")

# Output types that mean the condition source is a raw string — truthiness over
# a string is the foot-gun the typed-output gate exists to prevent (e.g. shell
# stdout "0\n" is truthy). Covers both the S1 vocabulary ("string") and the
# Python-ish registry vocabulary ("str").
_KNOWN_STRING_TYPES = frozenset({"string", "str"})


def _validate_loop_conditions(workflow_ir: dict[str, Any], node_outputs: dict[str, Any]) -> list[Diagnostic]:
    """Validate `loop: while:` / `loop: until:` conditions, one diagnostic per field."""
    diagnostics: list[Diagnostic] = []
    for node in workflow_ir.get("nodes", []):
        loop_config = node.get("loop")
        if not isinstance(loop_config, dict):
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        for field_name in ("while", "until"):
            condition_template = loop_config.get(field_name)
            if not isinstance(condition_template, str):
                continue
            diag = _loop_condition_diagnostic(node_id, field_name, condition_template, workflow_ir, node_outputs)
            if diag is not None:
                diagnostics.append(diag)
    return diagnostics


def _loop_condition_diagnostic(
    node_id: str,
    field_name: str,
    condition_template: str,
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any],
) -> Diagnostic | None:
    """Return the (at most one) ERROR for a loop condition, or None if valid.

    - **Operator rejection**: `while: ${x > 0}` / arithmetic is unsupported — the
      condition is truthiness over a typed value, not an expression.
    - **Typed-output gate (belt half 1)**: reject a `while:` whose source has a
      *known string* type (e.g. `${shell.stdout}`). `any`/un-inferable types are
      allowed so the motivating sub-workflow example isn't false-rejected. A
      coalesce (`${a ?? b}`) is checked per non-literal operand — the runtime belt
      raises on a string result too, so checking here keeps the validation half of
      the belt-and-suspenders honest.
    """
    from pflow.runtime.template_validation.type_checker import infer_template_type

    if any(ch in _LOOP_OPERATOR_CHARS for ch in condition_template):
        return _make_loop_operator_diagnostic(node_id, field_name, condition_template)

    var = TemplateResolver.extract_simple_template_var(condition_template)
    if var is None:
        # Not a single ${...} reference. The schema pattern (^\$\{.+\}$) is too broad to
        # catch a multi-reference like `${a}${b}`, so reject it HERE rather than leaving the
        # runtime to silently single-pass on it (the runtime stops on this shape — issue #445).
        return _make_loop_shape_diagnostic(node_id, field_name, condition_template)

    # NOTE: a bare node reference (`while: ${c}`, no field) needs no loop-specific
    # check here — it is already rejected by the generic template validator ("Invalid
    # template ${c} — this is a node ID. Use ${c.output_key}") AND data-flow. Verified
    # via the CLI: such a workflow fails validation (exit 1), it does NOT silently loop
    # to the cap. Adding a third loop-specific error would only be noise.
    is_coalesce = TemplateResolver.is_coalesce_expression(var)
    operands = TemplateResolver.split_coalesce_operands(var) if is_coalesce else [var]
    for operand in operands:
        if TemplateResolver.is_literal_operand(operand):
            continue
        inferred = infer_template_type(operand, workflow_ir, node_outputs)
        if inferred in _KNOWN_STRING_TYPES:
            return _make_loop_string_type_diagnostic(node_id, field_name, condition_template, operand, str(inferred))
    return None


def _make_loop_operator_diagnostic(node_id: str, field_name: str, condition_template: str) -> Diagnostic:
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=(
            f"Node '{node_id}' `loop: {field_name}:` is '{condition_template}', which uses a comparison or "
            f"arithmetic operator. The loop condition is truthiness over a typed value, not an expression."
        ),
        suggestions=[
            "Use a single ${node.output} reference whose value is truthy while the loop should continue "
            "(a non-empty list/string, a non-zero number, or true) and falsy to stop.",
            "If you need a comparison, compute it in the loop body and reference the boolean output: "
            "`while: ${step.should_continue}`.",
        ],
        context={"category": "validation", "path": f"nodes[id={node_id}].loop.{field_name}"},
    )


def _make_loop_shape_diagnostic(node_id: str, field_name: str, condition_template: str) -> Diagnostic:
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=(
            f"Node '{node_id}' `loop: {field_name}:` is '{condition_template}', which is not a single "
            f"${{...}} reference. The loop condition must be one reference to a typed output "
            f"whose truthiness decides whether to continue."
        ),
        suggestions=[
            "Use a single ${node.output} reference — a list (drains to empty), a number "
            "(counts to 0), or a boolean. Combine multiple signals in the loop body and "
            "reference the single boolean output: `while: ${step.should_continue}`.",
        ],
        context={"category": "validation", "path": f"nodes[id={node_id}].loop.{field_name}"},
    )


def _make_loop_string_type_diagnostic(
    node_id: str, field_name: str, condition_template: str, var: str, inferred: str
) -> Diagnostic:
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=(
            f"Node '{node_id}' `loop: {field_name}:` references '{condition_template}', whose type is "
            f"'{inferred}' (a string). String truthiness is a foot-gun — a non-empty string like "
            f"'0\\n' or 'false' is truthy, so the loop would never stop on those values."
        ),
        suggestions=[
            "Reference a typed output instead: a list (drains to empty), a number (counts to 0), "
            "or a boolean (`while: ${step.has_more}`).",
            "If the source genuinely is a list/number, declare its output type so it isn't seen as a string.",
        ],
        context={
            "category": "validation",
            "path": f"nodes[id={node_id}].loop.{field_name}",
            "template": condition_template,
        },
    )


def _validate_loop_carry_refs(workflow_ir: dict[str, Any], node_outputs: dict[str, Any]) -> list[Diagnostic]:
    """Validate carry refs against precise loop-node outputs when available."""
    diagnostics: list[Diagnostic] = []
    for node in workflow_ir.get("nodes", []):
        loop_config = node.get("loop")
        if not isinstance(loop_config, dict):
            continue
        carry = loop_config.get("carry")
        node_id = node.get("id")
        if not isinstance(node_id, str) or not isinstance(carry, dict):
            continue
        if not _loop_outputs_are_precise(node, node_outputs):
            continue
        available = _loop_declared_outputs(node_id, node_outputs)
        for key, value in carry.items():
            if not isinstance(value, str):
                continue
            output_name = _carry_value_unknown_output(value, node_id, node_outputs)
            if output_name:
                diagnostics.append(
                    _make_loop_carry_unknown_output_diagnostic(node_id, str(key), value, output_name, available)
                )
    return diagnostics


def _loop_declared_outputs(node_id: str, node_outputs: dict[str, Any]) -> list[str]:
    """The loop node's carryable top-level output names (from the namespaced node_outputs keys).

    Excludes ``loop_stopped`` — it's the engine-injected stop-reason marker, only present once
    the loop ends, so it's never a meaningful carry source mid-loop.
    """
    names = {
        key[len(node_id) + 1 :].split(".", 1)[0].split("[", 1)[0]
        for key in node_outputs
        if key.startswith(f"{node_id}.")
    }
    names.discard("loop_stopped")
    return sorted(names)


def _carry_value_unknown_output(value: str, node_id: str, node_outputs: dict[str, Any]) -> str | None:
    """Return the first self-referencing output segment in a carry value that the loop
    node does NOT declare (a typo), or None when every self-ref operand is declared.

    Coalesce is checked operand-by-operand, skipping literals — mirrors the loop
    CONDITION validator. Parsing the whole `${c.next_state ?? "start"}` as one path would
    read the output as `next_state ?? "start"` and falsely reject a valid carry; splitting
    first checks each self-ref operand against the declared outputs. Non-self-ref operands
    are left to the self-ref check in data_flow.
    """
    var = TemplateResolver.extract_simple_template_var(value)
    if var is None:
        return None
    operands = TemplateResolver.split_coalesce_operands(var) if TemplateResolver.is_coalesce_expression(var) else [var]
    for operand in operands:
        if TemplateResolver.is_literal_operand(operand):
            continue
        if TemplateResolver.extract_root_node_id(operand) != node_id:
            continue
        output_name = TemplateResolver.extract_first_field_segment(operand)
        if output_name and f"{node_id}.{output_name}" not in node_outputs:
            return output_name
    return None


def _loop_outputs_are_precise(node: dict[str, Any], node_outputs: dict[str, Any]) -> bool:
    node_id = node.get("id")
    node_type = node.get("type")
    if not isinstance(node_id, str) or not isinstance(node_type, str):
        return False
    if node_outputs.get(node_id, {}).get("is_workflow_dynamic"):
        return False
    has_namespaced_outputs = any(key.startswith(f"{node_id}.") for key in node_outputs)
    return has_namespaced_outputs and node_type in {"workflow", "pflow.runtime.workflow_executor", "code"}


def _make_loop_carry_unknown_output_diagnostic(
    node_id: str, key: str, template: str, output_name: str, available: list[str]
) -> Diagnostic:
    similar = find_similar_items(output_name, available, method="fuzzy")
    context: dict[str, Any] = {
        "category": "validation",
        "path": f"nodes[id={node_id}].loop.carry.{key}",
        "template": template,
        "output": output_name,
        "available_fields": available,
        "available_fields_total": len(available),
        "available_fields_label": "outputs",
    }
    if similar:
        context["similar_names"] = similar
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=(
            f"Node '{node_id}' `loop: carry:` entry '{key}' references '{template}', but loop node "
            f"'{node_id}' does not declare output '{output_name}'."
        ),
        suggestions=[
            "Reference one of the loop node's declared outputs, or update the body workflow/code output declaration.",
        ],
        context=context,
    )


def _validate_loop_carry_prompt_usage(workflow_ir: dict[str, Any]) -> list[Diagnostic]:
    """Warn when shell/llm carry inputs are not interpolated into their executable text."""
    diagnostics: list[Diagnostic] = []
    for node in workflow_ir.get("nodes", []):
        node_type = node.get("type")
        if node_type not in {"shell", "llm"}:
            continue
        node_id = node.get("id")
        loop_config = node.get("loop")
        carry = loop_config.get("carry") if isinstance(loop_config, dict) else None
        if not isinstance(node_id, str) or not isinstance(carry, dict):
            continue
        text = _loop_prompt_sink_text(node)
        # Collect the ROOT id of every template referenced in the prompt/command text.
        # A carried key used via a nested path (`${state.summary}`), index
        # (`${state[0]}`), or coalesce (`${state ?? ""}`) still roots at `state`, so it
        # counts as referenced — an exact `${state}` substring check false-positives on
        # all of those forms (the carry IS used, just not bare).
        referenced_roots: set[str] = set()
        for match in TemplateResolver.TEMPLATE_EXTRACT_PATTERN.finditer(text):
            for operand in TemplateResolver.split_coalesce_operands(match.group(1)):
                if TemplateResolver.is_literal_operand(operand):
                    continue
                root = TemplateResolver.extract_root_node_id(operand)
                if root:
                    referenced_roots.add(root)
        for key in carry:
            if isinstance(key, str) and key not in referenced_roots:
                diagnostics.append(_make_loop_carry_unreferenced_warning(node_id, node_type, key))
    return diagnostics


def _loop_prompt_sink_text(node: dict[str, Any]) -> str:
    params = node.get("params", {})
    if not isinstance(params, dict):
        return ""
    values: list[str] = []
    for key in ("command", "prompt", "system"):
        value = params.get(key)
        if isinstance(value, str):
            values.append(value)
    return "\n".join(values)


def _make_loop_carry_unreferenced_warning(node_id: str, node_type: str, key: str) -> Diagnostic:
    sink = "command" if node_type == "shell" else "prompt/system"
    return Diagnostic(
        severity=Severity.WARNING,
        source="validator",
        title="Validation Warning",
        node_id=node_id,
        message=(
            f"Node '{node_id}' carries input '{key}', but the {node_type} node's {sink} text does not "
            f"reference `${{{key}}}`. Carrying into `inputs:` alone is inert for {node_type} nodes."
        ),
        suggestions=[
            f"Reference `${{{key}}}` in the node's {sink} text, or remove the carried key.",
        ],
        context={"category": "validation", "path": f"nodes[id={node_id}].loop.carry.{key}"},
    )


def _validate_loop_carry_literal_fallback(workflow_ir: dict[str, Any]) -> list[Diagnostic]:
    """Warn when a `carry:` value uses a LITERAL coalesce fallback (e.g. `${node.x ?? 0}`).

    A literal fallback always resolves, so on a round where the loop body omits the
    carried output the fallback resolves silently and re-seeds the carried key — the
    loud carry guard (`_assert_carried_inputs_resolved`) never fires. That is the exact
    silent stale-state failure carry exists to prevent. A coalesce between two real
    outputs (`${a ?? b}`) is fine — both are body outputs — so only a literal operand
    trips this warning.
    """
    diagnostics: list[Diagnostic] = []
    for node in workflow_ir.get("nodes", []):
        loop_config = node.get("loop")
        carry = loop_config.get("carry") if isinstance(loop_config, dict) else None
        node_id = node.get("id")
        if not isinstance(node_id, str) or not isinstance(carry, dict):
            continue
        for key, value in carry.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            var = TemplateResolver.extract_simple_template_var(value)
            if var is None or not TemplateResolver.is_coalesce_expression(var):
                continue
            operands = TemplateResolver.split_coalesce_operands(var)
            if any(TemplateResolver.is_literal_operand(op) for op in operands):
                diagnostics.append(_make_loop_carry_literal_fallback_warning(node_id, key, value))
    return diagnostics


def _make_loop_carry_literal_fallback_warning(node_id: str, key: str, template: str) -> Diagnostic:
    return Diagnostic(
        severity=Severity.WARNING,
        source="validator",
        title="Validation Warning",
        node_id=node_id,
        message=(
            f"Node '{node_id}' `loop: carry:` entry '{key}' uses a literal fallback ({template}). "
            f"If the loop body skips producing '{key}' on a round, the literal silently re-seeds it "
            f"instead of stopping the loop — so the loop can keep running on stale state with no error."
        ),
        suggestions=[
            f"Use a plain `${{{node_id}.output}}` reference so a missing carried output fails loudly. "
            "Keep the literal fallback only if silent re-seeding is genuinely intended.",
        ],
        context={"category": "validation", "path": f"nodes[id={node_id}].loop.carry.{key}"},
    )


# ---------------------------------------------------------------------------
# Simple passes (too small for own file)
# ---------------------------------------------------------------------------


def _validate_unused_inputs(workflow_ir: dict[str, Any], all_templates: set[str]) -> list[Diagnostic]:
    """Validate that all declared inputs are actually used.

    Args:
        workflow_ir: The workflow IR
        all_templates: Set of all template variables found

    Returns:
        Diagnostics for unused inputs
    """
    diagnostics: list[Diagnostic] = []
    declared_inputs = set(workflow_ir.get("inputs", {}).keys())

    if declared_inputs:
        enable_namespacing = workflow_ir.get("enable_namespacing", True)
        node_ids = get_node_ids(workflow_ir) if enable_namespacing else set()

        # Extract root identifier from each template using the canonical
        # helper. A bare ``.split(".")[0]`` misses bracket syntax — e.g.
        # ``${items[0].name}`` would reduce to ``"items[0]"`` and then
        # never match a declared input named ``items``, producing a false
        # "unused input" error. ``extract_root_node_id`` handles all
        # variants (bare, dotted, indexed, mixed).
        used_inputs = set()
        for var in all_templates:
            base_var = TemplateResolver.extract_root_node_id(var) or var
            # Only count as used input if it's actually a declared input
            # and not a node ID (when namespacing is enabled)
            if base_var in declared_inputs and (not enable_namespacing or base_var not in node_ids):
                used_inputs.add(base_var)

        unused_inputs = declared_inputs - used_inputs
        if unused_inputs:
            sorted_unused = sorted(unused_inputs)
            # Severity.ERROR is intentional: declared inputs are a contract with
            # callers. An unused declaration means either the declaration is wrong
            # (spurious input) or a usage is missing (bug in the workflow), and
            # both are fixes the author should make before the workflow runs.
            # The existing test suite (test_unused_input_*, test_mixed_used_and_unused_inputs)
            # asserts this as blocking-severity; demoting to WARNING would require
            # updating ~6 tests and changing the declared-input contract.
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    source="validator",
                    title="Validation Error",
                    message=f"Declared input(s) never used as template variable: {', '.join(sorted_unused)}",
                    suggestions=["Remove unused declarations from '## Inputs' or reference them in a node parameter."],
                    context={
                        "category": "validation",
                        "path": "inputs",
                        "unused_inputs": sorted_unused,
                    },
                )
            )
            logger.warning(f"Found {len(unused_inputs)} unused inputs", extra={"unused": sorted(unused_inputs)})

    return diagnostics


def _malformed_literal_operand_hint(value: str) -> tuple[str, list[str]] | None:
    """Return a targeted (message, suggestions) for a malformed literal operand.

    After Optional A, ``${a ?? 0}`` and friends are valid, but ``${a ?? [1,2]}``
    (composite array) or ``${a ?? "unterminated}`` are not. Generic "malformed
    template syntax" misleads agents into thinking their literal is fine. This
    detects an operand that *looks* like a literal (starts with ``" [ { -`` or a
    digit) but doesn't fully parse, and returns the literal-specific guidance.
    Returns None when no such operand is found (caller uses the generic message).
    """
    if "??" not in value:
        return None

    for match in TemplateResolver.TEMPLATE_EXTRACT_PATTERN.finditer(value):
        for operand in TemplateResolver.split_coalesce_operands(match.group(1)):
            if not TemplateResolver.is_literal_operand(operand):
                continue
            # Check against the literal GRAMMAR (not json.loads): composite
            # arrays/objects like [1,2] parse as JSON but are deliberately
            # excluded from the ?? literal grammar.
            if re.fullmatch(TemplateResolver._LITERAL_PATTERN, operand) is None:
                return (
                    f"Malformed literal operand in '${{{match.group(1)}}}': literal operands must be "
                    "JSON values — numbers, \"double-quoted strings\" (no '??' inside), "
                    "true/false/null, [], or {}.",
                    [
                        "For complex defaults, use a code node that emits the value, then reference it.",
                    ],
                )
    return None


def _validate_malformed_templates(workflow_ir: dict[str, Any]) -> list[Diagnostic]:  # noqa: C901
    """Detect malformed template syntax by counting ${ vs valid template matches.

    A malformed template is one where we find ${ but it doesn't form a valid template.
    Examples: ${unclosed, ${}, ${ }

    Args:
        workflow_ir: The workflow IR

    Returns:
        Diagnostics for malformed templates
    """
    diagnostics: list[Diagnostic] = []

    for node in workflow_ir.get("nodes", []):
        node_id = node.get("id", "unknown")
        params = node.get("params", {})

        def check_value(value: Any, node_id: str, param_path: str = "") -> None:
            """Recursively check for malformed templates in any value type."""
            if isinstance(value, str) and "${" in value:
                # Count how many ${ we have
                dollar_brace_count = value.count("${")

                # Count how many valid templates we matched
                valid_matches = _PERMISSIVE_PATTERN.findall(value)

                # Account for nested templates inside brackets - they're part of
                # outer templates and shouldn't be counted separately.
                # Example: ${results[${__index__}]} has 2 '${' but is 1 logical template
                # - valid_matches = ['results[${__index__}]', '__index__'] (2 matches)
                # - nested_count = 1 (one match contains '[${')
                # - dollar_brace_count = 2
                # - len(valid_matches) + nested_count = 3 >= 2 ✓ (no error)
                nested_count = sum(f"${{{m}}}".count("[${") for m in valid_matches)

                # If mismatch (accounting for nested), we have malformed syntax
                if len(valid_matches) + nested_count < dollar_brace_count:
                    path = f"nodes[id={node_id}].params.{param_path}" if param_path else f"nodes[id={node_id}].params"
                    # Discriminate: a malformed LITERAL operand (Optional A) gets a
                    # targeted message so agents don't think their literal is fine.
                    literal_hint = _malformed_literal_operand_hint(value)
                    if literal_hint is not None:
                        message, suggestions = literal_hint
                    else:
                        message = (
                            f"Malformed template syntax: found {dollar_brace_count} '${{' but only "
                            f"{len(valid_matches)} valid template(s)."
                        )
                        suggestions = ["Check for missing '}' or empty templates like '${}'."]
                    diagnostics.append(
                        Diagnostic(
                            severity=Severity.ERROR,
                            source="validator",
                            title="Template Error",
                            node_id=node_id,
                            message=message,
                            suggestions=suggestions,
                            context={
                                "category": "template_error",
                                "path": path,
                                "template": value if isinstance(value, str) else None,
                            },
                        )
                    )
            elif isinstance(value, dict):
                for key, val in value.items():
                    check_value(val, node_id, f"{param_path}.{key}" if param_path else key)
            elif isinstance(value, list):
                for idx, item in enumerate(value):
                    check_value(item, node_id, f"{param_path}[{idx}]")

        for param_key, param_value in params.items():
            check_value(param_value, node_id, param_key)

    return diagnostics


# ---------------------------------------------------------------------------
# Template extraction
# ---------------------------------------------------------------------------


def _operands_in_string(value: str) -> Iterator[tuple[str, bool]]:
    """Yield ``(operand, in_coalesce)`` for each non-literal operand in one string.

    Uses the permissive pattern (so malformed templates are still surfaced by the
    separate malformed-syntax pass) and splits ``??`` chains. Literal operands
    (Optional A — ``0``, ``"x"``, ``null``) are dropped: they are values, not refs.
    ``in_coalesce`` is True for an operand of a multi-operand ``??`` chain.
    """
    for match in _PERMISSIVE_PATTERN.findall(value):
        if "??" in match:
            for op in TemplateResolver.split_coalesce_operands(match):
                if not TemplateResolver.is_literal_operand(op):
                    yield op, True
        elif not TemplateResolver.is_literal_operand(match):
            yield match, False


def _node_template_value_sources(node: dict[str, Any]) -> Iterator[Any]:
    """Yield every value on a node that may carry templates: params, ``batch.items``,
    and the loop condition / ``max_iterations:`` sources.

    Including the loop sources means an input used ONLY in ``while:`` isn't flagged
    "unused", and the root of ``while: ${typo.x}`` is path-validated.
    """
    yield from node.get("params", {}).values()
    batch_config = node.get("batch")
    if batch_config and batch_config.get("items"):
        yield batch_config["items"]
    loop_config = node.get("loop")
    if isinstance(loop_config, dict):
        for key in ("while", "until", "max_iterations"):
            value = loop_config.get(key)
            if isinstance(value, str):
                yield value


def _iter_template_operands(workflow_ir: dict[str, Any]) -> Iterator[tuple[str, bool]]:
    """Yield ``(operand, in_coalesce)`` for every non-literal template operand
    found in node params, ``batch.items``, and loop conditions.

    ``in_coalesce`` operands may be legitimately absent at runtime (``??`` falls
    through on a missing field — issue #441), so they are NOT eligible for Pass-5
    field validation, though they ARE references for unused-input detection. This
    is the single source of traversal truth for both ``_extract_all_templates``
    and ``_field_checkable_templates``.
    """

    def walk(value: Any) -> Iterator[tuple[str, bool]]:
        if isinstance(value, str) and "$" in value:
            yield from _operands_in_string(value)
        elif isinstance(value, dict):
            for val in value.values():
                yield from walk(val)
        elif isinstance(value, list):
            for item in value:
                yield from walk(item)

    for node in workflow_ir.get("nodes", []):
        for source in _node_template_value_sources(node):
            yield from walk(source)


def _extract_all_templates(workflow_ir: dict[str, Any]) -> set[str]:
    """All non-literal template operands (both sides of every ``??`` chain).

    Used for unused-input detection — an operand is a reference even when ``??``
    may let it be absent at runtime. Pass 5 (path validation) instead uses the
    field-checkable subset (see ``_field_checkable_templates``).
    """
    return {operand for operand, _ in _iter_template_operands(workflow_ir)}


def _field_checkable_templates(workflow_ir: dict[str, Any]) -> set[str]:
    """Template operands eligible for Pass-5 path/field existence validation.

    Excludes operands of a multi-operand ``??`` chain: under issue #441 ``??``
    falls through on a missing field, so a legitimately-optional field must not
    hard-error here. Their root existence is still validated in
    ``core/workflow/data_flow.py``; a bare ``${node.field}`` (no ``??``) stays
    fully field-checked.
    """
    return {operand for operand, in_coalesce in _iter_template_operands(workflow_ir) if not in_coalesce}


def _extract_cache_templates_for_unused_check(workflow_ir: dict[str, Any]) -> set[str]:
    """Extract template variables from the workflow-level ``## Cache`` block.

    Cache chunks reference workflow inputs / step outputs via their ``var``
    field; without registering these the unused-input check (``_validate_unused_inputs``)
    would flag inputs declared ONLY for use inside ``## Cache`` as unused —
    spurious ERROR even when the input IS used in cache.

    Cache vars are validated FOR RESOLUTION in
    ``core/workflow/data_flow.py::_validate_cache_block``, which emits richer
    "Cache chunk 'X' references..." diagnostics with similar-name suggestions
    and source-line metadata. The path-validation pass (``validate_template_paths``)
    in this package MUST NOT receive cache vars — it would emit a parallel
    generic "Template variable ${X} has no valid source" diagnostic and the
    user gets two errors for the same problem.

    Split-extractor contract: keep this function's output OUT of the
    ``all_templates`` set passed to ``validate_template_paths`` and friends.
    Only ``_validate_unused_inputs`` consumes the union.
    """
    templates: set[str] = set()
    cache_block = workflow_ir.get("cache")
    if not isinstance(cache_block, dict):
        return templates
    cache_items = cache_block.get("items")
    if not isinstance(cache_items, list):
        return templates
    for item in cache_items:
        if not isinstance(item, dict):
            continue
        var = item.get("var")
        if not isinstance(var, str) or not var:
            continue
        # Apply the same coalesce-split as node-param templates so a
        # hypothetical ``${a ?? b}`` chunk var (parser doesn't allow this in v1
        # but a programmatic IR could) is still split into operands for
        # the unused-input check.
        if "??" in var:
            templates.update(
                op
                for op in TemplateResolver.split_coalesce_operands(var)
                if not TemplateResolver.is_literal_operand(op)
            )
        elif not TemplateResolver.is_literal_operand(var):
            templates.add(var)
    return templates


# ---------------------------------------------------------------------------
# Output extraction (builds node_outputs dict used by all passes)
# ---------------------------------------------------------------------------


def extract_node_outputs(
    workflow_ir: dict[str, Any],
    registry: Registry,
    initial_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract full output structures from nodes using interface metadata.

    When namespacing is enabled, outputs are registered under both:
    - The original key (for backward compatibility checks)
    - The namespaced path "node_id.output_key"

    For batch nodes, registers batch-specific outputs (results, count, etc.)
    instead of the inner node's normal outputs, and adds the item alias
    as an available variable.

    Returns:
        Dict mapping variable names to their full structure/type info
    """
    node_outputs: dict[str, dict[str, Any]] = {}
    enable_namespacing = workflow_ir.get("enable_namespacing", True)

    for node in workflow_ir.get("nodes", []):
        node_id = node.get("id")
        node_type = node.get("type")
        if not node_type or not node_id:
            continue

        # Register inputs-as-context keys for all node types.
        # Runs before type-specific branching so workflow, batch, and regular
        # nodes all get their inputs keys registered.
        inputs_param = node.get("params", {}).get("inputs")
        if isinstance(inputs_param, dict):
            _register_inputs_context_variables(node_outputs, node_id, node_type, inputs_param)

        # Workflow nodes: resolve child outputs for validation.
        if node_type in ("workflow", "pflow.runtime.workflow_executor"):
            _register_workflow_node_outputs(
                node_outputs,
                node,
                node_id,
                node_type,
                enable_namespacing,
                registry,
                initial_params,
            )
            continue

        # Check for batch configuration
        batch_config = node.get("batch")

        # Pre-compute code-node annotations so both batch and non-batch output
        # registration can enrich the `result` type uniformly.
        code_annotations: dict[str, str] | None = None
        if node_type == "code":
            code_param = node.get("params", {}).get("code")
            if isinstance(code_param, str):
                from pflow.nodes.python.python_code import _extract_annotations

                try:
                    code_annotations = _extract_annotations(code_param)
                except SyntaxError:
                    code_annotations = None

        if batch_config:
            # Batch node: register batch outputs instead of normal outputs
            _register_batch_outputs(
                node_outputs,
                node_id,
                node_type,
                enable_namespacing,
                registry,
                error_handling=batch_config.get("error_handling", "fail_fast"),
                code_annotations=code_annotations,
                node_params=node.get("params"),
            )
            _register_batch_item_variables(node_outputs, node_id, node_type, batch_config)
        else:
            # Non-batch node: extract outputs from registry interface
            _register_node_outputs_from_registry(
                node_outputs,
                node_id,
                node_type,
                enable_namespacing,
                registry,
                code_annotations=code_annotations,
                node_params=node.get("params"),
            )

    _register_loop_node_outputs(node_outputs, workflow_ir, enable_namespacing)
    return node_outputs


def _register_loop_node_outputs(
    node_outputs: dict[str, Any], workflow_ir: dict[str, Any], enable_namespacing: bool
) -> None:
    """Register the synthetic outputs loop nodes expose (issue #445).

    - ``__iteration__``: 1-based loop iteration count, available in any loop body.
      Registered once globally (like batch's ``__index__``) so Pass 5 recognizes
      the bare ``${__iteration__}`` reference.
    - ``{loop}.loop_stopped``: the engine stamps "condition" | "max_iterations" onto
      a loop node's output dict when the loop ends. Registered (namespaced) so a
      post-loop node may reference it without a spurious "does not output" error.
      Gated on ``enable_namespacing``: the marker is written to ``shared[node_id]``
      (a dict the NamespacedSharedStore eagerly creates); with namespacing OFF the
      engine cannot stamp it, so registering it would be a validate-OK /
      runtime-empty drift. Keep the two layers in agreement.
    """
    loop_node_ids = [node.get("id") for node in workflow_ir.get("nodes", []) if node.get("loop")]
    if not loop_node_ids:
        return
    node_outputs["__iteration__"] = {
        "type": "int",
        "description": "Current loop iteration count (1-based, issue #445)",
        "is_loop_iteration": True,
    }
    if enable_namespacing:
        for loop_id in loop_node_ids:
            if isinstance(loop_id, str):
                node_outputs[f"{loop_id}.loop_stopped"] = {
                    "type": "string",
                    "description": 'Why the loop stopped: "condition" (drained) or "max_iterations" (capped).',
                    "node_id": loop_id,
                    "is_loop_marker": True,
                }


def _register_workflow_node_outputs(
    node_outputs: dict[str, Any],
    node: dict[str, Any],
    node_id: str,
    node_type: str,
    enable_namespacing: bool,
    registry: Registry,
    initial_params: dict[str, Any] | None,
) -> None:
    """Register outputs for a workflow node, handling both batch and non-batch cases.

    Resolves the child workflow's declared outputs. When the node has batch config,
    wraps those outputs in the batch structure (results, count, etc.) instead of
    exposing them directly.
    """
    child_outputs = _resolve_child_workflow_outputs(node, initial_params)
    batch_config = node.get("batch")

    if batch_config:
        # Batch workflow: wrap child outputs in batch structure
        if child_outputs is not None:
            inner_outputs: dict[str, Any] = {}
            for output_name, output_spec in child_outputs.items():
                output_type = output_spec.get("type", "any") if isinstance(output_spec, dict) else "any"
                inner_outputs[output_name] = {"type": output_type}
            _register_batch_outputs(
                node_outputs,
                node_id,
                node_type,
                enable_namespacing,
                registry,
                inner_outputs_override=inner_outputs,
                error_handling=batch_config.get("error_handling", "fail_fast"),
            )
        else:
            # Child unresolvable: register batch outputs without inner structure.
            # skip_results_structure=True lets the validator accept any results[N].* path
            # (falls through to permissive "array type" check).
            _register_batch_outputs(
                node_outputs,
                node_id,
                node_type,
                enable_namespacing,
                registry,
                skip_results_structure=True,
                error_handling=batch_config.get("error_handling", "fail_fast"),
            )
        _register_batch_item_variables(node_outputs, node_id, node_type, batch_config)
    elif child_outputs is not None:
        # Non-batch workflow with resolvable outputs
        for output_name, output_spec in child_outputs.items():
            output_type = output_spec.get("type", "any") if isinstance(output_spec, dict) else "any"
            output_info = {"type": output_type, "node_id": node_id, "node_type": node_type}
            node_outputs[output_name] = output_info
            if enable_namespacing:
                node_outputs[f"{node_id}.{output_name}"] = output_info
    else:
        # Can't resolve child outputs — mark as dynamic
        node_outputs[node_id] = {
            "type": "any",
            "node_id": node_id,
            "node_type": node_type,
            "is_workflow_dynamic": True,
        }


def _register_batch_item_variables(
    node_outputs: dict[str, Any],
    node_id: str,
    node_type: str,
    batch_config: dict[str, Any],
) -> None:
    """Register the item alias and __index__ as available variables for batch nodes."""
    item_alias = batch_config.get("as", "item")
    node_outputs[item_alias] = {
        "type": "any",
        "description": f"Current batch item during iteration (from node '{node_id}')",
        "node_id": node_id,
        "node_type": node_type,
        "is_batch_item": True,
    }
    node_outputs["__index__"] = {
        "type": "int",
        "description": f"Current batch item index (0-based) during iteration (from node '{node_id}')",
        "node_id": node_id,
        "node_type": node_type,
        "is_batch_item": True,
    }


def _register_inputs_context_variables(
    node_outputs: dict[str, Any],
    node_id: str,
    node_type: str,
    inputs_param: dict[str, Any],
) -> None:
    """Register inputs-as-context keys as available variables for template validation.

    When a node declares ``- inputs: {key: ${source}}``, resolved keys become
    template variables within that node (same mechanism as batch item aliases).
    Registering them here lets path validation accept both bare (``${key}``) and
    dotted (``${key.field}``) references.  Per-node scoping is handled by
    ``data_flow.py`` validation.
    """
    for key in inputs_param:
        node_outputs[key] = {
            "type": "any",
            "description": f"Template context variable from inputs mapping (node '{node_id}')",
            "node_id": node_id,
            "node_type": node_type,
            "is_inputs_context": True,
        }


def _resolve_child_workflow_outputs(
    node: dict[str, Any],
    initial_params: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Try to resolve a workflow node's child outputs for validation.

    Returns the child's declared outputs dict if resolvable, or None if
    the child can't be loaded (dynamic reference, missing file, etc.).
    """
    params = node.get("params", {})

    # File or saved name reference
    workflow_ref = params.get("workflow")
    if not workflow_ref or not isinstance(workflow_ref, str):
        return None

    # Skip template references — can't resolve at validation time
    if "${" in workflow_ref:
        return None

    from pflow.core.file_resolver import is_workflow_file_reference

    if is_workflow_file_reference(workflow_ref):
        # File reference — try to load
        try:
            from pathlib import Path

            from pflow.core.markdown_parser import parse_markdown

            path = Path(workflow_ref)
            if not path.is_absolute() and initial_params:
                parent_file = initial_params.get("_pflow_workflow_file")
                base_dir = Path(parent_file).parent if parent_file else Path.cwd()
                path = base_dir / path
            path = path.resolve()
            if not path.exists():
                return None
            content = path.read_text(encoding="utf-8")
            result = parse_markdown(content)
            outputs = result.ir.get("outputs", {})
            return outputs if outputs else None
        except Exception:
            logger.debug("Could not resolve child workflow outputs for '%s'", workflow_ref, exc_info=True)
            return None
    else:
        # Saved workflow name — try to load via WorkflowManager
        try:
            from pflow.core.workflow.manager import WorkflowManager

            wm = WorkflowManager()
            child_ir = wm.load_ir(workflow_ref)
            outputs = child_ir.get("outputs", {})
            return outputs if outputs else None
        except Exception:
            logger.debug("Could not resolve child workflow outputs for '%s'", workflow_ref, exc_info=True)
            return None


def _get_inner_outputs_from_registry(node_type: str, registry: Registry) -> dict[str, Any]:
    """Look up a node type's output structure from the registry.

    Returns a dict mapping output key → {type, description, structure}.
    Returns empty dict if node type is not found.
    """
    inner_outputs: dict[str, Any] = {}
    try:
        nodes_metadata = registry.get_nodes_metadata([node_type])
        if node_type in nodes_metadata:
            interface = nodes_metadata[node_type]["interface"]
            for output in interface.get("outputs", []):
                if isinstance(output, str):
                    inner_outputs[output] = {"type": "any"}
                else:
                    key = output.get("key", "")
                    if key:
                        inner_outputs[key] = {
                            "type": output.get("type", "any"),
                            "description": output.get("description", ""),
                            "structure": output.get("structure", {}),
                        }
    except (ValueError, KeyError):
        pass
    return inner_outputs


_LLM_SCHEMA_TYPE_TO_TEMPLATE_TYPE = {
    "array": "list",
    "boolean": "bool",
    "integer": "int",
    "number": "number",
    "object": "dict",
    "string": "str",
}
_LLM_ROOT_COMBINATORS = frozenset({"allOf", "anyOf", "oneOf", "not", "if", "then", "else"})


def _llm_response_type(node_params: dict[str, Any] | None) -> str:
    """Infer only an LLM schema's explicit root type; remain permissive otherwise."""
    if not isinstance(node_params, dict) or node_params.get("output_schema") is None:
        return "str"
    schema = node_params["output_schema"]
    if TemplateResolver.has_templates(schema) or not isinstance(schema, dict) or not schema:
        return "any"
    if "$ref" in schema or _LLM_ROOT_COMBINATORS.intersection(schema):
        return "any"

    declared_type = schema.get("type")
    if isinstance(declared_type, str):
        return _LLM_SCHEMA_TYPE_TO_TEMPLATE_TYPE.get(declared_type, "any")
    if not isinstance(declared_type, list) or not declared_type:
        return "any"

    resolved: list[str] = []
    for member in declared_type:
        if not isinstance(member, str) or member == "null":
            return "any"
        mapped = _LLM_SCHEMA_TYPE_TO_TEMPLATE_TYPE.get(member)
        if mapped is None:
            return "any"
        if mapped not in resolved:
            resolved.append(mapped)
    return "|".join(resolved) if resolved else "any"


def _specialize_llm_response_output(
    inner_outputs: dict[str, Any],
    node_type: str,
    node_params: dict[str, Any] | None,
) -> dict[str, Any]:
    if node_type != "llm" or "response" not in inner_outputs:
        return inner_outputs
    return {
        **inner_outputs,
        "response": {
            **inner_outputs["response"],
            "type": _llm_response_type(node_params),
        },
    }


def _enrich_code_result_output_type(
    output_key: str,
    output_info: dict[str, Any],
    code_annotations: dict[str, str] | None,
) -> dict[str, Any]:
    """Override code-node `result` output type from its annotation when known."""
    if not code_annotations or output_key != "result" or output_info.get("type") != "any":
        return output_info

    from pflow.nodes.python.python_code import _get_outer_type_name

    annotation_str = code_annotations.get("result")
    if not annotation_str:
        return output_info

    enriched_type = _get_outer_type_name(annotation_str)
    if enriched_type is None:
        return output_info

    return {**output_info, "type": enriched_type}


def _register_batch_outputs(
    node_outputs: dict[str, Any],
    node_id: str,
    node_type: str,
    enable_namespacing: bool,
    registry: Registry,
    inner_outputs_override: dict[str, Any] | None = None,
    skip_results_structure: bool = False,
    error_handling: str = "fail_fast",
    code_annotations: dict[str, str] | None = None,
    node_params: dict[str, Any] | None = None,
) -> None:
    """Register batch-specific outputs for a node with batch configuration.

    Batch nodes wrap their inner node's outputs in a structured result with:
    - results: Array of successful results (failed items filtered out at runtime)
    - count: Total items attempted
    - success_count/error_count: Success/failure counts
    - errors: Error details if any
    - batch_metadata: Execution statistics

    Args:
        inner_outputs_override: Pre-resolved inner output structure (e.g., from
            child workflow outputs). When provided, skips registry lookup.
        skip_results_structure: When True, don't attach items structure to results.
            Used when inner outputs are unknown (e.g., dynamic workflow child ref)
            so the validator accepts any results[N].* path at validation time.
        error_handling: The batch error handling mode ("fail_fast" or "continue").
            Stored on the results entry so path validation can block index access
            when continue mode filters out failed items.
    """
    if skip_results_structure:
        inner_outputs_structure: dict[str, Any] = {}
    elif inner_outputs_override is not None:
        inner_outputs_structure = inner_outputs_override
    else:
        inner_outputs_structure = _get_inner_outputs_from_registry(node_type, registry)

    inner_outputs_structure = _specialize_llm_response_output(inner_outputs_structure, node_type, node_params)

    if code_annotations and node_type == "code" and "result" in inner_outputs_structure:
        inner_outputs_structure = {
            **inner_outputs_structure,
            "result": _enrich_code_result_output_type("result", inner_outputs_structure["result"], code_annotations),
        }

    for output in BATCH_OUTPUTS:
        key = output["key"]
        output_info: dict[str, Any] = {
            "type": output["type"],
            "description": output["description"],
            "node_id": node_id,
            "node_type": node_type,
            "is_batch_output": True,
        }

        # Store error_handling on results entry so path validation can block
        # index access when continue mode filters out failed items.
        if key == "results":
            output_info["error_handling"] = error_handling

        # For 'results' array, add inner node's output structure plus 'item'.
        # When skip_results_structure is True, omit items so the validator
        # falls through to permissive array-type access for unknown inner outputs.
        if key == "results" and not skip_results_structure:
            # Each result always contains 'item' (original batch input)
            result_structure = {"item": {"type": "any", "description": "Original batch input"}}
            if inner_outputs_structure:
                result_structure.update(inner_outputs_structure)
            output_info["items"] = {
                "type": "dict",
                "structure": result_structure,
            }

        # Register under original key for backward compatibility
        node_outputs[key] = output_info

        # If namespacing is enabled, also register under node_id.output
        if enable_namespacing:
            namespaced_key = f"{node_id}.{key}"
            node_outputs[namespaced_key] = output_info


def _register_node_outputs_from_registry(
    node_outputs: dict[str, Any],
    node_id: str,
    node_type: str,
    enable_namespacing: bool,
    registry: Registry,
    code_annotations: dict[str, str] | None = None,
    node_params: dict[str, Any] | None = None,
) -> None:
    """Register outputs from registry interface metadata for non-batch nodes.

    Silently skips unknown node types — the pre-execution
    ``WorkflowValidator._validate_node_types`` step (step 6) produces a rich
    ``Unknown node type`` diagnostic with ``similar_names`` and structured
    path, which is strictly more useful than anything this function could
    emit. Raising here would propagate through ``validate_workflow_templates``
    (step 5) to the outer CLI/MCP exception boundary — issue #237 removed the
    defensive wrapper that previously would have absorbed it as a generic
    ``"Template validation error: ..."`` diagnostic on top of the rich one.
    """
    # Get node metadata from registry
    nodes_metadata = registry.get_nodes_metadata([node_type])
    if node_type not in nodes_metadata:
        return

    interface = nodes_metadata[node_type]["interface"]

    # Extract outputs with full structure
    for output in interface["outputs"]:
        if isinstance(output, str):
            key = output
            output_info: dict[str, Any] = {"type": "any", "node_id": node_id, "node_type": node_type}
        else:
            key = output["key"]
            output_info = {
                "type": output.get("type", "any"),
                "structure": output.get("structure", {}),
                "node_id": node_id,
                "node_type": node_type,
            }

        output_info = _enrich_code_result_output_type(key, output_info, code_annotations)
        if node_type == "llm" and key == "response":
            output_info = {**output_info, "type": _llm_response_type(node_params)}

        node_outputs[key] = output_info

        if enable_namespacing:
            namespaced_key = f"{node_id}.{key}"
            node_outputs[namespaced_key] = output_info
