"""Instruction resources for AI agents building pflow workflows.

This module exposes agent instructions as MCP resources that agents can
read to learn best practices, patterns, and the workflow building process.

Two variants are provided:
- Regular agents: Full system access (settings, traces, library)
- Sandbox agents: Isolated environments (no settings/trace access)
"""

import logging
from pathlib import Path

from ..server import mcp

logger = logging.getLogger(__name__)


# Paths to agent instructions
def _get_instructions_path(filename: str) -> Path:
    """Get path to instructions file, checking multiple locations.

    Args:
        filename: Name of the instruction file (e.g., "MCP-AGENT_INSTRUCTIONS.md")

    Returns:
        Path to the instruction file (may not exist)
    """
    # Try project root first (development mode)
    # From: src/pflow/mcp_server/resources/instruction_resources.py
    # To:   .pflow/instructions/{filename}
    # Need to go up 5 levels: resources/ -> mcp_server/ -> pflow/ -> src/ -> project_root/
    project_root = Path(__file__).parent.parent.parent.parent.parent
    dev_path = project_root / ".pflow" / "instructions" / filename
    if dev_path.exists():
        return dev_path

    # Fall back to user home (for custom instructions)
    user_path = Path.home() / ".pflow" / "instructions" / filename
    if user_path.exists():
        return user_path

    # Return dev path as default (will trigger fallback message if missing)
    return dev_path


MCP_AGENT_INSTRUCTIONS_PATH = _get_instructions_path("MCP-AGENT_INSTRUCTIONS.md")
SANDBOX_AGENT_INSTRUCTIONS_PATH = _get_instructions_path("MCP-SANDBOX-AGENT_INSTRUCTIONS.md")


@mcp.resource(
    "pflow://instructions",
    name="Agent Instructions",
    title="Complete Workflow Building Guide (READ FIRST)",
    description="""Complete agent instructions for building pflow workflows (shares user's system access with the user).

    ⚠️ IMPORTANT: Read this resource before building new workflows!

    This version is for agents with FULL system access:
    - ✅ Can read/write ~/.pflow/settings.json
    - ✅ Can access trace files in ~/.pflow/debug/
    - ✅ Have pflow cli installed and configured in their environment (check with `pflow --version`)

    This is a comprehensive guide covering:
    - The 10-step development loop (discover → design → build → test → save)
    - When to discover vs build new workflows (always discover first!)
    - Critical patterns (use shell/jq for structured data extraction)
    - Workflow structure and constraints (sequential execution only)
    - Template syntax and variables (${input}, ${node.output})
    - Authentication and credential management
    - Common patterns and complete examples
    - Troubleshooting and debugging techniques
    - What workflows CANNOT do (no conditionals, loops, or state)

    The instructions are organized into sections:
    1. Quick Start & Decision Trees - Read first
    2. The Agent Development Loop - 10 steps to follow
    3. Building Workflows - Technical reference
    4. Common Patterns - Real examples
    5. Troubleshooting - Debug errors
    6. Testing & Debugging - Validate and fix

    Note: You do NOT need to read this before using workflow_discover or workflow_execute
    if a workflow matches the user's request perfectly. This resource is only for when
    you need to BUILD a new workflow.

    For sandboxed/isolated environments (no pflow cli installed), use pflow://instructions/sandbox instead.
    """,
)
def get_instructions() -> str:
    """Complete agent instructions for building pflow workflows (full system access).

    This version is for agents with FULL system access to the user's system:
    - Can read/write ~/.pflow/settings.json
    - Can access trace files in ~/.pflow/debug/
    - Have pflow CLI installed and configured

    For sandboxed/isolated environments, use pflow://instructions/sandbox instead.
    """
    try:
        if not MCP_AGENT_INSTRUCTIONS_PATH.exists():
            logger.warning(f"Instructions file not found at {MCP_AGENT_INSTRUCTIONS_PATH}")
            return _regular_fallback_message()

        content = MCP_AGENT_INSTRUCTIONS_PATH.read_text(encoding="utf-8")
        logger.debug(f"Successfully loaded instructions ({len(content)} bytes)")
        return content

    except Exception as e:
        logger.error(f"Failed to read instructions from {MCP_AGENT_INSTRUCTIONS_PATH}: {e}", exc_info=True)
        return _regular_fallback_message()


@mcp.resource(
    "pflow://instructions/sandbox",
    name="Sandbox Agent Instructions",
    title="Workflow Building Guide for Isolated Environments",
    description="""Agent instructions for sandboxed/isolated environments (restricted access).

    ⚠️ Use this version for SANDBOXED agents with restricted system access:
    - ❌ NO access to trace files in ~/.pflow/debug/
    - ❌ Dont have pflow cli installed and configured in their environment (check with `pflow --version` if you are unsure)

    Key differences for sandboxed environments:
    - Have to use send workflow IR object instead of file path when using workflow_validate, workflow_execute, workflow_save tools
    - No trace debugging (rely on workflow error outputs only)
    - Work entirely within sandbox constraints

    This guide covers the same workflow building process as regular instructions,
    but adapted for isolated environments where system access is restricted.

    Use cases:
    - Containerized agents
    - Web-based AI assistants like Claude Desktop, ChatGPT Desktop etc.
    - Any environment without shared access to the users system

    For agents with user's system access, use pflow://instructions instead.
    """,
)
def get_sandbox_instructions() -> str:
    """Agent instructions for sandboxed/isolated environments (restricted access).

    Use this version for SANDBOXED agents with restricted system access:
    - NO access to ~/.pflow/settings.json (can't read/write API keys)
    - NO access to trace files in ~/.pflow/debug/
    - Don't have pflow CLI installed in their environment
    - Must send workflow IR objects instead of file paths

    Use cases: containerized agents, web-based AI assistants, CI/CD environments,
    multi-tenant systems, or any environment without shared access to the user's system.

    For agents with full system access, use pflow://instructions instead.
    """
    try:
        if not SANDBOX_AGENT_INSTRUCTIONS_PATH.exists():
            logger.warning(f"Sandbox instructions file not found at {SANDBOX_AGENT_INSTRUCTIONS_PATH}")
            return _sandbox_fallback_message()

        content = SANDBOX_AGENT_INSTRUCTIONS_PATH.read_text(encoding="utf-8")
        logger.debug(f"Successfully loaded sandbox instructions ({len(content)} bytes)")
        return content

    except Exception as e:
        logger.error(f"Failed to read sandbox instructions from {SANDBOX_AGENT_INSTRUCTIONS_PATH}: {e}", exc_info=True)
        return _sandbox_fallback_message()


def _regular_fallback_message() -> str:
    """Fallback message for regular agents when instructions unavailable.

    Provides full CLI command reference including settings and trace access.
    """
    return """# Agent Instructions Not Available

The instruction file could not be loaded from `~/.pflow/instructions/MCP-AGENT_INSTRUCTIONS.md`.

## Alternative Resources

Use these CLI tools to discover what you need:

### Discovery Commands (Use These First!)
- `pflow workflow discover "your task description"` - Find existing workflows
- `pflow registry discover "what you need to build"` - Find nodes with LLM selection

### Manual Discovery Commands
- `pflow workflow list` - Browse all saved workflows
- `pflow registry describe node1 node2` - Get specific node specs
- `pflow registry search pattern` - Search for nodes by pattern

### Execution & Management
- `pflow workflow.json param=value` - Run a workflow
- `pflow --validate-only workflow.json` - Validate before running
- `pflow --trace workflow.json` - Run with trace output
- `pflow workflow save file name "description"` - Save to library

### Settings & Configuration
- `pflow settings set-env KEY value` - Store API keys securely
- `pflow settings get-env KEY` - Retrieve stored values
- `pflow settings show` - Show all settings

### Help & Documentation
- `pflow --help` - See all available commands
- `pflow registry --help` - Registry command help
- `pflow workflow --help` - Workflow command help

## Key Principles (Quick Reference)

1. **Always discover first**: Run `workflow discover` before building new
2. **Use shell/jq for data**: Never use LLM for structured data extraction
3. **Sequential only**: Workflows are linear chains, no branches or loops
4. **Test MCP nodes**: Always test with real data before building
5. **Templates**: Use `${input}` for workflow inputs, `${node.output}` for node outputs
6. **Store credentials**: Use `pflow settings set-env` for API keys

## Manual Setup

If the file is missing:
1. Check if `~/.pflow/instructions/` directory exists
2. Reinstall pflow: `pip install --upgrade pflow`
3. File an issue if problem persists: https://github.com/anthropics/pflow/issues

## Troubleshooting

If you're seeing this message but the file should exist:
- Verify path: `ls -la ~/.pflow/instructions/MCP-AGENT_INSTRUCTIONS.md`
- Check permissions: File should be readable
- Check pflow installation: `pflow --version`
"""


def _sandbox_fallback_message() -> str:
    """Fallback message for sandbox agents when instructions unavailable.

    Excludes settings commands and trace access - focuses on self-contained workflows.
    """
    return """# Sandbox Agent Instructions Not Available

The instruction file could not be loaded from `~/.pflow/instructions/MCP-SANDBOX-AGENT_INSTRUCTIONS.md`.

## Key Principles for Sandboxed Environments

1. **Avoid passing credentials as workflow inputs**:
   - NO `~/.pflow/settings.json access`, ask user to set environment variables instead by using the `pflow settings set-env` cli command or other means

2. **Send workflow IR object instead of file path**
   - This is applicable for workflow_validate, workflow_execute, workflow_save tools
   - Don't assume shared access to the user's system where pflow is installed

3. **No trace debugging**: Use workflow outputs for debugging
   - Add explicit output nodes to capture intermediate data
   - Return useful error messages in workflow outputs

4. **Sequential execution only**: No conditionals, loops, or state
   - Workflows are linear chains of nodes
   - Each node executes once in order

## Example: Credentials as Workflow Inputs and saving to file

```json
{
  "inputs": {
    "api_token": {
      "type": "string",
      "required": true,
      "description": "API authentication token"
    },
    "api_url": {
      "type": "string",
      "required": true,
      "description": "API URL to fetch data from"
    }
  },
  "nodes": [
    {
      "id": "call-api",
      "type": "http",
      "purpose": "call API",
      "params": {
        "url": "${api_url}",
        "method": "GET",
        "auth_token": "${api_token}"
      }
    },
    {
      "id": "save-to-file",
      "type": "write-file",
      "params": {
        "file_path": "${output_file}",
        "content": "${call-api.response.data}"
      }
    },
  ],
  "edges": [
    {"from": "call-api", "to": "save-to-file"}
  ],
  "outputs": {
    "result-file-path": {
      "source": "${save-to-file.file-path}",
      "description": "Path to file where API response data was saved"
    }
  }
}
```

**Run with**:
```bash
# Avoid this
pflow workflow.json api_token=YOUR_KEY_HERE api_url=https://api.example.com/data

# If credentials are set as environment variables, use this (no api_token input required)
pflow workflow.json api_url=https://api.example.com/data
```



## Troubleshooting

In sandboxed environments:
- Settings.json is NOT accessible (by design)
- Trace files are NOT accessible (by design)
- Workflow library may be isolated or restricted
- Focus on creating self-contained workflows
"""
