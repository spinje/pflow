# pflow Commands Extraction Report

## Summary
- **Total commands found**: 23 unique commands (including variations with flags)
- **Command categories**: 7
- **Most frequently referenced**:
  1. `pflow workflow discover` (mandatory, mentioned 10+ times)
  2. `pflow registry discover` (mandatory, mentioned 8+ times)
  3. `pflow --trace` (debugging, mentioned 6+ times)
  4. `pflow registry run` (testing, mentioned 10+ times)
  5. `pflow workflow save` (mentioned 5+ times)

## Commands by Category

### Workflow Discovery & Management
| CLI Command | MCP Tool Name | MCP Description | Notes |
|------------|---------------|-----------------|-------|
| `pflow workflow discover "request"` | `workflow_discover` | Finds existing workflows matching a natural language request, returns confidence scores and reasoning | **MANDATORY** - Always run first, returns JSON with matches, confidence scores |
| `pflow workflow list` | `workflow_list` | Lists all saved workflows with metadata | Returns workflow names, descriptions, inputs/outputs |
| `pflow workflow save <file> <name> "description"` | `workflow_save` | Saves a workflow to global library for reuse | Accepts `--generate-metadata` and `--delete-draft` flags |

### Node Discovery & Registry
| CLI Command | MCP Tool Name | MCP Description | Notes |
|------------|---------------|-----------------|-------|
| `pflow registry discover "task description"` | `registry_discover` | Uses LLM to intelligently select relevant nodes with complete interface specs | **MANDATORY** for building new workflows, returns complete node specs |
| `pflow registry describe node1 node2` | `registry_describe` | Gets detailed specifications for specific nodes by name | Returns parameter types, descriptions, output structure |
| `pflow registry list` | `registry_list` | Lists all available nodes in the registry | **Warning**: Pollutes context with hundreds of nodes, avoid unless needed |
| `pflow registry search "pattern"` | `registry_search` | Searches for nodes matching a pattern | Useful for finding MCP server tools and meta-tools |
| `pflow registry run NODE --show-structure` | `registry_run` | Executes a single node with parameters to test output structure | **CRITICAL** for MCP nodes - reveals actual nested output structure |

### Workflow Execution
| CLI Command | MCP Tool Name | MCP Description | Notes |
|------------|---------------|-----------------|-------|
| `pflow workflow.json param=value` | `workflow_execute_file` | Executes a workflow from a JSON file with parameters | Basic execution |
| `pflow workflow-name param=value` | `workflow_execute_saved` | Executes a saved workflow by name with parameters | Executes from global library |
| `pflow --trace workflow.json` | `workflow_execute_trace` | Executes workflow with trace output to ~/.pflow/debug/ | Saves to `workflow-trace-*.json` for debugging |
| `pflow --trace-planner "request"` | `planner_execute_trace` | Executes natural language planner with trace output | Saves to `planner-trace-*.json` |
| `pflow --validate-only workflow.json` | `workflow_validate` | Validates workflow structure without execution | Catches structural errors before running |
| `pflow --output-format json workflow.json` | `workflow_execute_json` | Executes workflow with JSON output format | **MANDATORY** for agents building workflows |
| `pflow --no-repair workflow.json` | `workflow_execute_no_repair` | Executes workflow without automatic repair on errors | **MANDATORY** for agents building workflows |

### Combined Execution Flags (Agent Mode)
| CLI Command | MCP Tool Name | MCP Description | Notes |
|------------|---------------|-----------------|-------|
| `pflow --output-format json --no-repair --trace workflow.json` | `workflow_execute_agent_mode` | Executes workflow with all agent-required flags: JSON output, no auto-repair, trace enabled | **MANDATORY** combination when building workflows for AI agents |

### Settings Management
| CLI Command | MCP Tool Name | MCP Description | Notes |
|------------|---------------|-----------------|-------|
| `pflow settings set-env KEY value` | `settings_set_env` | Sets API keys and authentication credentials in ~/.pflow/settings.json | Only for authentication secrets, not workflow parameters |
| `pflow settings get-env KEY` | `settings_get_env` | Retrieves a setting value | Implicit from documentation context |
| `pflow settings list` | `settings_list` | Lists all configured settings | Implicit from documentation context |

### Direct Execution (Natural Language)
| CLI Command | MCP Tool Name | MCP Description | Notes |
|------------|---------------|-----------------|-------|
| `pflow "natural language request"` | `execute_natural_language` | Executes planner to generate and run workflow from natural language | Combines discovery, building, and execution |

### Debugging & Inspection
| CLI Command | MCP Tool Name | MCP Description | Notes |
|------------|---------------|-----------------|-------|
| `cat ~/.pflow/debug/workflow-trace-*.json \| jq '.nodes[0].outputs'` | N/A - Shell command | Not a pflow command, but critical pattern for debugging | Agents should use shell tools or pflow should expose trace reading |
| `cat ~/.pflow/debug/workflow-trace-*.json \| jq '.events[] \| select(.node_id == "X")'` | N/A - Shell command | Not a pflow command, but critical pattern for debugging | Same as above |

## Command Usage Examples

### Example 1: Workflow Discovery (MANDATORY FIRST STEP)
```bash
uv run pflow workflow discover "user's exact request here"
```
**Purpose**: Find existing workflows before building new ones. Returns:
- Match confidence scores (≥95% = use it, 80-95% = confirm, <80% = build new)
- Workflow names and descriptions
- Required inputs/outputs
- Reasoning for matches

**Critical**: This is the FIRST command agents must run. "This takes 5 seconds. Building unnecessarily takes hours."

### Example 2: Node Discovery for Building
```bash
uv run pflow registry discover "I need to fetch Slack messages, analyze with AI, send responses, and log to Google Sheets"
```
**Purpose**: Find nodes needed to build a new workflow. Returns:
- Complete interface specifications
- Parameter types and descriptions
- Output structure
- Usage requirements

### Example 3: Testing MCP Nodes (CRITICAL)
```bash
uv run pflow registry run mcp-service-TOOL_NAME param1="value1" --show-structure
```
**Purpose**: Reveals actual nested output structure of MCP nodes. "MCP outputs are NEVER simple."
- Documentation says: `result: Any`
- Reality: `result.data.tool_response.nested.deeply.url`

### Example 4: Validation Before Execution
```bash
uv run pflow --validate-only workflow.json
```
**Purpose**: Catch structural errors before execution
- Validates template variables exist
- Checks node types are valid
- Verifies edge connections
- No actual execution

### Example 5: Agent Mode Execution
```bash
uv run pflow --output-format json --no-repair --trace workflow.json param1=value param2=value
```
**Purpose**: Execute with all agent-required flags
- `--output-format json`: Structured output for parsing
- `--no-repair`: No automatic fixes (explicit errors)
- `--trace`: Save debug info to ~/.pflow/debug/

### Example 6: Saving Workflows
```bash
uv run pflow workflow save .pflow/workflows/your-draft.json workflow-name "Clear description" --generate-metadata --delete-draft
```
**Purpose**: Save tested workflow to global library for reuse

### Example 7: Running Saved Workflows
```bash
uv run pflow workflow-name channel=C123 sheet_id=abc123
```
**Purpose**: Execute saved workflow with parameters

### Example 8: Settings Management
```bash
uv run pflow settings set-env REPLICATE_API_TOKEN "secret123"
```
**Purpose**: Store authentication credentials securely

## Common Command Sequences

### Pattern 1: Discovery → Execute Existing Workflow
1. `pflow workflow discover "user's exact request"`
2. If ≥95% match: `pflow workflow-name param1=value param2=value`
3. Done!

### Pattern 2: Discovery → Build New Workflow
1. `pflow workflow discover "user request"` (check for existing)
2. If <80% match: `pflow registry discover "specific task description"` (find nodes)
3. Build JSON workflow file
4. `pflow --validate-only workflow.json` (validate structure)
5. `pflow --trace workflow.json param=value` (test execution)
6. `pflow workflow save workflow.json name "description"` (save for reuse)

### Pattern 3: Testing Unknown MCP Nodes
1. `pflow registry search "servername"` (find meta-tools)
2. `pflow registry run mcp-service-LIST_SCHEMAS --show-structure` (use helper tools)
3. `pflow registry run mcp-service-TOOL param="test" --show-structure` (test actual tool)
4. Document actual output structure for templates

### Pattern 4: Debugging Template Errors
1. `pflow --trace workflow.json` (execute with trace)
2. Check error output for available fields
3. `cat ~/.pflow/debug/workflow-trace-*.json | jq '.nodes[] | select(.id=="node-name")'`
4. Update templates with actual field paths

### Pattern 5: Agent Workflow Building (Complete)
1. `pflow workflow discover "user request"` **(MANDATORY)**
2. If building new: `pflow registry discover "task description"` **(MANDATORY)**
3. Test unknown nodes: `pflow registry run NODE --show-structure`
4. Build workflow JSON
5. `pflow --validate-only workflow.json`
6. `pflow --output-format json --no-repair --trace workflow.json params` **(MANDATORY FLAGS)**
7. Fix errors, iterate
8. `pflow workflow save workflow.json name "description"`
9. Tell user: `pflow workflow-name param=value`

## Critical Findings

### Essential Commands for Agents

**Priority 1 (MUST HAVE):**
1. `workflow discover` - Mandatory first step, prevents duplicate work
2. `registry discover` - Intelligent node selection for building
3. `registry run --show-structure` - Critical for understanding MCP output structures
4. `workflow_execute` with agent flags (`--trace --no-repair --output-format json`)
5. `workflow validate` - Catch errors before execution
6. `workflow save` - Make workflows reusable

**Priority 2 (SHOULD HAVE):**
7. `registry describe` - Get specific node specs
8. `registry search` - Find MCP tools and meta-tools
9. `workflow list` - Show available workflows
10. `settings set-env` - Configure authentication

**Priority 3 (NICE TO HAVE):**
11. `registry list` - Browse all nodes (warning: verbose)
12. Natural language execution - One-shot workflow creation

### Commands with Special Agent Behavior

1. **`--output-format json`**: Returns structured output instead of human-readable
2. **`--no-repair`**: Disables automatic error fixing, shows explicit errors to agent
3. **`--trace`**: Saves execution trace to `~/.pflow/debug/workflow-trace-*.json`
4. **`--trace-planner`**: Saves planner trace to `~/.pflow/debug/planner-trace-*.json`
5. **`--validate-only`**: Returns validation errors without execution
6. **`--show-structure`**: Shows complete output structure for nodes (not mentioned as flag, but usage pattern)

### Commands Returning Structured Data

✅ **JSON-friendly commands** (ideal for MCP):
- `workflow discover` - Returns matches with scores, reasoning
- `registry discover` - Returns node interfaces, specs
- `registry describe` - Returns node metadata
- `registry search` - Returns matching node names
- `registry run --show-structure` - Returns complete output structure
- `workflow list` - Returns workflow metadata
- Execution with `--output-format json` - Returns structured results

❌ **Human-readable only** (need JSON option):
- Settings commands (likely return simple strings)
- Validation errors (might be structured, need to verify)

## Special Considerations

### Stdin/Stdout Integration
- Not explicitly shown in AGENT_INSTRUCTIONS.md
- CLAUDE.md mentions "shell pipe syntax for stdin/stdout integration"
- Likely supports: `echo "input" | pflow workflow.json`
- **Action**: Verify if MCP tools need to handle stdin/stdout

### Interactive Prompts
- Documentation explicitly states "No interactive prompts" for workflows
- All parameters must be provided via command line
- **Action**: MCP tools should expect all parameters upfront

### File Operations
- Commands modify files: `workflow save` creates files in ~/.pflow/
- Commands read files: workflow execution reads .json files
- Trace files written to `~/.pflow/debug/`
- **Action**: MCP tools need file read/write capabilities

### Long-Running Operations
- Workflow execution can take 3-5 minutes for complex workflows
- External API calls add 30-60 seconds each
- **Action**: MCP tools should have appropriate timeouts

### Error Handling
- `--no-repair` flag is MANDATORY for agents - disables auto-fixing
- Validation returns detailed error messages with field suggestions
- Template errors show available fields (first 5, then refer to trace)
- **Action**: MCP tools should return full error details

## Recommendations for MCP Implementation

### Priority 1 Tools (Must Have)

These are ESSENTIAL for the agent workflow building loop:

1. **`workflow_discover`**
   - Input: `query` (string) - natural language request
   - Output: JSON array of matches with scores, descriptions, inputs/outputs, reasoning
   - Why: Mandatory first step, prevents duplicate work
   - Usage frequency: Every new request

2. **`registry_discover`**
   - Input: `task_description` (string) - what needs to be built
   - Output: JSON array of node specs with interfaces, parameters, outputs
   - Why: Intelligent node selection for building workflows
   - Usage frequency: Every new workflow build

3. **`registry_run`**
   - Inputs: `node_type` (string), `params` (object), `show_structure` (boolean)
   - Output: Node execution result with complete structure
   - Why: Critical for discovering MCP node output structures
   - Usage frequency: When testing unknown nodes

4. **`workflow_execute_agent_mode`**
   - Inputs: `workflow_file_or_name` (string), `parameters` (object)
   - Auto-applies: `--trace --no-repair --output-format json`
   - Output: Structured execution result with trace file path
   - Why: Standard execution mode for agents
   - Usage frequency: Every workflow test/execution

5. **`workflow_validate`**
   - Input: `workflow_file` (string)
   - Output: Validation result with errors or success
   - Why: Catch errors before execution
   - Usage frequency: Every workflow before testing

6. **`workflow_save`**
   - Inputs: `workflow_file` (string), `name` (string), `description` (string), `generate_metadata` (boolean), `delete_draft` (boolean)
   - Output: Save confirmation with workflow name
   - Why: Make workflows reusable
   - Usage frequency: After successful workflow testing

### Priority 2 Tools (Should Have)

7. **`registry_describe`**
   - Input: `node_names` (array of strings)
   - Output: Detailed specs for specific nodes
   - Why: Get specific node information when names are known

8. **`registry_search`**
   - Input: `pattern` (string)
   - Output: Matching node names
   - Why: Find MCP servers and meta-tools

9. **`workflow_list`**
   - Input: None (or optional filter)
   - Output: Array of workflow metadata
   - Why: Browse available workflows

10. **`settings_set_env`**
    - Inputs: `key` (string), `value` (string)
    - Output: Confirmation
    - Why: Configure authentication credentials

11. **`settings_get_env`**
    - Input: `key` (string)
    - Output: Value or null
    - Why: Retrieve settings

### Priority 3 Tools (Nice to Have)

12. **`registry_list`**
    - Input: Optional filters
    - Output: All available nodes
    - Warning: Can return hundreds of nodes
    - Why: Browse complete registry

13. **`execute_natural_language`**
    - Input: `request` (string)
    - Output: Generated workflow and execution result
    - Why: One-shot workflow creation and execution
    - Note: Complex, might not be needed if agents use individual steps

14. **`trace_read`**
    - Input: `trace_file` (string) or latest
    - Output: Parsed trace data
    - Why: Currently requires shell commands, should be native
    - Note: Agents need structured access to trace files

### Execution Flag Combinations

**Agent Mode** (combine these into single tool):
- `--output-format json` + `--no-repair` + `--trace`
- Mentioned together 5+ times as "MANDATORY for agents"
- Should be default behavior for MCP tools

### Tool Design Patterns

1. **Discovery Tools**: Return structured data with confidence/relevance scores
2. **Execution Tools**: Support trace mode, JSON output, no auto-repair
3. **Validation Tools**: Return detailed errors with suggestions
4. **Testing Tools**: Reveal actual structure, not just documentation

## Additional Implementation Notes

### Command Variations to Handle

1. **File vs. Name execution**:
   - `pflow workflow.json` (file path)
   - `pflow workflow-name` (saved workflow)
   - MCP tool should detect which is which

2. **Parameter passing**:
   - CLI: `param1=value param2=value`
   - MCP: Should accept `parameters` object

3. **Flag combinations**:
   - Create "agent mode" that combines common flags
   - Individual flags still available for specific use cases

### Error Messages to Preserve

The documentation emphasizes detailed error messages:
- Template errors show available fields (5 of N)
- Validation errors suggest fixes
- Trace file paths included in errors

MCP tools should return these verbatim.

### File Path Handling

- Workflow files: Can be relative or absolute
- Trace files: Always in `~/.pflow/debug/`
- Settings: Always in `~/.pflow/settings.json`
- Draft workflows: Usually in `.pflow/workflows/`

MCP tools need to handle path resolution.

### Authentication Flow

From documentation:
1. Store in settings: `pflow settings set-env TOKEN "secret"`
2. Declare as workflow input
3. Pass at runtime or use environment variable

MCP tools should support both settings management and parameter passing.

## Missing Commands (Implied but Not Shown)

Based on the documentation, these commands likely exist but aren't explicitly shown:

1. **`pflow workflow load <name>`**: Load workflow JSON to view/edit
2. **`pflow workflow delete <name>`**: Remove saved workflow
3. **`pflow settings list`**: Show all settings
4. **`pflow settings delete KEY`**: Remove setting
5. **`pflow registry refresh`**: Reload registry (if dynamic)
6. **`pflow version`**: Show version (mentioned in CLAUDE.md)

**Recommendation**: Verify these exist in actual CLI before implementing MCP tools.

## Key Insights for MCP Server Design

1. **Two-Phase Discovery is Critical**:
   - Phase 1: Workflow discovery (find existing)
   - Phase 2: Node discovery (build new)
   - MCP server MUST enforce this pattern

2. **Structured Output is Non-Negotiable**:
   - All discovery/execution commands need JSON output
   - Human-readable output is secondary for agents

3. **Testing Before Building**:
   - `registry run --show-structure` is essential
   - MCP nodes have deeply nested outputs
   - Testing saves hours of debugging

4. **Validation is Separate from Execution**:
   - `--validate-only` catches errors early
   - Cheaper than full execution
   - Should be its own MCP tool

5. **Trace Files are Central to Debugging**:
   - Every execution should support trace
   - Trace reading should be native (not shell commands)
   - Consider dedicated trace tools

6. **Settings vs. Parameters**:
   - Settings: Authentication only
   - Parameters: Workflow-specific data
   - MCP tools need both mechanisms

## Conclusion

The AGENT_INSTRUCTIONS.md reveals a sophisticated CLI workflow system with:
- **Mandatory discovery** preventing duplicate work
- **Intelligent node selection** using LLM
- **Comprehensive testing** before execution
- **Structured output** for agents
- **Rich debugging** with trace files

The MCP server should expose these capabilities as tools while maintaining the enforced workflow:
1. Discover existing workflows first
2. Build new only if needed
3. Test nodes before integration
4. Validate before executing
5. Execute with full tracing
6. Save for reuse

**Next Steps**:
1. Verify all commands exist in actual CLI
2. Design MCP tool schemas with appropriate parameters
3. Implement agent mode defaults (JSON output, no repair, trace)
4. Add trace file reading as native tool
5. Test discovery tools return correct structured data
