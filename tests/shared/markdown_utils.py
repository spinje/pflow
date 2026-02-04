"""Test utility for converting IR dicts to .pflow.md markdown format.

This module is test-only infrastructure — NOT production code.
It generates valid .pflow.md content from IR dicts so tests can write
markdown workflow files instead of JSON.

Usage:
    from tests.shared.markdown_utils import ir_to_markdown, write_workflow_file

    markdown = ir_to_markdown(ir_dict, title="My Workflow")
    write_workflow_file(ir_dict, Path("/tmp/test.pflow.md"))
"""

from pathlib import Path
from typing import Any

import yaml


def ir_to_markdown(  # noqa: C901
    ir_dict: dict[str, Any],
    title: str = "Test Workflow",
    description: str | None = None,
) -> str:
    """Generate valid .pflow.md content from an IR dict.

    Args:
        ir_dict: Workflow IR dictionary (same shape as json.load() produces)
        title: H1 heading title for the workflow
        description: Optional workflow description (H1 prose)

    Returns:
        Valid .pflow.md markdown string
    """
    lines: list[str] = []

    # H1 title
    lines.append(f"# {title}")
    lines.append("")

    # Workflow description
    if description:
        lines.append(description)
        lines.append("")

    # Inputs section
    inputs = ir_dict.get("inputs", {})
    if inputs:
        lines.append("## Inputs")
        lines.append("")
        for name, input_def in inputs.items():
            lines.append(f"### {name}")
            lines.append("")
            # Description (required by parser)
            desc = input_def.get("description", "Input parameter.")
            lines.append(desc)
            lines.append("")
            # Params (flat — no params wrapper for inputs)
            for key, value in input_def.items():
                if key == "description":
                    continue
                lines.append(f"- {key}: {_format_inline_value(value)}")
            lines.append("")

    # Steps section
    nodes = ir_dict.get("nodes", [])
    if nodes:
        lines.append("## Steps")
        lines.append("")
        for node in nodes:
            lines.append(f"### {node['id']}")
            lines.append("")
            # Purpose/description
            purpose = node.get("purpose", "Step description.")
            lines.append(purpose)
            lines.append("")
            # Type param (extracted to top-level in IR, but written as param in markdown)
            lines.append(f"- type: {node['type']}")
            # Params
            params = node.get("params", {})
            for key, value in params.items():
                if key == "command":
                    # Shell command → code block
                    lines.append("")
                    lines.append("```shell command")
                    lines.append(str(value))
                    lines.append("```")
                elif key == "prompt":
                    # LLM prompt → code block
                    lines.append("")
                    # Use 4+ backticks if content contains triple backticks
                    fence = "````" if "```" in str(value) else "```"
                    lines.append(f"{fence}markdown prompt")
                    lines.append(str(value))
                    lines.append(fence)
                elif key == "code":
                    # Python code → code block
                    lines.append("")
                    lines.append("```python code")
                    lines.append(str(value))
                    lines.append("```")
                elif key == "stdin" and isinstance(value, (dict, list)):
                    # Complex stdin → yaml code block
                    lines.append("")
                    lines.append("```yaml stdin")
                    lines.append(yaml.dump(value, default_flow_style=False, sort_keys=False).rstrip())
                    lines.append("```")
                elif key == "headers" and isinstance(value, dict):
                    # HTTP headers → yaml code block
                    lines.append("")
                    lines.append("```yaml headers")
                    lines.append(yaml.dump(value, default_flow_style=False, sort_keys=False).rstrip())
                    lines.append("```")
                elif key == "output_schema" and isinstance(value, (dict, list)):
                    # Claude-code output schema → yaml code block
                    lines.append("")
                    lines.append("```yaml output_schema")
                    lines.append(yaml.dump(value, default_flow_style=False, sort_keys=False).rstrip())
                    lines.append("```")
                elif isinstance(value, (dict, list)):
                    # Other complex params → inline YAML flow style
                    lines.append(f"- {key}: {yaml.dump(value, default_flow_style=True).rstrip()}")
                else:
                    lines.append(f"- {key}: {_format_inline_value(value)}")
            # Batch config (top-level on node, not in params)
            batch = node.get("batch")
            if batch:
                lines.append("")
                lines.append("```yaml batch")
                lines.append(yaml.dump(batch, default_flow_style=False, sort_keys=False).rstrip())
                lines.append("```")
            lines.append("")

    # Outputs section
    outputs = ir_dict.get("outputs", {})
    if outputs:
        lines.append("## Outputs")
        lines.append("")
        for name, output_def in outputs.items():
            lines.append(f"### {name}")
            lines.append("")
            desc = output_def.get("description", "Output value.")
            lines.append(desc)
            lines.append("")
            for key, value in output_def.items():
                if key == "description":
                    continue
                if key == "source" and isinstance(value, str) and "\n" in value:
                    # Multi-line source template → code block
                    lines.append("")
                    lines.append("```markdown source")
                    lines.append(value)
                    lines.append("```")
                else:
                    lines.append(f"- {key}: {_format_inline_value(value)}")
            lines.append("")

    return "\n".join(lines)


def write_workflow_file(
    ir_dict: dict[str, Any],
    path: Path,
    title: str = "Test Workflow",
    description: str | None = None,
) -> None:
    """Write an IR dict as a .pflow.md file.

    Args:
        ir_dict: Workflow IR dictionary
        path: File path to write to (should end in .pflow.md)
        title: H1 heading title
        description: Optional workflow description
    """
    content = ir_to_markdown(ir_dict, title=title, description=description)
    path.write_text(content, encoding="utf-8")


def _format_inline_value(value: Any) -> str:
    """Format a value for inline YAML param output.

    Handles booleans (lowercase), strings, numbers.
    Quotes strings that contain YAML-special characters.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        # Check if the string needs quoting for YAML safety
        # Characters that can cause YAML parsing issues: colons followed by space,
        # leading/trailing spaces, YAML special values (true/false/null/yes/no), etc.
        needs_quoting = (
            ": " in value
            or value.startswith(("{", "[", "'", '"', "&", "*", "!", "|", ">", "%", "@"))
            or value.lower() in ("true", "false", "null", "yes", "no", "on", "off", "~")
            or "#" in value
            or "\n" in value
        )
        if needs_quoting:
            # Use double quotes and escape internal quotes
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            # For multiline, replace newlines with literal \n inside quotes
            escaped = escaped.replace("\n", "\\n")
            return f'"{escaped}"'
        return value
    return str(value)
