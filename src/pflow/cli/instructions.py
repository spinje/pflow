"""Instructions command group for AI agents.

Provides on-demand instructions for using pflow CLI directly, enabling agents
to learn how to use pflow without pre-configured knowledge.

Commands:
    pflow instructions usage  - Basic usage guide (~166 lines)
    pflow instructions create - Comprehensive workflow creation guide (~1650 lines)
                               Use --part 1/2/3 for smaller chunks (~550 lines each)
"""

import re
from pathlib import Path

import click

# Part metadata for table of contents
PART_INFO = {
    1: {
        "title": "Foundation & Mental Model",
        "description": "Core concepts, edges vs templates, workflow limitations, node selection, development steps 1-8",
    },
    2: {
        "title": "Building Workflows",
        "description": "Input declaration, node creation patterns, validation, testing, saving workflows, technical reference",
    },
    3: {
        "title": "Testing & Reference",
        "description": "Testing, debugging, workflow patterns, troubleshooting, quick reference cheat sheets",
    },
}


def _parse_parts(content: str) -> dict[int, str]:
    """Parse content into parts based on markers.

    Returns dict mapping part number to content.
    """
    # Pattern to match part markers: <!-- PART N START: ... -->
    pattern = r"<!-- PART (\d+) START:[^>]*-->"

    # Find all part markers with their positions
    markers = list(re.finditer(pattern, content))

    if not markers:
        # No markers found, return entire content as part 1
        return {1: content}

    parts: dict[int, str] = {}

    for i, marker in enumerate(markers):
        part_num = int(marker.group(1))
        start_pos = marker.start()

        # End position is either next marker or end of file
        end_pos = markers[i + 1].start() if i + 1 < len(markers) else len(content)

        # Extract content, skip the marker comment lines
        part_content = content[start_pos:end_pos]
        # Remove the marker lines (first two lines)
        lines = part_content.split("\n")
        # Skip marker comment lines (lines starting with <!--)
        clean_lines = [ln for ln in lines if not ln.strip().startswith("<!-- PART")]
        # Also skip the "Covers:" comment line
        clean_lines = [ln for ln in clean_lines if not ln.strip().startswith("<!-- Covers:")]
        parts[part_num] = "\n".join(clean_lines).strip()

    return parts


def _strip_part_markers(content: str) -> str:
    """Remove part marker comments from content for cleaner output."""
    lines = content.split("\n")
    clean_lines = [
        ln for ln in lines if not ln.strip().startswith("<!-- PART") and not ln.strip().startswith("<!-- Covers:")
    ]
    return "\n".join(clean_lines)


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
@click.option(
    "--part",
    type=click.IntRange(1, 3),
    default=None,
    help="Show specific part (1-3). Without this flag, shows table of contents.",
)
def create_instructions(part: int | None) -> None:
    """Display comprehensive workflow creation instructions for AI agents.

    The guide is split into 3 parts (~550 lines each) to avoid output truncation:

    \b
    Part 1: Foundation & Mental Model
            Core concepts, edges vs templates, workflow limitations,
            node selection, development steps 1-8

    \b
    Part 2: Building Workflows
            Input declaration, node creation patterns, validation,
            testing, saving workflows, technical reference

    \b
    Part 3: Testing & Reference
            Testing, debugging, workflow patterns, troubleshooting,
            quick reference cheat sheets

    Use --part N to read a specific section. Without --part, shows table of contents.

    Examples:
        pflow instructions create           # Show table of contents
        pflow instructions create --part 1  # Show Part 1 (~550 lines)
        pflow instructions create --part 2  # Show Part 2 (~550 lines)
        pflow instructions create --part 3  # Show Part 3 (~550 lines)
    """
    instructions_path = Path(__file__).parent / "resources" / "cli-agent-instructions.md"

    if not instructions_path.exists():
        click.echo(
            "Error: Comprehensive instructions not found. This may indicate a corrupted installation.",
            err=True,
        )
        raise click.Abort()

    content = instructions_path.read_text(encoding="utf-8")

    if part is None:
        # Show full content (strip marker comments for cleaner output)
        clean_content = _strip_part_markers(content)
        click.echo(clean_content)
        return

    # Parse and show specific part
    parts = _parse_parts(content)

    if part not in parts:
        click.echo(f"Error: Part {part} not found in instructions file.", err=True)
        raise click.Abort()

    # Add header indicating which part this is
    part_info = PART_INFO.get(part, {})
    header = f"# Part {part}: {part_info.get('title', 'Unknown')}\n\n"
    click.echo(header + parts[part])
