"""Instructions command group for AI agents.

Provides on-demand instructions for using pflow CLI directly, enabling agents
to learn how to use pflow without pre-configured knowledge.

Commands:
    pflow instructions usage  - Basic usage guide (~500 lines)
    pflow instructions create - Comprehensive workflow creation guide (~1800 lines)
"""

from pathlib import Path

import click


@click.group(name="instructions")
def instructions() -> None:
    """Get instructions for using pflow as an AI agent.

    These commands return comprehensive instructions optimized for LLM consumption,
    enabling AI agents to learn how to use pflow on-demand.

    Examples:
        pflow instructions usage   # Get basic usage guide
        pflow instructions create  # Get comprehensive creation guide
    """
    pass


@instructions.command(name="usage")
def usage_instructions() -> None:
    """Display basic pflow usage instructions for AI agents.

    Returns a ~500 line guide covering:
    - What pflow is and core concepts
    - Essential commands (discovery, execution, management)
    - Quick workflow structure overview
    - When to request comprehensive instructions
    - Common patterns and best practices

    This should be the first instruction set agents read to understand pflow basics.
    For detailed workflow creation, use 'pflow instructions create'.

    Examples:
        pflow instructions usage
    """
    instructions_path = Path(__file__).parent / "resources" / "cli-basic-usage.md"

    if not instructions_path.exists():
        click.echo(
            "Error: Basic usage instructions not found. This may indicate a corrupted installation.",
            err=True,
        )
        raise click.Abort()

    content = instructions_path.read_text(encoding="utf-8")
    click.echo(content)


@instructions.command(name="create")
def create_instructions() -> None:
    """Display comprehensive workflow creation instructions for AI agents.

    Returns a ~1800 line comprehensive guide covering:
    - Complete IR schema reference
    - All available node types and interfaces
    - Template variable system in depth
    - Data flow patterns and examples
    - Error handling strategies
    - Testing and validation approaches
    - Real-world workflow examples
    - Best practices for workflow design

    Use this when you need to build new workflows from scratch.
    For basic usage, use 'pflow instructions usage' instead.

    Examples:
        pflow instructions create
    """
    instructions_path = Path(__file__).parent / "resources" / "cli-agent-instructions.md"

    if not instructions_path.exists():
        click.echo(
            "Error: Comprehensive instructions not found. This may indicate a corrupted installation.",
            err=True,
        )
        raise click.Abort()

    content = instructions_path.read_text(encoding="utf-8")
    click.echo(content)
