"""IR structure validation and input preparation for the compilation pipeline.

- validate_ir_structure: the basic shape of workflow IR (nodes, edges arrays)
- prepare_inputs: the workflow input boundary — resolve, type, report
- check_supplied_inputs: the same boundary over the supplied values only
- check_parameter_names: the name rule over a caller's parameter names
"""

import copy
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.exceptions import CompilationError, InputTypeError
from pflow.core.llm_config import is_settings_injected
from pflow.core.param_coercion import InputSource, coerce_declared_input
from pflow.core.types import input_usage
from pflow.core.validation_utils import (
    RESERVED_NAME_PREFIX,
    VALIDATION_PLACEHOLDER,
    get_parameter_validation_error,
    is_valid_parameter_name,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Caller:
    """Who supplied the values, beyond each value's source label — it places every problem:
    the run being resumed (named in a ``recorded`` value's fix line), or the parent step passing
    a sub-workflow its inputs (paths point at that step's ``inputs:``)."""

    resumed_run: str | None = None
    step: str | None = None
    sub_workflow_path: str | None = None

    @property
    def workflow(self) -> str:
        """The workflow whose inputs these are, mid-sentence."""
        return (self.sub_workflow_path or "the sub-workflow") if self.step else "this workflow"

    @property
    def subject(self) -> str:
        """The same workflow opening a sentence."""
        return (self.sub_workflow_path or "The sub-workflow") if self.step else "Workflow"

    def path(self, name: str) -> str:
        """Where the value for input ``name`` is supplied."""
        return f"nodes[id={self.step}].params.inputs.{name}" if self.step else f"inputs.{name}"

    def required_fix(self, name: str, spec: dict[str, Any]) -> str:
        """The remedy for a missing required input — at a sub-workflow boundary only the parent can
        pass it; at the root, an argument (or the pipe) or the same name in the environment or settings."""
        if self.step:
            return (
                f"Pass it under step '{self.step}' `inputs:` "
                "(a required sub-workflow input is never read from the environment or settings)"
            )
        usage = input_usage(spec)
        passed = f"Pipe it on stdin or pass {usage.argument(name)}" if usage.stdin else f"Pass {usage.argument(name)}"
        return (
            f"{passed} — or set the name '{name}' in the shell environment, "
            f"or once with: pflow settings set-env {name} {usage.type.placeholder}"
        )

    def context(self) -> dict[str, str]:
        if not self.step:
            return {}
        return {"sub_workflow_step": self.step, "sub_workflow_path": self.sub_workflow_path or ""}

    def place(self, error: InputTypeError) -> Diagnostic:
        located = error.located(resumed_run=self.resumed_run, step=self.step, sub_workflow_path=self.sub_workflow_path)
        return located.to_diagnostics()[0]

    def error(self, message: str, path: str, suggestion: str = "") -> Diagnostic:
        """An input-boundary error that is not a type mismatch (missing, empty, undeclared, misnamed)."""
        return Diagnostic(
            severity=Severity.ERROR,
            message=message,
            title="Validation Error",
            suggestions=[suggestion] if suggestion else None,
            source="validation",
            context={"category": "validation", "path": path, **self.context()},
        )


def _fallback_value(
    input_name: str, input_spec: dict[str, Any], settings_env: Mapping[str, str], caller: _Caller
) -> tuple[Any, InputSource | None]:
    """A value for an input nobody supplied: shell environment → settings.env → declared default.

    ``(None, None)`` when none has one (a ``default: null`` is no value). At a sub-workflow
    boundary a required input (``input_usage``: no default, or ``""``) has none: it comes from the parent, never from
    the environment or settings (as the validator rules statically, ``_check_required_inputs``).
    A container default is a fresh copy every time — the IR's own object is never handed to a run.
    """
    if caller.step and input_usage(input_spec).required:
        return None, None
    if input_name in os.environ:
        # CLI/MCP startup copies settings.env into the environment, never over an exported name.
        return os.environ[input_name], "settings" if is_settings_injected(input_name) else "env"
    if input_name in settings_env:
        return settings_env[input_name], "settings"
    if input_spec.get("default") is not None:
        return copy.deepcopy(input_spec["default"]), "default"
    return None, None


def _resolve_input(
    input_name: str,
    input_spec: dict[str, Any],
    supplied: Any,
    supplied_source: InputSource,
    settings_env: Mapping[str, str],
    caller: _Caller,
) -> tuple[Diagnostic | None, Any, InputSource | None]:
    """One declared input: ``(problem, typed value, source)``; ``source`` is ``None`` when no value exists."""
    value, source = (
        (supplied, supplied_source)
        if supplied is not None
        else _fallback_value(input_name, input_spec, settings_env, caller)
    )
    description = input_spec.get("description", "No description provided")
    is_required = input_spec.get("required", True)
    if source is None:
        if is_required:
            message = f"{caller.subject} requires input '{input_name}': {description}"
            return (
                caller.error(message, caller.path(input_name), caller.required_fix(input_name, input_spec)),
                None,
                None,
            )
        return None, None, None
    if is_required and value == "":
        origin = "" if supplied is not None else f" (resolved from {source})"
        if input_usage(input_spec).required:
            message, fix = f"Required input '{input_name}' is empty{origin}: {description}", "Provide a non-empty value"
        else:  # its default makes it optional to leave out — but not to pass empty
            message = f"Input '{input_name}' is empty{origin}: {description}"
            fix = "Provide a non-empty value, or leave it out to use its default"
        return caller.error(message, caller.path(input_name), fix), None, source
    try:
        return None, coerce_declared_input(input_name, input_spec.get("type"), value, source=source), source
    except InputTypeError as e:
        return caller.place(e), None, source


def _is_framework_param_key(key: str) -> bool:
    """Whether ``key`` is one pflow itself injects into ``initial_params`` before
    ``prepare_inputs`` runs: the runner's ``_pflow_workflow_file`` or a compiler ``__*__`` key
    (``__template_resolution_mode__``).

    Any other underscore-prefixed name (e.g. ``_foo``) is user-authored and surfaces as an
    extra, so a typo like ``_foo`` for declared ``foo`` is visible. A caller cannot supply
    either framework form: the name rule rejects both where parameters enter
    (:func:`check_parameter_names` in the runner, the CLI and MCP boundaries), and declared
    input names are checked by it below.
    """
    return key.startswith(RESERVED_NAME_PREFIX) or (key.startswith("__") and key.endswith("__"))


def _check_undeclared_extras(
    declared_names: set[str], provided_params: Mapping[str, Any], caller: _Caller
) -> list[Diagnostic]:
    """Detect keys in ``provided_params`` that are not declared as workflow inputs.

    Framework-internal keys are filtered via :func:`_is_framework_param_key`.
    Symmetric with the sub-workflow check in
    ``WorkflowValidator._check_required_inputs`` (GH #288 / task 153).

    Returns one Diagnostic per undeclared key.
    """
    # Framework keys ride a root run's params; a parent passes a child only its `inputs:` map,
    # so there every undeclared key is the parent's (a `__loop_active__` would steer the child).
    user_provided = [k for k in provided_params if caller.step or not _is_framework_param_key(k)]
    extras = sorted(set(user_provided) - declared_names)
    if not extras:
        return []

    from pflow.core.suggestion_utils import find_similar_items

    errors: list[Diagnostic] = []
    sorted_declared = sorted(declared_names)
    for extra in extras:
        if sorted_declared:
            similar = find_similar_items(extra, sorted_declared, max_results=2, method="fuzzy")
            message = f"Unknown input '{extra}' — not declared by {caller.workflow}."
            suggestion = (
                f"Did you mean '{similar[0]}'?" if similar else f"Available inputs: {', '.join(sorted_declared)}"
            )
        else:
            message = f"Unknown input '{extra}' — {caller.workflow} declares no inputs."
            suggestion = "Remove the parameter, or declare it in ## Inputs."
        errors.append(caller.error(message, caller.path(extra), suggestion))
    return errors


def validate_ir_structure(ir_dict: dict[str, Any]) -> None:
    """Validate basic IR structure (nodes, edges arrays).

    This performs minimal structural validation to ensure the IR has
    the required top-level keys. Full validation should be done by
    the IR schema validator before compilation.

    Args:
        ir_dict: The IR dictionary to validate

    Raises:
        CompilationError: If required keys are missing or have wrong types
    """
    logger.debug("Validating IR structure", extra={"phase": "validation"})

    # Check for required 'nodes' key
    if "nodes" not in ir_dict:
        raise CompilationError(
            "Missing 'nodes' key in IR", phase="validation", suggestion="IR must contain 'nodes' array"
        )

    # Check nodes is a list
    if not isinstance(ir_dict["nodes"], list):
        raise CompilationError(
            f"'nodes' must be an array, got {type(ir_dict['nodes']).__name__}",
            phase="validation",
            suggestion="Ensure 'nodes' is an array of node objects",
        )

    # Check for required 'edges' key
    if "edges" not in ir_dict:
        raise CompilationError(
            "Missing 'edges' key in IR", phase="validation", suggestion="IR must contain 'edges' array (can be empty)"
        )

    # Check edges is a list
    if not isinstance(ir_dict["edges"], list):
        raise CompilationError(
            f"'edges' must be an array, got {type(ir_dict['edges']).__name__}",
            phase="validation",
            suggestion="Ensure 'edges' is an array of edge objects",
        )

    logger.debug(
        "IR structure validated",
        extra={"phase": "validation", "node_count": len(ir_dict["nodes"]), "edge_count": len(ir_dict["edges"])},
    )


def prepare_inputs(
    workflow_ir: dict[str, Any],
    provided_params: Mapping[str, Any],
    settings_env: Mapping[str, str] | None = None,
    *,
    input_sources: Mapping[str, InputSource] | None = None,
    resumed_run: str | None = None,
    step: str | None = None,
    sub_workflow_path: str | None = None,
) -> tuple[list[Diagnostic], dict[str, Any], set[str]]:
    """The workflow input boundary: resolve each declared input, type it, report what is wrong.

    Per declared input, the first value found wins: supplied (a supplied ``None`` is no
    value) → shell environment → settings.env → declared default (``_fallback_value``; at a
    sub-workflow boundary a required input with no default takes no fallback); with none, a
    required input (``required`` defaults to true) is an error and an optional one is ``None``.
    Every value found is typed by ``coerce_declared_input`` with its source — supplied
    values take theirs from ``input_sources`` (absent key: ``"argument"``). ``resumed_run``
    is the id of the run whose recorded inputs are being replayed, named in a ``recorded``
    value's fix line; ``step`` / ``sub_workflow_path`` name the parent step and the child at
    a sub-workflow boundary, and every problem is placed at that step's ``inputs:``. Does not
    mutate ``provided_params``.

    Returns:
        ``(errors, updates, settings_names)``: one Diagnostic per problem (type mismatch,
        missing or empty required input, undeclared key, invalid name, several ``stdin: true``
        inputs); the values to apply over ``provided_params`` — every input resolved by a
        fallback and every supplied value the coercer changed; the names whose value came
        from settings.env.
    """
    errors: list[Diagnostic] = []
    updates: dict[str, Any] = {}
    settings_names: set[str] = set()
    settings_env = settings_env or {}
    input_sources = input_sources or {}
    caller = _Caller(resumed_run=resumed_run, step=step, sub_workflow_path=sub_workflow_path)
    inputs: dict[str, Any] = workflow_ir.get("inputs") or {}

    stdin_inputs = [name for name, spec in inputs.items() if spec.get("stdin") is True]
    if len(stdin_inputs) > 1:
        errors.append(
            caller.error(
                f"Multiple inputs marked `- stdin: true`: {', '.join(stdin_inputs)}",
                "inputs",
                "Only one input can receive piped stdin",
            )
        )

    for input_name, input_spec in inputs.items():
        if not is_valid_parameter_name(input_name):
            errors.append(
                caller.error(
                    get_parameter_validation_error(input_name, "input"),
                    f"inputs.{input_name}",
                    "Rename the input",
                )
            )
            continue
        supplied = provided_params.get(input_name)
        problem, value, source = _resolve_input(
            input_name, input_spec, supplied, input_sources.get(input_name, "argument"), settings_env, caller
        )
        if problem is not None:
            errors.append(problem)
            continue
        if input_name not in provided_params or value is not supplied:
            updates[input_name] = value
        if source == "settings":
            settings_names.add(input_name)

    # Reject undeclared extras (GH #288, symmetric with the sub-workflow check in
    # WorkflowValidator._check_required_inputs).
    errors.extend(_check_undeclared_extras(set(inputs), provided_params, caller))
    return errors, updates, settings_names


def check_supplied_inputs(
    workflow_ir: dict[str, Any],
    provided_params: Mapping[str, Any],
    *,
    input_sources: Mapping[str, InputSource] | None = None,
) -> tuple[list[Diagnostic], dict[str, Any]]:
    """``prepare_inputs`` over the supplied values only — for checks that run without a full
    set of inputs (``--validate-only``, cache analysis).

    An input nobody supplied (or supplied as ``None``) stands in as ``VALIDATION_PLACEHOLDER``:
    it is neither required nor resolved from the environment, settings or its default. Returns
    the problems with the supplied values only (type mismatch, undeclared key, empty required
    text — the declarations' own problems are the validator's) and the supplied values typed
    by their declarations.
    """
    supplied = {name: value for name, value in provided_params.items() if value is not None}
    padded = {**dict.fromkeys(workflow_ir.get("inputs") or {}, VALIDATION_PLACEHOLDER), **supplied}
    errors, updates, _ = prepare_inputs(workflow_ir, padded, input_sources=input_sources)
    supplied_paths = {f"inputs.{name}" for name in supplied}
    problems = [error for error in errors if (error.context or {}).get("path") in supplied_paths]
    return problems, {name: updates.get(name, value) for name, value in supplied.items()}


def check_parameter_names(provided_params: Mapping[str, Any]) -> list[Diagnostic]:
    """One error per caller-supplied parameter whose name breaks the name rule
    (``is_valid_parameter_name``) — e.g. a reserved ``_pflow_*`` or ``__*__`` key, which would
    otherwise seed pflow's own shared-store state. Run on the caller's names only, before pflow
    adds its own keys (``WorkflowRunner._prepare_workflow``).
    """
    caller = _Caller()
    return [
        caller.error(
            get_parameter_validation_error(name, "parameter"),
            caller.path(name),
            "Remove it — no workflow input can have this name",
        )
        for name in provided_params
        if not is_valid_parameter_name(name)
    ]
