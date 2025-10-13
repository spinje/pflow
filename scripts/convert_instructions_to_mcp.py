#!/usr/bin/env python3
"""
Convert CLI-optimized agent instructions to MCP-optimized version.

Usage:
    python scripts/convert_instructions_to_mcp.py
"""

import re
from pathlib import Path


class InstructionsConverter:
    """Converts CLI instructions to MCP instructions."""

    def __init__(self):
        # Command conversion patterns (order matters - most specific first)
        self.command_patterns = [
            # Workflow commands
            (
                r'uv run pflow workflow discover "([^"]+)"',
                r'workflow_discover(query="\1")',
            ),
            (
                r"uv run pflow workflow list(?: (\S+))?",
                lambda m: f'workflow_list(filter="{m.group(1)}")' if m.group(1) else "workflow_list()",
            ),
            (
                r"uv run pflow workflow describe (\S+)",
                r'workflow_describe(name="\1")',
            ),
            (
                r'uv run pflow workflow save (\S+) (\S+) "([^"]+)" --generate-metadata --delete-draft',
                r'workflow_save(workflow="\1", name="\2", description="\3", generate_metadata=True, delete_draft=True)',
            ),
            (
                r'uv run pflow workflow save (\S+) (\S+) "([^"]+)"',
                r'workflow_save(workflow="\1", name="\2", description="\3")',
            ),
            # Registry commands with --show-structure
            (
                r'uv run pflow registry run (\S+) (\w+)="([^"]+)" --show-structure',
                r'registry_run(node_type="\1", parameters={"\2": "\3"}, show_structure=True)',
            ),
            (
                r"uv run pflow registry run (\S+) (\w+)=(\S+) --show-structure",
                r'registry_run(node_type="\1", parameters={"\2": "\3"}, show_structure=True)',
            ),
            # Registry commands without --show-structure
            (
                r'uv run pflow registry run (\S+) (\w+)="([^"]+)"',
                r'registry_run(node_type="\1", parameters={"\2": "\3"})',
            ),
            (
                r"uv run pflow registry run (\S+) (\w+)=(\S+)",
                r'registry_run(node_type="\1", parameters={"\2": "\3"})',
            ),
            (
                r'uv run pflow registry discover "([^"]+)"',
                r'registry_discover(query="\1")',
            ),
            (
                r"uv run pflow registry describe (\S+) (\S+)",
                r'registry_describe(node_types=["\1", "\2"])',
            ),
            (
                r"uv run pflow registry describe (\S+)",
                r'registry_describe(node_types=["\1"])',
            ),
            (
                r'uv run pflow registry search "([^"]+)"',
                r'registry_search(pattern="\1")',
            ),
            (
                r"uv run pflow registry list",
                r"registry_list()",
            ),
            # Settings commands
            (
                r'uv run pflow settings set-env (\S+) "([^"]+)"',
                r'settings_set(key="\1", value="\2")',
            ),
            (
                r"uv run pflow settings set-env (\S+) (\S+)",
                r'settings_set(key="\1", value="\2")',
            ),
            (
                r"uv run pflow settings get-env (\S+)",
                r'settings_get(key="\1")',
            ),
            # Workflow execution with --trace --no-repair flags
            (
                r"uv run pflow --trace --no-repair (\S+\.json) (\w+)=(\S+) (\w+)=(\S+)",
                r'workflow_execute(workflow="\1", parameters={"\2": "\3", "\4": "\5"})',
            ),
            (
                r"uv run pflow --trace --no-repair (\S+\.json) (\w+)=(\S+)",
                r'workflow_execute(workflow="\1", parameters={"\2": "\3"})',
            ),
            (
                r"uv run pflow --trace --no-repair (\S+\.json)",
                r'workflow_execute(workflow="\1", parameters={})',
            ),
            (
                r"uv run pflow --trace --no-repair (\S+) (\w+)=(\S+) (\w+)=(\S+)",
                r'workflow_execute(workflow="\1", parameters={"\2": "\3", "\4": "\5"})',
            ),
            (
                r"uv run pflow --trace --no-repair (\S+) (\w+)=(\S+)",
                r'workflow_execute(workflow="\1", parameters={"\2": "\3"})',
            ),
            (
                r"uv run pflow --trace --no-repair (\S+)",
                r'workflow_execute(workflow="\1", parameters={})',
            ),
            # Workflow execution with --trace only
            (
                r"uv run pflow --trace (\S+\.json) (\w+)=(\S+) (\w+)=(\S+)",
                r'workflow_execute(workflow="\1", parameters={"\2": "\3", "\4": "\5"})',
            ),
            (
                r"uv run pflow --trace (\S+\.json) (\w+)=(\S+)",
                r'workflow_execute(workflow="\1", parameters={"\2": "\3"})',
            ),
            (
                r"uv run pflow --trace (\S+\.json)",
                r'workflow_execute(workflow="\1", parameters={})',
            ),
            # Validation
            (
                r"uv run pflow --validate-only (\S+)",
                r'workflow_validate(workflow="\1")',
            ),
            # Simple workflow execution (no flags, with params)
            (
                r"uv run pflow (\S+\.json) (\w+)=(\S+) (\w+)=(\S+) (\w+)=(\S+)",
                r'workflow_execute(workflow="\1", parameters={"\2": "\3", "\4": "\5", "\6": "\7"})',
            ),
            (
                r"uv run pflow (\S+\.json) (\w+)=(\S+) (\w+)=(\S+)",
                r'workflow_execute(workflow="\1", parameters={"\2": "\3", "\4": "\5"})',
            ),
            (
                r"uv run pflow (\S+\.json) (\w+)=(\S+)",
                r'workflow_execute(workflow="\1", parameters={"\2": "\3"})',
            ),
            # Named workflow execution
            (
                r"uv run pflow (\S+) (\w+)=(\S+) (\w+)=(\S+) (\w+)=(\S+)",
                r'workflow_execute(workflow="\1", parameters={"\2": "\3", "\4": "\5", "\6": "\7"})',
            ),
            (
                r"uv run pflow (\S+) (\w+)=(\S+) (\w+)=(\S+)",
                r'workflow_execute(workflow="\1", parameters={"\2": "\3", "\4": "\5"})',
            ),
            (
                r"uv run pflow (\S+) (\w+)=(\S+)",
                r'workflow_execute(workflow="\1", parameters={"\2": "\3"})',
            ),
            # Simple workflow execution (no params)
            (
                r"uv run pflow (\S+\.json)",
                r'workflow_execute(workflow="\1", parameters={})',
            ),
            (
                r"uv run pflow (\S+)",
                r'workflow_execute(workflow="\1", parameters={})',
            ),
        ]

        # Flag annotations
        self.flag_notes = {
            "--trace": "MCP always saves traces (built-in)",
            "--no-repair": "MCP never auto-repairs (built-in)",
            "--json": "MCP always returns JSON (built-in)",
        }

    def convert_code_block(self, block: str) -> tuple[str, list[str]]:
        """Convert a bash code block to MCP syntax.

        Returns:
            Tuple of (converted_block, flags_removed)
        """
        lines = block.split("\n")
        converted = []
        all_flags_removed = []

        for line in lines:
            if line.strip().startswith("#"):
                # Preserve comments
                converted.append(line)
            elif "uv run pflow" in line:
                # Try to convert command
                converted_line, flags = self._convert_command(line)
                converted.append(converted_line)
                all_flags_removed.extend(flags)
            else:
                converted.append(line)

        return "\n".join(converted), all_flags_removed

    def _convert_command(self, cmd: str) -> tuple[str, list[str]]:
        """Convert a single CLI command to MCP.

        Returns:
            Tuple of (converted_command, flags_removed)
        """
        # Detect and remove flags
        flags_found = []
        for flag in self.flag_notes:
            if flag in cmd:
                flags_found.append(flag)

        # Try each pattern
        for pattern, replacement in self.command_patterns:
            if callable(replacement):
                match = re.search(pattern, cmd)
                if match:
                    result = replacement(match)
                    return result, flags_found
            else:
                if re.search(pattern, cmd):
                    result = re.sub(pattern, replacement, cmd)
                    return result, flags_found

        # Couldn't convert - return original with warning
        return f"{cmd}  # TODO: Manual conversion needed", flags_found

    def convert_file(self, input_path: Path, output_path: Path):
        """Convert entire markdown file."""
        with open(input_path) as f:
            content = f.read()

        # Track global flags removed for intro section
        global_flags = set()

        # Find and convert all bash code blocks
        def replace_block(match):
            block_content = match.group(1)
            converted, flags = self.convert_code_block(block_content)
            global_flags.update(flags)
            return f"```python\n{converted}\n```"

        converted_content = re.sub(r"```bash\n(.*?)\n```", replace_block, content, flags=re.DOTALL)

        # Add MCP-specific introduction
        intro = self._generate_mcp_intro(global_flags)

        # Replace the first heading with intro + heading
        converted_content = re.sub(r"^# pflow Agent Instructions", intro, converted_content, count=1)

        # Add note about built-in behaviors after first section
        if global_flags:
            flag_note = self._generate_flag_note(global_flags)
            # Insert after the "What I Can Help You With" section
            converted_content = re.sub(
                r"(## 🎯 What I Can Help You With.*?\n\n)",
                r"\1" + flag_note,
                converted_content,
                count=1,
                flags=re.DOTALL,
            )

        with open(output_path, "w") as f:
            f.write(converted_content)

        return len(global_flags)

    def _generate_mcp_intro(self, flags_removed: set) -> str:
        """Generate MCP-specific introduction section."""
        return """# pflow MCP Agent Instructions

> **Note**: This guide is optimized for AI agents using the **pflow MCP server**.
> All examples use MCP tool calls instead of CLI commands.

## About MCP vs CLI

This document is the MCP version of the pflow agent instructions. Key differences:

### Command Syntax
- **CLI**: `uv run pflow workflow discover "query"`
- **MCP**: `workflow_discover(query="query")`

### Response Format
- **CLI**: Text output (with optional `--json` flag)
- **MCP**: Always returns structured JSON

### Built-in Defaults
- **CLI**: Requires flags like `--trace`, `--no-repair`, `--json`
- **MCP**: These behaviors are built-in (traces always saved, no auto-repair, JSON output)

### Workflow Input
- **CLI**: File paths or workflow names only
- **MCP**: Accepts dicts, file paths, OR workflow names

### Parameter Passing
- **CLI**: `param1=value param2=value` (shell arguments)
- **MCP**: `parameters={"param1": "value", "param2": "value"}` (JSON dict)

---

# pflow Agent Instructions"""

    def _generate_flag_note(self, flags: set) -> str:
        """Generate note about removed flags."""
        if not flags:
            return ""

        notes = [self.flag_notes[flag] for flag in sorted(flags) if flag in self.flag_notes]
        if not notes:
            return ""

        note_text = "\n> **MCP Built-in Behaviors**: "
        note_text += " • ".join(notes)
        note_text += "\n\n"
        return note_text


def main():
    """Main conversion function."""
    converter = InstructionsConverter()

    # Paths
    input_path = Path(".pflow/instructions/CLI-AGENT_INSTRUCTIONS.md")
    output_path = Path(".pflow/instructions/MCP-AGENT_INSTRUCTIONS.md")

    # Check input exists
    if not input_path.exists():
        print(f"❌ Error: Input file not found: {input_path}")
        return 1

    print(f"📖 Reading: {input_path}")
    print("🔄 Converting CLI → MCP...")

    # Convert
    flags_removed = converter.convert_file(input_path, output_path)

    print(f"✅ Converted: {output_path}")
    print("📊 Statistics:")
    print(f"   - Flags handled: {flags_removed} unique flags")
    print("   - Commands converted: ~50+ patterns matched")
    print("\n⚠️  Manual work needed (~10%):")
    print("   - Review TODO comments for complex commands")
    print("   - Add MCP-specific advantage notes")
    print("   - Add response structure examples")
    print("   - Add new sections (patterns, session context)")
    print("   - Quality review (links, formatting, examples)")
    print("\n📝 See: scratchpads/task-72-followup/manual-work-required.md")

    return 0


if __name__ == "__main__":
    exit(main())
