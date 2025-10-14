# CLI to MCP Instructions Converter - Analysis & Specification

## Executive Summary

**Yes, programmatic conversion is very feasible!** The patterns are regular and predictable. This document analyzes what needs to change and proposes a conversion strategy.

## Key Differences: CLI vs MCP

### 1. Command Syntax Mapping

| CLI Command | MCP Tool Call | Notes |
|-------------|---------------|-------|
| `uv run pflow workflow discover "query"` | `workflow_discover(query="query")` | Returns structured JSON |
| `uv run pflow registry discover "query"` | `registry_discover(query="query")` | Returns complete specs |
| `uv run pflow registry run node param=value` | `registry_run(node_type="node", parameters={"param": "value"})` | Built-in structure display |
| `uv run pflow workflow.json param=value` | `workflow_execute(workflow="workflow.json", parameters={"param": "value"})` | Can pass dict, name, or path |
| `uv run pflow --validate-only workflow.json` | `workflow_validate(workflow="workflow.json")` | No side effects |
| `uv run pflow workflow save file.json name "desc"` | `workflow_save(workflow="file.json", name="name", description="desc")` | Auto-normalizes |
| `uv run pflow workflow list [filter]` | `workflow_list(filter="filter")` | Optional filter |
| `uv run pflow workflow describe name` | `workflow_describe(name="name")` | Shows interface |
| `uv run pflow settings set-env KEY value` | `settings_set(key="KEY", value="value")` | Secure storage |
| `uv run pflow settings get-env KEY` | `settings_get(key="KEY")` | Retrieve values |
| `uv run pflow registry describe node1 node2` | `registry_describe(node_types=["node1", "node2"])` | Array parameter |
| `uv run pflow registry search "pattern"` | `registry_search(pattern="pattern")` | Fuzzy matching |
| `uv run pflow registry list` | `registry_list()` | All nodes |

### 2. Flag Handling Differences

**CLI Flags** → **MCP Built-in Behavior**

| CLI Flag | MCP Equivalent | Explanation |
|----------|----------------|-------------|
| `--trace` | Always enabled | MCP always saves traces to `~/.pflow/debug/` |
| `--no-repair` | Always disabled | MCP never auto-repairs (explicit errors only) |
| `--json` | Always enabled | MCP always returns structured JSON |
| `--show-structure` | Optional parameter | `registry_run(..., show_structure=true)` |
| `--validate-only` | Separate tool | Use `workflow_validate()` instead |
| `--generate-metadata` | Optional parameter | `workflow_save(..., generate_metadata=true)` |
| `--delete-draft` | Optional parameter | `workflow_save(..., delete_draft=true)` |

### 3. Parameter Passing Differences

**CLI (positional and key=value)**:
```bash
uv run pflow workflow.json channel=C123 limit=10
```

**MCP (structured JSON)**:
```json
workflow_execute(
  workflow="workflow.json",
  parameters={
    "channel": "C123",
    "limit": 10
  }
)
```

### 4. File/Workflow Reference Differences

**CLI**: Always needs file path or workflow name
```bash
uv run pflow my-workflow param=value
uv run pflow ./path/to/workflow.json param=value
```

**MCP**: Flexible - supports dict, name, or path
```json
// By name
workflow_execute(workflow="my-workflow", parameters={...})

// By file path
workflow_execute(workflow="./path/to/workflow.json", parameters={...})

// By dict (inline IR)
workflow_execute(
  workflow={
    "nodes": [...],
    "edges": [...]
  },
  parameters={...}
)
```

### 5. Output Format Differences

**CLI**: Text-based output (with optional --json)
```
✓ Schema validation passed
✓ Data flow validation passed
```

**MCP**: Always JSON
```json
{
  "valid": true,
  "message": "✓ Schema validation passed\n✓ Data flow validation passed",
  "checks_passed": 4
}
```

## Content Changes Required

### Section-by-Section Analysis

#### Sections Needing Major Changes

1. **Command examples** (throughout)
   - Replace all bash code blocks with MCP tool call syntax
   - Example count: ~50+ command examples

2. **Flag references** (multiple sections)
   - Remove `--trace`, `--no-repair`, `--json` mentions
   - Add note about MCP defaults
   - Locations: Testing, Debugging, Execution sections

3. **"Quick Start Decision Tree"** (line 47-64)
   - Update command syntax examples

4. **"The Agent Development Loop"** (line 145-710)
   - All discovery/execution commands need updating
   - Step 2: DISCOVER WORKFLOWS
   - Step 3: DISCOVER NODES
   - Step 3.2: TEST MCP/HTTP NODES
   - Step 7: VALIDATE
   - Step 8: TEST
   - Step 10: SAVE

5. **"Testing & Debugging"** (line 1182-1314)
   - Update all command examples
   - Explain MCP always includes structure info

6. **"Command Cheat Sheet"** (line 2004-2024)
   - Complete rewrite to MCP tool calls

7. **"Complete Example"** (line 2035-2180)
   - Update all command executions

#### Sections Needing Minor Changes

1. **Conceptual sections** (no command examples)
   - Workflow structure, template syntax, patterns
   - These stay mostly the same

2. **JSON examples**
   - Workflow IR structure is identical
   - No changes needed

#### Sections That Stay the Same

1. **"🎯 What I Can Help You With"** - Concepts only
2. **"🛑 What Workflows CANNOT Do"** - Limitations unchanged
3. **"How to Think About Workflows"** - Mental models
4. **"Building Workflows"** - IR structure identical
5. **"Common Workflow Patterns"** - Pattern examples unchanged
6. **"Workflow Structure Essentials"** - IR schema identical

## Conversion Strategy

### Approach 1: Pattern-Based String Replacement

**Pros**: Simple, fast, easy to validate
**Cons**: Fragile for complex cases

```python
patterns = [
    (r'uv run pflow workflow discover "([^"]+)"', r'workflow_discover(query="\1")'),
    (r'uv run pflow registry discover "([^"]+)"', r'registry_discover(query="\1")'),
    (r'uv run pflow registry run (\S+) (\S+)=(\S+)', r'registry_run(node_type="\1", parameters={"\2": "\3"})'),
    # ... more patterns
]

def convert_cli_to_mcp(text):
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text
```

**Limitations**: Doesn't handle multi-line commands, complex parameter lists

### Approach 2: AST-Based Command Parser

**Pros**: Robust, handles complex commands
**Cons**: More complex implementation

```python
class CommandConverter:
    def parse_cli_command(self, cmd: str) -> Dict:
        """Parse CLI command into structured data"""
        # Parse: uv run pflow [command] [args] [--flags]

    def to_mcp_call(self, parsed: Dict) -> str:
        """Convert parsed command to MCP tool call"""

    def convert_code_block(self, block: str) -> str:
        """Convert entire code block"""
```

### Approach 3: Hybrid (Recommended)

Combine both approaches:
1. Use regex for simple, common patterns (90% of cases)
2. Use parser for complex cases (multi-line, multiple params)
3. Manual review for edge cases

## Programmatic Conversion Script Specification

```python
#!/usr/bin/env python3
"""
Convert CLI-optimized agent instructions to MCP-optimized version.

Usage:
    python convert_instructions.py input.md output.md
"""

from typing import Dict, List, Tuple
import re

class InstructionsConverter:
    """Converts CLI instructions to MCP instructions."""

    # Command mappings
    COMMAND_PATTERNS = {
        'workflow_discover': (
            r'uv run pflow workflow discover "([^"]+)"',
            r'workflow_discover(query="\1")'
        ),
        'registry_discover': (
            r'uv run pflow registry discover "([^"]+)"',
            r'registry_discover(query="\1")'
        ),
        'workflow_execute_simple': (
            r'uv run pflow (\S+\.json) (\w+)=(\S+)',
            r'workflow_execute(workflow="\1", parameters={"\2": "\3"})'
        ),
        'workflow_execute_multiple': (
            r'uv run pflow (\S+\.json) (\w+)=(\S+) (\w+)=(\S+)',
            r'workflow_execute(workflow="\1", parameters={"\2": "\3", "\4": "\5"})'
        ),
        'workflow_validate': (
            r'uv run pflow --validate-only (\S+)',
            r'workflow_validate(workflow="\1")'
        ),
        'workflow_save': (
            r'uv run pflow workflow save (\S+) (\S+) "([^"]+)"',
            r'workflow_save(workflow="\1", name="\2", description="\3")'
        ),
        'registry_run': (
            r'uv run pflow registry run (\S+) (\w+)="([^"]+)" --show-structure',
            r'registry_run(node_type="\1", parameters={"\2": "\3"}, show_structure=true)'
        ),
        'workflow_list': (
            r'uv run pflow workflow list(?: (\S+))?',
            r'workflow_list(filter="\1")' if r'\1' else r'workflow_list()'
        ),
        'settings_set': (
            r'uv run pflow settings set-env (\S+) "([^"]+)"',
            r'settings_set(key="\1", value="\2")'
        ),
    }

    # Flag removals/explanations
    FLAG_NOTES = {
        '--trace': 'MCP always saves traces (built-in)',
        '--no-repair': 'MCP never auto-repairs (built-in)',
        '--json': 'MCP always returns JSON (built-in)',
    }

    def convert_code_block(self, block: str) -> str:
        """Convert a bash code block to MCP syntax."""
        lines = block.split('\n')
        converted = []

        for line in lines:
            if line.strip().startswith('#'):
                # Preserve comments
                converted.append(line)
            elif 'uv run pflow' in line:
                # Try to convert command
                converted_line = self._convert_command(line)
                converted.append(converted_line)
            else:
                converted.append(line)

        return '\n'.join(converted)

    def _convert_command(self, cmd: str) -> str:
        """Convert a single CLI command to MCP."""
        # Remove flags and note them
        flags_found = []
        for flag in self.FLAG_NOTES.keys():
            if flag in cmd:
                flags_found.append(flag)
                cmd = cmd.replace(flag, '').strip()

        # Try each pattern
        for name, (pattern, replacement) in self.COMMAND_PATTERNS.items():
            match = re.match(pattern, cmd.strip())
            if match:
                result = re.sub(pattern, replacement, cmd.strip())
                if flags_found:
                    note = ' '.join([self.FLAG_NOTES[f] for f in flags_found])
                    result += f'  # {note}'
                return result

        # Couldn't convert - return with warning
        return f'{cmd}  # TODO: Manual conversion needed'

    def convert_file(self, input_path: str, output_path: str):
        """Convert entire markdown file."""
        with open(input_path) as f:
            content = f.read()

        # Find all bash code blocks
        code_block_pattern = r'```bash\n(.*?)\n```'

        def replace_block(match):
            block_content = match.group(1)
            converted = self.convert_code_block(block_content)
            return f'```python\n{converted}\n```'

        converted_content = re.sub(
            code_block_pattern,
            replace_block,
            content,
            flags=re.DOTALL
        )

        # Add MCP-specific introduction
        intro = self._generate_mcp_intro()
        converted_content = intro + converted_content

        with open(output_path, 'w') as f:
            f.write(converted_content)

    def _generate_mcp_intro(self) -> str:
        """Generate MCP-specific introduction section."""
        return """# pflow MCP Agent Instructions

## About This Guide

This guide is optimized for AI agents using the **pflow MCP server**. All examples use MCP tool calls instead of CLI commands.

### Key MCP Advantages

1. **Structured Responses**: All tools return JSON (no text parsing needed)
2. **Built-in Defaults**: Traces always saved, no auto-repair, JSON output
3. **Flexible Input**: Workflows can be dicts, names, or file paths
4. **Session Context**: MCP can maintain context across calls
5. **Better Errors**: Structured error responses with full context

### MCP vs CLI Quick Reference

| CLI Command | MCP Tool |
|-------------|----------|
| `uv run pflow workflow discover` | `workflow_discover()` |
| `uv run pflow registry discover` | `registry_discover()` |
| `uv run pflow workflow.json` | `workflow_execute()` |
| `uv run pflow --validate-only` | `workflow_validate()` |

---

"""

# Additional sections to add for MCP version:
MCP_SPECIFIC_SECTIONS = """
## MCP-Specific Patterns

### Pattern 1: Inline Workflow Building
MCP agents can build and test workflows without saving files:

```python
# Build workflow as dict
workflow_ir = {
    "nodes": [...],
    "edges": [...],
    "inputs": {...}
}

# Validate inline
result = workflow_validate(workflow=workflow_ir)

# Execute if valid
if result["valid"]:
    workflow_execute(workflow=workflow_ir, parameters={...})
```

### Pattern 2: Iterative Development
MCP makes iteration faster:

```python
# 1. Discover nodes
nodes = registry_discover(query="slack and sheets")

# 2. Build workflow dict
workflow = build_workflow_from_nodes(nodes)

# 3. Validate
validation = workflow_validate(workflow=workflow)

# 4. If errors, fix and re-validate (no file I/O!)
if not validation["valid"]:
    workflow = fix_errors(workflow, validation["errors"])
    validation = workflow_validate(workflow=workflow)

# 5. Execute when ready
result = workflow_execute(workflow=workflow, parameters={...})
```

### Pattern 3: Session Memory
MCP servers can maintain context:

```python
# First call: Discover and remember
nodes = registry_discover(query="github operations")
# Agent stores nodes in session

# Later call: Reference previous discovery
# Agent uses cached node information
workflow = build_using_cached_nodes()
```

"""
```

## Implementation Plan

### Phase 1: Core Converter (2-3 hours)
1. Implement basic pattern matching for common commands
2. Handle code block extraction and replacement
3. Add flag detection and removal
4. Test on sample sections

### Phase 2: Complex Cases (2-3 hours)
1. Handle multi-line commands
2. Parse complex parameter lists
3. Convert cheat sheets and tables
4. Handle edge cases

### Phase 3: Content Additions (2-3 hours)
1. Add MCP-specific introduction
2. Add MCP-specific patterns section
3. Update conceptual explanations where needed
4. Add notes about built-in behaviors

### Phase 4: Validation (1-2 hours)
1. Manual review of converted content
2. Test command examples
3. Check for consistency
4. Fix any conversion errors

**Total Estimated Time: 8-11 hours**

## Specific Changes Needed

### High-Priority Changes (Breaking)

1. **All bash code blocks** → Python function calls (~50 locations)
2. **Flag references** → Built-in behavior notes (~15 locations)
3. **Command cheat sheet** → Complete rewrite (1 section)
4. **Complete example** → Update all commands (1 section)

### Medium-Priority Changes (Additive)

1. **Add MCP intro section** (new content)
2. **Add MCP-specific patterns** (new content)
3. **Add inline workflow pattern** (new content)
4. **Update "Quick Start"** to mention MCP advantages

### Low-Priority Changes (Nice-to-have)

1. **Add MCP error format examples**
2. **Document MCP tool response structures**
3. **Add session context examples**

## Automation Feasibility: ✅ HIGH

### What Can Be Automated (90%)

1. ✅ Command syntax conversion (regex patterns)
2. ✅ Flag removal and notation (string replacement)
3. ✅ Code block language changes (bash → python)
4. ✅ Parameter format conversion (key=value → JSON)
5. ✅ Table updates (patterns are regular)

### What Needs Manual Work (10%)

1. ⚠️ Conceptual explanations about MCP advantages
2. ⚠️ New sections (MCP patterns, session context)
3. ⚠️ Edge cases (unusual command structures)
4. ⚠️ Final review and quality check

## Maintenance Strategy

### Keep Both Versions Synchronized

**Option 1: Single Source + Templates**
- Maintain content in a template format
- Use variables for command syntax
- Generate both CLI and MCP versions

**Option 2: Conversion Script + Manual Sync**
- Edit CLI version as primary
- Run converter to generate MCP version
- Manually add MCP-specific content

**Option 3 (Recommended): Shared Base + Overlays**
- Maintain shared conceptual content (60%)
- Maintain CLI-specific overlay (20%)
- Maintain MCP-specific overlay (20%)
- Build final docs from base + overlay

## Conclusion

**Yes, programmatic conversion is very feasible!**

The command patterns are regular and predictable, making regex-based conversion straightforward for 90% of content. The remaining 10% requires manual additions for MCP-specific patterns and concepts.

### Recommended Approach

1. **Build the converter script** (Phase 1-2, ~5 hours)
2. **Run automated conversion** (1 minute)
3. **Manual review and enhancement** (Phase 3-4, ~3 hours)
4. **Maintain both versions** using overlay strategy

### ROI Analysis

- **Initial investment**: 8-11 hours to build and run converter
- **Ongoing maintenance**: Same effort for both (edit base + overlays)
- **Benefit**: Perfect CLI/MCP parity with minimal duplication
- **Risk**: Low - converter is testable, changes are reversible

### Next Steps

1. ✅ Get user approval for conversion approach
2. Implement Phase 1 converter (basic patterns)
3. Test on sample sections
4. Complete phases 2-4
5. Establish maintenance workflow
