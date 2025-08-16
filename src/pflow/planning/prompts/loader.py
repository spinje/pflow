"""Simple prompt loader for markdown files."""

import re
from pathlib import Path
from typing import Any


def load_prompt(prompt_name: str) -> str:
    """Load a prompt from a markdown file.

    Args:
        prompt_name: Name of the prompt file (without .md extension)

    Returns:
        The prompt text with {{variable}} placeholders

    Raises:
        FileNotFoundError: If the prompt file doesn't exist
    """
    prompt_dir = Path(__file__).parent
    prompt_file = prompt_dir / f"{prompt_name}.md"

    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

    # Read the entire file
    content = prompt_file.read_text()

    # Skip YAML frontmatter if present
    if content.startswith("---\n"):
        # Find the closing --- and skip everything before it
        parts = content.split("\n---\n", 1)
        if len(parts) == 2:
            # Take everything after the frontmatter
            content = parts[1]

    # Skip the header line if it starts with #
    lines = content.split("\n")
    if lines and lines[0].startswith("#"):
        # Skip the first line (header) and any blank lines after it
        content = "\n".join(lines[1:]).strip()

    return content


def extract_variables(prompt_template: str) -> set[str]:
    """Extract all variable names from a prompt template.

    Args:
        prompt_template: Prompt with {{variable}} placeholders

    Returns:
        Set of variable names found in the template
    """
    return set(re.findall(r"\{\{(\w+)\}\}", prompt_template))


def format_prompt(prompt_template: str, variables: dict[str, Any]) -> str:
    """Format a prompt template with variables.

    This function enforces a strict contract:
    - All variables provided must exist in the template
    - All variables in the template must be provided

    Args:
        prompt_template: Prompt with {{variable}} placeholders
        variables: Dictionary of variable values

    Returns:
        Formatted prompt with variables replaced

    Raises:
        ValueError: If provided variables don't exist in the template
        KeyError: If template variables are missing from provided values
    """
    # Extract variables from template
    template_variables = extract_variables(prompt_template)
    provided_variables = set(variables.keys())

    # Check for unused provided variables (likely a bug in the template or code)
    unused_variables = provided_variables - template_variables
    if unused_variables:
        raise ValueError(
            f"Variables provided but not in template: {sorted(unused_variables)}. "
            f"Template expects: {sorted(template_variables)}"
        )

    # Check for missing required variables
    missing_variables = template_variables - provided_variables
    if missing_variables:
        raise KeyError(f"Missing required variables: {sorted(missing_variables)}")

    # Simple replacement of {{variable}} with values
    formatted = prompt_template
    for var_name, var_value in variables.items():
        placeholder = f"{{{{{var_name}}}}}"
        formatted = formatted.replace(placeholder, str(var_value))

    return formatted
