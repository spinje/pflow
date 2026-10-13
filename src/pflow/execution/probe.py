"""Probe: run one node by type, outside any workflow — `pflow probe` and MCP `registry_run`.

Both channels call :func:`probe_node`, so a node runs, fails and is cached the same way on each:
the node goes through ``WorkflowRunner`` as a one-node workflow (validation, compilation, the
engine's failure records), and the channel only renders the :class:`ProbeResult`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from typing import Any

from pflow.core.diagnostic import Diagnostic, Severity, exception_to_diagnostics
from pflow.core.execution_cache import ExecutionCache
from pflow.core.security_utils import redact_sensitive, scrub_secret_values, secret_values
from pflow.core.validation_utils import get_parameter_validation_error, is_valid_parameter_name
from pflow.core.workflow.template_surfaces import param_mode
from pflow.execution.formatters.run_outcome import scrub_diagnostic
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner
from pflow.registry import Registry
from pflow.registry.node_id import normalize_node_id
from pflow.runtime.node_state import get_node_output

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProbeResult:
    """How one probe ended.

    ``ran`` is False when the probe was refused before the node started (an unknown node, a bad
    parameter, a validation error) — the caller's call is wrong, not the node.
    ``execution_id`` is set when the outputs were cached for ``read-fields``.
    On a failure ``outputs`` holds whatever the node wrote before failing.
    """

    node_type: str
    success: bool
    ran: bool
    outputs: dict[str, Any] = field(default_factory=dict)
    errors: list[Diagnostic] = field(default_factory=list)
    warnings: list[Diagnostic] = field(default_factory=list)
    execution_id: str | None = None
    execution_time_ms: int = 0


def probe_node(node_type: str, params: dict[str, Any]) -> ProbeResult:
    """Run the node ``node_type`` (a registry id or a short form of one) with ``params`` as its params.

    A ``${VAR}`` in a param that is not a body is expanded from the environment and
    ``pflow settings set-env`` first; a variable that is set nowhere refuses the probe.
    """
    nodes = Registry().load()
    resolved = normalize_node_id(node_type, set(nodes))
    if resolved is None:
        return _refused(node_type, [_unresolved_node_diagnostic(node_type, sorted(nodes))])

    bad_names = [name for name in params if not is_valid_parameter_name(name)]
    if bad_names:
        return _refused(resolved, [_bad_param_name_diagnostic(name, resolved) for name in bad_names])

    try:
        node_params = _expand_env_vars(resolved, params)
    except ValueError as missing:
        return _refused(resolved, [replace(d, node_id=resolved) for d in exception_to_diagnostics(missing)])

    # A probe is for discovery: it neither reads nor writes the node memo cache (`cache: False`
    # stops the write `cache_enabled=False` leaves on) and keeps no trace. Runner params stay
    # empty — the user's params are the node's params, never workflow inputs.
    node = {"id": resolved, "type": resolved, "params": node_params, "cache": False}
    workflow_ir = {"nodes": [node], "edges": []}
    result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig(cache_enabled=False, trace_enabled=False))
    execution_time_ms = int(result.metrics.workflow_nodes.get(resolved, 0)) if result.metrics else 0
    # A probe's params are its inputs: their sensitive-named values (and every `pflow settings` value)
    # never print, wherever they travelled — the rule `build_run_outcome` applies to a run.
    secrets = _with_json_escaped_forms(secret_values(node_params))
    errors = [scrub_diagnostic(d, secrets) for d in result.errors]
    warnings = [scrub_diagnostic(d, secrets) for d in result.diagnostics if d.severity is not Severity.ERROR]
    # Wherever the run left them: a failure record, or the node's own key when the run failed after
    # the node completed (a non-interactive escalation).
    outputs = scrub_secret_values(_as_outputs(get_node_output(result.shared_after, resolved)), secrets)

    if not result.success:
        return ProbeResult(
            node_type=resolved,
            success=False,
            ran=result.engine_started,
            outputs=outputs,
            errors=errors,
            warnings=warnings,
            execution_time_ms=execution_time_ms,
        )

    return ProbeResult(
        node_type=resolved,
        success=True,
        ran=True,
        outputs=outputs,
        warnings=warnings,
        execution_id=_cache_outputs(resolved, scrub_secret_values(redact_sensitive(params), secrets), outputs),
        execution_time_ms=execution_time_ms,
    )


def _with_json_escaped_forms(secrets: frozenset[str]) -> frozenset[str]:
    """``secrets`` plus each one as JSON text spells it (a quote or backslash escaped, non-ASCII as
    ``\\u``): output that is JSON text holds that form, and the probe's renderer and ``read-fields``
    decode it back to the secret."""
    escaped = {json.dumps(secret, ensure_ascii=as_ascii)[1:-1] for secret in secrets for as_ascii in (True, False)}
    return secrets | escaped


def _refused(node_type: str, errors: list[Diagnostic]) -> ProbeResult:
    return ProbeResult(node_type=node_type, success=False, ran=False, errors=errors)


def _as_outputs(value: Any) -> dict[str, Any]:
    if value is None:  # the node never ran
        return {}
    return value if isinstance(value, dict) else {"result": value}


def _expand_env_vars(node_type: str, params: dict[str, Any]) -> dict[str, Any]:
    """``params`` with ``${VAR}`` expanded — never in a body or embedded code (a shell command, a
    code block, JavaScript an MCP tool runs), whose ``${…}`` belongs to that language."""
    from pflow.mcp.auth_utils import expand_env_vars_nested  # the `pflow.mcp` package loads the MCP SDK

    expandable = {key: value for key, value in params.items() if param_mode(node_type, key) not in ("body", "embedded")}
    expanded = expand_env_vars_nested(expandable, include_settings=True, raise_on_missing=True)
    return {key: expanded.get(key, value) for key, value in params.items()}


def _cache_outputs(node_type: str, params: dict[str, Any], outputs: dict[str, Any]) -> str | None:
    """Store the outputs for ``read-fields``; the execution id, or None when they could not be stored.

    The params cached are the caller's, before ``${VAR}`` expansion, so a secret from the
    environment never lands in the cache.
    """
    execution_id = ExecutionCache.generate_execution_id()
    try:  # the node has already run: a cache that cannot be written loses the id, never the result
        ExecutionCache().store(execution_id, node_type, params, outputs)
    except Exception as error:
        logger.warning("Failed to cache probe execution %s: %s", execution_id, error)
        return None
    return execution_id


def _unresolved_node_diagnostic(node_type: str, available_nodes: list[str]) -> Diagnostic:
    """Node Not Found — or Ambiguous Node when a short form matches several ids — with candidates."""
    normalized = node_type.replace("-", "_")
    matches = sorted(node for node in available_nodes if node.endswith(node_type) or node.endswith(normalized))
    if len(matches) > 1:
        return Diagnostic(
            severity=Severity.ERROR,
            message=f"Node '{node_type}' matches more than one node.",
            title="Ambiguous Node",
            suggestions=["Use the full node id of one of the matches."],
            source="registry",
            context={"category": "not_found", "similar_names": matches},
        )
    return _node_not_found_diagnostic(node_type, available_nodes)


def _node_not_found_diagnostic(node_type: str, available_nodes: list[str]) -> Diagnostic:
    """Node Not Found, with the nearest node ids — or, when none is near, the first ten."""
    from pflow.core.suggestion_utils import find_similar_items

    similar = find_similar_items(node_type, available_nodes, max_results=5, method="substring")
    if not similar:
        similar = sorted(available_nodes)[:10]
    return Diagnostic(
        severity=Severity.ERROR,
        message=f"Node '{node_type}' not found in registry.",
        title="Node Not Found",
        suggestions=_node_discovery_suggestions(node_type),
        source="registry",
        context={"category": "not_found", "similar_names": similar},
    )


def _node_discovery_suggestions(node_type: str) -> list[str]:
    if node_type.startswith("mcp-"):
        return [
            "Use 'pflow mcp find' to search MCP tools by intent",
            "Use 'pflow mcp list' to see all available MCP tools",
        ]
    return [
        "Core node types: shell, http, llm, code, read-file, write-file",
        "Use 'pflow mcp list' to see available MCP tools",
    ]


def _bad_param_name_diagnostic(name: str, node_type: str) -> Diagnostic:
    return Diagnostic(
        severity=Severity.ERROR,
        message=get_parameter_validation_error(name),
        node_id=node_type,
        source="validator",
        context={"category": "validation"},
    )
