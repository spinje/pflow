"""Template type validation (Passes 6, 7, and 9).

Pass 6: Validates template variable types match parameter expectations.
Pass 7: Blocks structured data (dict/list) in shell command parameters.
Pass 9: Validates code-node input annotations against template source types.
"""

import re
from typing import Any, Optional

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.registry import Registry
from pflow.runtime.template_resolver import TemplateResolver
from pflow.runtime.template_validation.type_checker import (
    get_parameter_type,
    infer_template_type,
    is_type_compatible,
)

# Pattern to detect templates exactly wrapped in single quotes: '${var}'
# This is an escape hatch for structured types in shell commands.
#
# Matches:   '${var}', '${node.field}', '${data.items[0].name}'
# Does NOT match: '${a} ${b}', 'prefix ${var}', '$${var}' (escaped)
#
# Note: Array indices use [] not {}, so [^}]+ correctly captures paths
# like 'data.items[0].value' without stopping at brackets.
_QUOTED_TEMPLATE_PATTERN = re.compile(r"'\$\{([^}]+)\}'")

# Types that are safe in shell commands (string-like or unknown type)
# When a union contains one of these, runtime coercion to string is acceptable.
_SHELL_SAFE_TYPES = {"str", "string", "any"}


def _extract_base_type(type_str: str) -> str:
    """Extract base type from generic type string.

    Generic types like list[dict] or dict[str, any] have a base type
    (list, dict) that determines their shell command compatibility.

    Examples:
        list[dict] -> list
        dict[str, any] -> dict
        str -> str
        list -> list

    Args:
        type_str: Type string, possibly with generic parameters

    Returns:
        Base type without generic parameters
    """
    return type_str.split("[")[0]


def _is_shell_safe_type(inferred_type: str, blocked_types: set[str]) -> tuple[bool, str | None]:
    """Check if a type is safe for shell command embedding.

    Args:
        inferred_type: The inferred type string (may be union like "dict|str")
        blocked_types: Set of blocked type names

    Returns:
        Tuple of (is_safe, blocked_type_if_not_safe)
        - (True, None) if type is safe
        - (False, "dict") if blocked, with the first blocked type
    """
    # Split union and get base type for each component
    type_parts = [t.strip() for t in inferred_type.split("|")]
    base_types = [_extract_base_type(t) for t in type_parts]

    # Tier 1: If union contains a safe base type (str, string, any), allow it
    if any(t in _SHELL_SAFE_TYPES for t in base_types):
        return (True, None)

    # Check if any base type is blocked
    blocked_parts = [t for t in base_types if t in blocked_types]
    if blocked_parts:
        return (False, blocked_parts[0])

    return (True, None)


# ---------------------------------------------------------------------------
# Pass 6: Type matching
# ---------------------------------------------------------------------------


def validate_template_types(
    workflow_ir: dict[str, Any], node_outputs: dict[str, Any], registry: Registry
) -> list[Diagnostic]:
    """Validate template variable types match parameter expectations.

    Args:
        workflow_ir: Workflow IR
        node_outputs: Node output metadata from registry
        registry: Registry instance

    Returns:
        Type mismatch diagnostics
    """
    diagnostics: list[Diagnostic] = []

    for node in workflow_ir.get("nodes", []):
        node_type = node.get("type")
        node_id = node.get("id")
        params = node.get("params", {})

        for param_name, param_value in params.items():
            expected_type = get_parameter_type(node_type, param_name, registry)
            _check_param_type(param_name, param_value, expected_type, node_id, workflow_ir, node_outputs, diagnostics)

    return diagnostics


def _check_param_type(
    param_name: str,
    value: Any,
    expected_type: Optional[str],
    node_id: str,
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any],
    diagnostics: list[Diagnostic],
) -> None:
    """Recursively validate template types in a parameter value."""
    if isinstance(value, str) and TemplateResolver.has_templates(value):
        if expected_type and expected_type != "any":
            _check_string_template_types(
                param_name,
                value,
                expected_type,
                node_id,
                workflow_ir,
                node_outputs,
                diagnostics,
            )
    elif isinstance(value, dict):
        for val in value.values():
            _check_param_type(param_name, val, None, node_id, workflow_ir, node_outputs, diagnostics)
    elif isinstance(value, list):
        for item in value:
            _check_param_type(param_name, item, None, node_id, workflow_ir, node_outputs, diagnostics)


def _check_string_template_types(
    param_name: str,
    value: str,
    expected_type: str,
    node_id: str,
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any],
    diagnostics: list[Diagnostic],
) -> None:
    """Validate template types in a string parameter value."""
    templates = TemplateResolver.extract_variables(value)
    for template in templates:
        inferred_type = infer_template_type(template, workflow_ir, node_outputs)
        if not inferred_type or inferred_type == "any":
            continue
        if not is_type_compatible(inferred_type, expected_type):
            suggestions: list[str] | None = None
            available_fields: list[str] = []
            if inferred_type in ["dict", "list", "object"] and expected_type in ["str", "string"]:
                suggestions, available_fields = _generate_type_fix_suggestions(template, node_outputs, expected_type)

            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    source="validator",
                    title="Validation Error",
                    node_id=node_id,
                    message=(
                        f"Type mismatch in parameter '{param_name}': template ${{{template}}} has type "
                        f"'{inferred_type}' but parameter expects '{expected_type}'."
                    ),
                    suggestions=suggestions,
                    context={
                        "category": "validation",
                        "path": f"nodes[id={node_id}].params.{param_name}",
                        "template": f"${{{template}}}",
                        "inferred_type": inferred_type,
                        "expected_type": expected_type,
                        "available_fields": available_fields or None,
                        "available_fields_total": len(available_fields) if available_fields else None,
                        "available_fields_label": "matching outputs" if available_fields else None,
                    },
                )
            )


# ---------------------------------------------------------------------------
# Pass 7: Shell command types
# ---------------------------------------------------------------------------


def _build_quoted_templates(command: str) -> set[str]:
    """Extract templates wrapped in single quotes as escape hatch.

    Splits coalesce operands so '${a ?? b}' exempts both 'a' and 'b'.
    """
    result: set[str] = set()
    for match in _QUOTED_TEMPLATE_PATTERN.finditer(command):
        for operand in TemplateResolver.split_coalesce_operands(match.group(1)):
            result.add(operand)
    return result


def validate_shell_command_types(workflow_ir: dict[str, Any], node_outputs: dict[str, Any]) -> list[Diagnostic]:
    """Block dict/list types in shell command parameters.

    Shell commands cannot safely handle JSON embedded in command strings
    due to shell escaping issues. This check runs BEFORE template resolution
    to catch the problem at validation time rather than runtime.

    The general type checker allows dict/list → str (for LLM prompts, HTTP bodies),
    but shell commands are special - embedded JSON breaks shell parsing.

    Validation has three tiers:
    1. Fix 0: Extract base types from generics (list[dict] → list) before checking
    2. Tier 1: Auto-allow unions containing safe types (str, string, any)
    3. Tier 2: Allow templates wrapped in single quotes '${var}' as an escape hatch

    Args:
        workflow_ir: Workflow IR
        node_outputs: Node output metadata from registry

    Returns:
        Diagnostics for structured data in shell commands
    """
    diagnostics: list[Diagnostic] = []
    # Types that cannot be safely embedded in shell command strings.
    # Includes both Python type names (dict, list) and JSON Schema names (object, array)
    # since workflow IR may use either convention.
    SHELL_BLOCKED_TYPES = {"dict", "object", "list", "array"}

    for node in workflow_ir.get("nodes", []):
        node_type = node.get("type")
        node_id = node.get("id")

        # Only check shell nodes
        if node_type != "shell":
            continue

        params = node.get("params", {})
        command = params.get("command", "")

        # Skip if command has no templates
        if not isinstance(command, str) or not TemplateResolver.has_templates(command):
            continue

        # Tier 2: Find templates exactly wrapped in single quotes (escape hatch)
        # Pattern '${var}' signals user accepts runtime coercion to string
        quoted_templates = _build_quoted_templates(command)

        # Check each template in the command and collect blocked ones
        templates = TemplateResolver.extract_variables(command)
        blocked_templates: list[tuple[str, str]] = []  # (template, type)

        for template in templates:
            # Tier 2: Skip if template is quoted (user accepts coercion)
            if template in quoted_templates:
                continue

            inferred_type = infer_template_type(template, workflow_ir, node_outputs)

            # Skip if cannot infer type (will be caught by path validation)
            if not inferred_type:
                continue

            # Check if type is safe (handles Fix 0 and Tier 1)
            is_safe, blocked_type = _is_shell_safe_type(inferred_type, SHELL_BLOCKED_TYPES)
            if not is_safe and blocked_type:
                blocked_templates.append((template, blocked_type))

        # Generate a single consolidated error if any templates are blocked
        if blocked_templates:
            display_cmd = command if len(command) <= 60 else command[:57] + "..."

            if len(blocked_templates) == 1:
                # Single template - simple case
                template, blocked_type = blocked_templates[0]
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.ERROR,
                        source="validator",
                        title="Validation Error",
                        node_id=node_id,
                        message=(
                            f"Shell node '{node_id}': cannot use ${{{template}}} (type: {blocked_type}) "
                            f"in command parameter — embedded {blocked_type} breaks shell parsing."
                        ),
                        suggestions=[
                            f"Access a specific field: ${{{template}.fieldname}}",
                            f'Use stdin for the whole object: stdin: "${{{template}}}", command: "jq \'.field\'"',
                            f"Quote the template to accept JSON coercion: '${{{template}}}'",
                        ],
                        context={
                            "category": "validation",
                            "path": f"nodes[id={node_id}].params.command",
                            "template": f"${{{template}}}",
                            "blocked_type": blocked_type,
                            "shell_command": display_cmd,
                        },
                    )
                )
            else:
                # Multiple templates - need different approach
                template_list = ", ".join(f"${{{t}}} ({typ})" for t, typ in blocked_templates)
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.ERROR,
                        source="validator",
                        title="Validation Error",
                        node_id=node_id,
                        message=(
                            f"Shell node '{node_id}': multiple structured data templates in command: "
                            f"{template_list}. Shell commands can only receive ONE data source via stdin."
                        ),
                        suggestions=[
                            "Use temp files: write each data source via write-file nodes, then read in shell.",
                            "Process each data source in separate shell nodes, then combine results.",
                            "Pass one via stdin and reference another via file.",
                            "Quote the template to accept JSON coercion: '${var}'",
                        ],
                        context={
                            "category": "validation",
                            "path": f"nodes[id={node_id}].params.command",
                            "shell_command": display_cmd,
                            "blocked_templates": [
                                {"template": f"${{{template_name}}}", "type": blocked_type_name}
                                for template_name, blocked_type_name in blocked_templates
                            ],
                        },
                    )
                )

    return diagnostics


# ---------------------------------------------------------------------------
# Type fix suggestions
# ---------------------------------------------------------------------------


def _generate_type_fix_suggestions(
    template: str, node_outputs: dict[str, Any], expected_type: str
) -> tuple[list[str], list[str]]:
    """Generate structured suggestions for type mismatches with actual available fields.

    Args:
        template: The template variable that has the wrong type
        node_outputs: Node output metadata from registry
        expected_type: The type that was expected

    Returns:
        Tuple of (suggestions, available_fields)
    """
    # For nested templates like node.output.field, we need to traverse to find structure
    # Find the structure for this template by traversing
    structure = None
    for key in node_outputs:
        if template.startswith(key + ".") or template == key:
            output_info = node_outputs[key]
            remaining_path = template[len(key) :].lstrip(".")

            if not remaining_path:
                # This IS the base output
                structure = output_info.get("structure", {})
                break
            else:
                # Need to traverse nested structure
                structure = _traverse_to_structure(output_info.get("structure", {}), remaining_path)
                if structure:
                    break

    if not structure:
        return ([f"Access a specific field, for example ${{{template}.field}}.", "Serialize the value to JSON."], [])

    # Find fields that match the expected type
    matching_fields = []
    for field_name, field_info in structure.items():
        if isinstance(field_info, dict) and "type" in field_info:
            field_type = field_info["type"]
            # Check if this field matches the expected type
            if field_type in [expected_type, "str", "string"] and expected_type in ["str", "string"]:
                matching_fields.append(field_name)

    if matching_fields:
        suggestions = [f"Use ${{{template}.{field}}}" for field in matching_fields[:5]]
        available_fields = [f"${{{template}.{field}}}" for field in matching_fields]
        return (suggestions, available_fields)
    return (["Access a nested field or serialize the value to JSON."], [])


def _infer_missing_annotation_type(
    key: str,
    inputs: dict[str, Any],
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any],
) -> Optional[str]:
    """Infer a Python-display type for a missing code-node input annotation.

    Returns the inferred Python name (``"list"``, ``"dict"``, ``"str"``, …)
    when ``inputs[key]`` is a **simple** template (``"${ref}"`` with nothing
    else). Complex templates (``"prefix ${ref}"``) coerce to ``str`` at
    runtime regardless of the source type, so the inferred runtime type is
    always ``"str"`` in that case.

    Returns ``None`` when the type can't be inferred — caller falls back to
    the ``<type>`` placeholder in the suggestion.
    """
    from pflow.nodes.python.python_code import s1_type_to_python_display

    value = inputs.get(key)
    if not isinstance(value, str) or not TemplateResolver.has_templates(value):
        return None

    # Complex templates (text surrounding the template, or multiple templates)
    # resolve to strings at runtime — preserve that contract in the suggestion.
    if not TemplateResolver.is_simple_template(value):
        return "str"

    templates = TemplateResolver.extract_variables(value)
    if not templates:
        return None
    for template in templates:
        inferred = infer_template_type(template, workflow_ir, node_outputs)
        if inferred and inferred != "any":
            return s1_type_to_python_display(inferred)
    return None


def _build_missing_code_annotation_diagnostics(
    node_id: str,
    input_keys: set[str],
    annotation_keys: set[str],
    inputs: dict[str, Any],
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any],
) -> list[Diagnostic]:
    """Build diagnostics for inputs that are missing code annotations.

    When the upstream type can be inferred from the template binding, the
    suggestion names a concrete annotation (``x: list``) instead of the
    generic ``<type>`` placeholder — so agents can copy-paste the fix.
    """
    diagnostics: list[Diagnostic] = []
    for key in sorted(input_keys - annotation_keys):
        inferred_name = _infer_missing_annotation_type(key, inputs, workflow_ir, node_outputs)
        if inferred_name is not None:
            suggestion = f"Add an annotation (in params.code): {key}: {inferred_name}  (inferred from {inputs[key]})"
        else:
            suggestion = f"Add an annotation (in params.code): {key}: <type>"
        context: dict[str, Any] = {
            "category": "validation",
            "path": f"nodes[id={node_id}].params.inputs.{key}",
            "node_type": "code",
            "input_key": key,
        }
        if inferred_name is not None:
            context["inferred_type"] = inferred_name
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                source="validator",
                title="Validation Error",
                node_id=node_id,
                message=f"Input '{key}' is missing a type annotation in the code block.",
                suggestions=[suggestion],
                context=context,
            )
        )
    return diagnostics


def _build_orphan_code_annotation_diagnostics(
    node_id: str,
    input_keys: set[str],
    annotation_keys: set[str],
    annotations: dict[str, str],
    load_refs: set[str],
    batch_alias: Optional[str],
) -> list[Diagnostic]:
    """Build diagnostics for annotations with no matching input binding.

    Chooses a canonical single-fix suggestion per orphan (Task 154 pattern):

    - Orphan key appears as ``ast.Name(ctx=Load())`` in the code body → the
      author expected the variable to be bound at runtime. Canonical fix is
      "Add to the inputs dict". Typo-level fuzzy matches against existing
      input keys are surfaced via ``similar_names``.
    - Orphan key has no Load reference → dead annotation. Canonical fix is
      "Remove the annotation".

    ``batch_alias`` (when present) narrows the "add to inputs" suggestion to
    the exact source template (``${item}``) for the common batch-code pattern,
    skipping the ``${<source>}`` placeholder.
    """
    from pflow.core.suggestion_utils import find_similar_items

    diagnostics: list[Diagnostic] = []
    for key in sorted(annotation_keys - input_keys):
        annotation_str = annotations[key]
        is_used = key in load_refs
        context: dict[str, Any] = {
            "category": "validation",
            "path": f"nodes[id={node_id}].params.code",
            "node_type": "code",
            "annotation_key": key,
        }

        if is_used:
            # Batch alias is deterministic metadata and must win over fuzzy
            # matching. Otherwise a near-miss between `item` (the alias) and
            # a user input like `items` produces "Rename to 'items'", which
            # would break code that correctly reads the per-iteration `item`.
            if batch_alias and key == batch_alias:
                # The engine injects the batch alias into template resolution
                # only — code-exec requires an explicit binding. The canonical
                # fix is to route the alias through `inputs:` verbatim.
                fix = (
                    f"Add '{key}' to the inputs dict (in params.inputs): {key}: ${{{key}}} "
                    f"(binds the batch alias into the code block)"
                )
            else:
                similar = find_similar_items(key, sorted(input_keys), method="fuzzy", cutoff=0.6, max_results=3)
                if similar:
                    fix = f"Rename the annotation to '{similar[0]}' to match the existing input binding."
                    context["similar_names"] = similar
                else:
                    fix = f"Add '{key}' to the inputs dict (in params.inputs): {key}: ${{<source>}}"
        else:
            fix = f"Remove the annotation '{key}: {annotation_str}' — it is never read in the code."

        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                source="validator",
                title="Validation Error",
                node_id=node_id,
                message=f"Annotation '{key}: {annotation_str}' has no corresponding entry in 'inputs'.",
                suggestions=[fix],
                context=context,
            )
        )
    return diagnostics


def _build_simple_template_mismatch_diagnostic(
    node_id: str,
    key: str,
    template: str,
    annotation_str: str,
    expected_canonical: str,
    inferred_type: str,
    annotation_is_optional: bool,
    workflow_inputs: dict[str, Any],
) -> Diagnostic:
    """Build a Class 3 mismatch diagnostic for a single simple-template binding."""
    from pflow.nodes.python.python_code import s1_type_to_python_display

    display_inferred = s1_type_to_python_display(inferred_type)
    display_expected = s1_type_to_python_display(expected_canonical)
    suggested_annotation = f"{display_inferred} | None" if annotation_is_optional else display_inferred

    # Tailor the "change the source" wording to the template's origin.
    # Workflow inputs aren't "returned" by anything — telling the agent
    # to change a non-existent upstream node wastes cycles.
    root = TemplateResolver.extract_root_node_id(template) or template.split(".")[0]
    if root in workflow_inputs:
        source_fix = (
            f"Or change the workflow input declaration for '{root}' "
            f"to '- type: {display_expected}' (currently {display_inferred})"
        )
    else:
        source_fix = f"Or change ${{{template}}} to return {annotation_str}"

    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=(f"Input '{key}' expects {annotation_str} but receives {display_inferred} from ${{{template}}}."),
        suggestions=[
            f"Change the type annotation (in params.code): {key}: {suggested_annotation}",
            source_fix,
            f"Or accept any type (in params.code): {key}: Any",
        ],
        context={
            "category": "validation",
            "path": f"nodes[id={node_id}].params.inputs.{key}",
            "node_type": "code",
            "template": f"${{{template}}}",
            "input_key": key,
            "annotation": annotation_str,
            "inferred_type": display_inferred,
            "expected_type": display_expected,
        },
    )


def _build_complex_template_str_coercion_diagnostic(
    node_id: str,
    key: str,
    value: str,
    annotation_str: str,
    expected_canonical: str,
    annotation_is_optional: bool,
) -> Optional[Diagnostic]:
    """Emit a diagnostic when a complex template resolves to str and violates a non-str target.

    Runtime coerces ``"prefix ${x}"`` / ``"${a} ${b}"`` to str unconditionally
    (no JSON auto-parse for multi-fragment templates). This check is stricter
    than ``is_type_compatible("str", target)`` because the matrix treats
    ``str → dict/list`` as compatible for the simple-template path; the
    auto-parse doesn't apply here.

    Returns None when the target (``string`` / ``any``) accepts the coerced
    string — caller skips emission in that case.
    """
    from pflow.nodes.python.python_code import s1_type_to_python_display

    if expected_canonical in ("string", "any"):
        return None

    display_inferred = "str"
    display_expected = s1_type_to_python_display(expected_canonical)
    suggested_annotation = f"{display_inferred} | None" if annotation_is_optional else display_inferred
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=(
            f"Input '{key}' expects {annotation_str} but receives str from {value!r} "
            f"(complex templates are coerced to string at runtime)."
        ),
        suggestions=[
            f"Change the type annotation (in params.code): {key}: {suggested_annotation}",
            "Or drop the surrounding text so only a single template remains in the value",
            f"Or accept any type (in params.code): {key}: Any",
        ],
        context={
            "category": "validation",
            "path": f"nodes[id={node_id}].params.inputs.{key}",
            "node_type": "code",
            "template": value,
            "input_key": key,
            "annotation": annotation_str,
            "inferred_type": display_inferred,
            "expected_type": display_expected,
        },
    )


def _check_one_code_input_binding(
    node_id: str,
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any],
    code: str,
    key: str,
    value: Any,
    annotation_str: str,
    workflow_inputs: dict[str, Any],
) -> list[Diagnostic]:
    """Produce Class 3 diagnostics for one code-node input binding.

    Splits the per-input analysis out of the main builder to keep the
    orchestrator loop simple (below the cyclomatic-complexity limit).
    Returns an empty list for bindings that should skip the check
    (non-template values, Any targets, or compatible types).
    """
    from pflow.nodes.python.python_code import (
        _is_optional_type,
        extract_code_annotation_type,
    )

    if not isinstance(value, str) or not TemplateResolver.has_templates(value):
        return []

    expected_canonical = extract_code_annotation_type(code, key)
    if expected_canonical is None:
        return []
    annotation_is_optional = _is_optional_type(annotation_str)

    # Complex templates coerce to str at runtime — handle at the value level
    # rather than per embedded ref.
    if not TemplateResolver.is_simple_template(value):
        diag = _build_complex_template_str_coercion_diagnostic(
            node_id, key, value, annotation_str, expected_canonical, annotation_is_optional
        )
        return [diag] if diag is not None else []

    out: list[Diagnostic] = []
    for template in TemplateResolver.extract_variables(value):
        inferred_type = infer_template_type(template, workflow_ir, node_outputs)
        if not inferred_type or inferred_type == "any":
            continue
        if is_type_compatible(inferred_type, expected_canonical):
            continue
        out.append(
            _build_simple_template_mismatch_diagnostic(
                node_id,
                key,
                template,
                annotation_str,
                expected_canonical,
                inferred_type,
                annotation_is_optional,
                workflow_inputs,
            )
        )
    return out


def _build_code_annotation_type_diagnostics(
    node_id: str,
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any],
    code: str,
    inputs: dict[str, Any],
    annotations: dict[str, str],
    annotation_keys: set[str],
) -> list[Diagnostic]:
    """Build diagnostics for incompatible template source types."""
    diagnostics: list[Diagnostic] = []
    workflow_inputs = workflow_ir.get("inputs", {}) or {}

    for key, value in inputs.items():
        if key not in annotation_keys:
            continue
        diagnostics.extend(
            _check_one_code_input_binding(
                node_id, workflow_ir, node_outputs, code, key, value, annotations[key], workflow_inputs
            )
        )
    return diagnostics


# ---------------------------------------------------------------------------
# Pass 9: Code-node input annotation type matching
# ---------------------------------------------------------------------------


def validate_code_node_input_annotations(workflow_ir: dict[str, Any], node_outputs: dict[str, Any]) -> list[Diagnostic]:
    """Validate code-node input annotations against their template source types.

    Closes the boundary between a code node's ``inputs`` mapping and its Python
    code-block annotations:

    1. Input bound but annotation missing
    2. Annotation declared but no input bound
    3. Annotation type incompatible with inferred template source type

    Skip semantics intentionally mirror the runtime checks in
    ``python_code.py``: unknown types and ``any`` silently skip validation.
    """
    # Lazy import follows the existing runtime -> nodes pattern used by the
    # compiler for code-node annotation introspection.
    import ast as _ast

    from pflow.nodes.python.python_code import extract_code_load_references, extract_top_level_annotations

    diagnostics: list[Diagnostic] = []

    for node in workflow_ir.get("nodes", []):
        if node.get("type") != "code":
            continue

        node_id = node.get("id", "unknown")
        params = node.get("params", {})
        code = params.get("code")
        inputs = params.get("inputs", {})

        if not isinstance(code, str) or not isinstance(inputs, dict):
            continue

        # Skip Pass 9 entirely when the code has a SyntaxError — runtime
        # surfaces a clean line-numbered error and Pass 9 emitting extra
        # "missing annotation" / "orphan" diagnostics on top only obscures
        # the real issue. `extract_top_level_annotations` fails open with
        # `{}`, so without this check Pass 9 would proceed and over-report.
        try:
            _ast.parse(code)
        except SyntaxError:
            continue

        # Module-level annotations only — function/class locals are not
        # candidate code-node inputs. Using ``_extract_annotations`` here
        # would flag every ``def helper(): y: int = 1`` as an orphan.
        annotations = extract_top_level_annotations(code)

        input_keys = set(inputs.keys())
        # `result` / `next` are outputs / routing declarations, not inputs.
        # The batch alias (default "item") is NOT excluded here: the engine only
        # injects it into template resolution, not into code exec. Code nodes
        # using batch must explicitly bind `inputs: {item: ${item}}` or runtime
        # fails with "Undefined variable 'item'". Pass 9 correctly flags the
        # missing binding as Class 2 (orphan annotation with Load reference →
        # "Add 'item' to the inputs dict").
        annotation_keys = {key for key in annotations if key not in {"result", "next"}}
        # Load references disambiguate orphan annotations: a name read in the
        # body signals "add to inputs"; an unused annotation is dead code.
        load_refs = extract_code_load_references(code)
        # Batch alias is used to produce a specific `${alias}` suggestion when
        # the orphan is the batch iteration variable.
        batch_cfg = node.get("batch")
        batch_alias: Optional[str] = (batch_cfg.get("as") or "item") if isinstance(batch_cfg, dict) else None

        diagnostics.extend(
            _build_missing_code_annotation_diagnostics(
                node_id, input_keys, annotation_keys, inputs, workflow_ir, node_outputs
            )
        )
        diagnostics.extend(
            _build_orphan_code_annotation_diagnostics(
                node_id, input_keys, annotation_keys, annotations, load_refs, batch_alias
            )
        )
        diagnostics.extend(
            _build_code_annotation_type_diagnostics(
                node_id,
                workflow_ir,
                node_outputs,
                code,
                inputs,
                annotations,
                annotation_keys,
            )
        )

    return diagnostics


def _traverse_to_structure(structure: dict[str, Any], path: str) -> Optional[dict[str, Any]]:
    """Traverse nested structure to find the structure at a given path.

    Args:
        structure: The structure dict to traverse
        path: Dot-separated path like "author.login"

    Returns:
        The structure dict at that path, or None if not found
    """
    if not path or not structure:
        return structure

    path_parts = path.split(".")
    current = structure

    for part in path_parts:
        if part in current:
            field_info = current[part]
            if isinstance(field_info, dict):
                current = field_info.get("structure", {})
                if not current:
                    return None
            else:
                return None
        else:
            return None

    return current
