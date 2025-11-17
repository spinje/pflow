"""Implementation of read-fields command for selective field retrieval."""

import sys
from typing import Any

import click

from pflow.core.execution_cache import ExecutionCache
from pflow.runtime.template_resolver import TemplateResolver


@click.command(name="read-fields")
@click.argument("execution_id", type=str)
@click.argument("field_paths", nargs=-1, required=True)
@click.option(
    "--output-format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format (text or json)",
)
def read_fields(execution_id: str, field_paths: tuple[str, ...], output_format: str) -> None:
    """Read specific fields from cached registry run execution.

    This command retrieves specific field values from a previous registry run
    execution, enabling efficient data access without re-executing the node.

    \b
    Arguments:
        EXECUTION_ID: The execution ID from a previous registry run command
        FIELD_PATHS: One or more field paths to retrieve (e.g., result[0].title)

    \b
    Examples:
        # Single field
        pflow read-fields exec-1705234567-a1b2 result[0].title

        # Multiple fields
        pflow read-fields exec-1705234567-a1b2 result[0].title result[0].id result[0].state

        # JSON output
        pflow read-fields exec-1705234567-a1b2 result --output-format json
    """
    try:
        # Load cached execution
        cache = ExecutionCache()
        cache_data = cache.retrieve(execution_id)

        if cache_data is None:
            click.echo(f"❌ Execution '{execution_id}' not found in cache", err=True)
            click.echo("", err=True)
            click.echo("Run 'pflow registry run <node-type>' to execute a node and cache results.", err=True)
            sys.exit(1)

        # Extract field values using TemplateResolver
        outputs = cache_data["outputs"]
        field_values: dict[str, Any] = {}

        for field_path in field_paths:
            try:
                # Use TemplateResolver for consistent path parsing
                value = TemplateResolver.resolve_value(field_path, outputs)
                field_values[field_path] = value
            except Exception:
                # Invalid path or not found - store None
                field_values[field_path] = None

        # Format and display results
        from pflow.execution.formatters.field_output_formatter import format_field_output

        result = format_field_output(field_values, format_type=output_format)

        if output_format == "json":
            import json

            click.echo(json.dumps(result, indent=2, default=str))
        else:
            click.echo(result)

    except Exception as e:
        click.echo(f"❌ Error reading fields: {e}", err=True)
        sys.exit(1)
