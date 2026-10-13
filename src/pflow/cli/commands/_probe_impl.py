"""Implementation of the `pflow probe` command: render a :func:`pflow.execution.probe.probe_node` result."""

from __future__ import annotations

import json
import sys
from typing import Any

import click

from pflow.cli.param_parsing import infer_type, parse_workflow_params
from pflow.core.stdio_reservation import reserve_stdout
from pflow.core.workflow.status import WorkflowStatus
from pflow.execution.formatters.run_outcome import (
    EXIT_CODES,
    EXIT_REJECTED,
    diagnostic_sections,
    errors_block,
    partition_surfaced_diagnostics,
)
from pflow.execution.probe import ProbeResult, probe_node


def execute_single_node(node_type: str, params: tuple[str, ...], output_format: str, verbose: bool) -> None:
    """Probe one node: its result on stdout, its failure on stderr (text) — exit 1 when the node
    ran and failed, 2 when the probe was refused before it ran."""
    # A node parameter has no workflow-input declaration, so its token type is guessed here.
    execution_params = {key: infer_type(value) for key, value in parse_workflow_params(params).items()}
    if verbose:
        _display_execution_banner(node_type, execution_params)

    with reserve_stdout():
        probe = probe_node(node_type, execution_params)

    if verbose and probe.node_type != node_type:
        click.echo(f"📝 Resolved '{node_type}' to '{probe.node_type}'", err=True)
    if verbose and probe.execution_id:
        click.echo(f"💾 Stored execution in cache: {probe.execution_id}", err=True)

    # The same sections MCP's `format_error_text` composes; `-v` adds an error's technical details.
    warnings, advisories = partition_surfaced_diagnostics(probe.warnings)
    sections = diagnostic_sections(warnings, advisories)
    if output_format == "json":
        click.echo(json.dumps(_json_document(probe, execution_params, verbose), indent=2, default=str))
    elif probe.success:
        click.echo(_format_success_text(probe, execution_params, verbose))
        if sections:
            click.echo("\n".join(sections), err=True)
    else:
        errors = errors_block(probe.errors, warnings, verbose=verbose)
        click.echo("\n".join([*errors, *(["", *sections] if sections else [])]), err=True)

    if not probe.success:
        sys.exit(EXIT_CODES[WorkflowStatus.FAILED] if probe.ran else EXIT_REJECTED)


def _display_execution_banner(node_type: str, execution_params: dict[str, Any]) -> None:
    click.echo(f"🔄 Running node '{node_type}'...", err=True)
    if not execution_params:
        return

    from pflow.execution.formatters.node_output_formatter import format_param_value

    click.echo("   Parameters:", err=True)
    for key, value in execution_params.items():
        click.echo(f"     {key}: {format_param_value(value)}", err=True)


def _shared_store_view(probe: ProbeResult, execution_params: dict[str, Any]) -> dict[str, Any]:
    """The flat store `-v` shows: the params given, then what the node wrote."""
    return {**execution_params, **probe.outputs}


def _json_document(probe: ProbeResult, execution_params: dict[str, Any], verbose: bool) -> dict[str, Any]:
    document: dict[str, Any] = {
        "success": probe.success,
        "node_type": probe.node_type,
        "outputs": probe.outputs,
        "shared_store": _shared_store_view(probe, execution_params) if verbose else None,
        "execution_time_ms": probe.execution_time_ms,
        "execution_id": probe.execution_id,
    }
    if not probe.success:
        document["errors"] = [error.to_output_dict() for error in probe.errors]
    if probe.warnings or not probe.success:
        document["warnings"] = [warning.to_output_dict() for warning in probe.warnings]
    return document


def _format_success_text(probe: ProbeResult, execution_params: dict[str, Any], verbose: bool) -> str:
    from pflow.execution.formatters.node_output_formatter import format_structure_output
    from pflow.registry import Registry

    return format_structure_output(
        probe.node_type,
        probe.outputs,
        _shared_store_view(probe, execution_params),
        Registry(),
        probe.execution_time_ms,
        verbose,
        execution_id=probe.execution_id,
        output_mode=_load_registry_output_mode(),
    )


def _load_registry_output_mode() -> str:
    from pflow.core.settings import SettingsManager

    try:
        return SettingsManager().load().registry.output_mode
    except Exception:
        return "smart"
