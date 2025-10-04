# Repair System Context Analysis

## Executive Summary

The repair system has **significantly less rich context** than the planner. While the planner gets detailed node interfaces with structured type information, the repair system only gets:
- Error messages
- Failed workflow IR (JSON)
- Checkpoint data (completed nodes, failed node)
- Generic category guidance
- Original request (if available)

**Critical Gap**: Repair does NOT have access to:
- Node interface specifications (inputs/outputs/params with types)
- Output structure schemas (for template resolution guidance)
- Available fields from upstream nodes
- Type information for data flow validation

---

## 1. What Planner Gets (Rich Context)

### Node Interface Information

From `context_builder.py` → `build_planning_context()`:

**For each selected node, planner receives:**

```markdown
### read-file

Read content from a file and add line numbers for display.

**Parameters**:
- `file_path: str` - Path to the file to read
- `encoding: str` - File encoding (optional, default: utf-8)

**Outputs**:
- `content: str` - File contents with line numbers
- `error: str` - Error message if operation failed
```

**For complex structured outputs:**

```markdown
**Outputs**:
- `issue_data: dict` - GitHub issue data

Structure (JSON format):
```json
{
  "issue_data": {
    "number": 123,
    "title": "string",
    "body": "string",
    "state": "open|closed",
    "labels": ["label1", "label2"]
  }
}
```

Available paths:
- issue_data.number (int) - Issue number
- issue_data.title (str) - Issue title
- issue_data.body (str) - Issue description
- issue_data.state (str) - Issue state
- issue_data.labels (list[str]) - Issue labels
```

### Full Registry Metadata

Planner has access to complete registry via `ComponentBrowsingNode`:

```python
{
  "read-file": {
    "class_name": "ReadFileNode",
    "module": "pflow.nodes.file.read_file",
    "type": "core",
    "interface": {
      "description": "Read content from a file...",
      "inputs": [
        {
          "key": "file_path",
          "type": "str",
          "description": "Path to the file to read"
        },
        {
          "key": "encoding",
          "type": "str",
          "description": "File encoding (optional, default: utf-8)"
        }
      ],
      "outputs": [
        {
          "key": "content",
          "type": "str",
          "description": "File contents with line numbers"
        },
        {
          "key": "error",
          "type": "str",
          "description": "Error message if operation failed"
        }
      ],
      "params": [],
      "actions": ["default", "error"]
    }
  }
}
```

### Workflow Structure Context

Planner gets saved workflow details with:
- Input/output declarations
- Node configuration examples
- Execution flow patterns

---

## 2. What Repair Gets (Minimal Context)

### Repair Prompt Structure

From `repair_service.py` → `_build_repair_prompt()`:

```markdown
Fix this workflow that has errors.

## Core Repair Principle
The error occurred at one node, but the fix might be in a different node. Consider the data flow:
- If a node fails because of bad input format, fix the UPSTREAM node that produces that data
- If an LLM node's output causes downstream failures, improve its prompt with clear formatting instructions and examples
- Read the error carefully to understand what data format is expected vs what was received

## Original Request
{original_request or "Not available"}

## Failed Workflow
```json
{workflow_ir}
```

## Errors to Fix
1. Template variable ${fetch.result.data} not found
   Category: template_error
   Node: process

## Repair Context
- Completed nodes: fetch, analyze
- Failed at node: process

## Guidance for Error Categories Present

### Template Variable Resolution Errors
- Template path ${node.field} references non-existent data
- Check what fields the referenced node ACTUALLY outputs
- Common issue: Assuming a field exists when it doesn't
- Solution: Correct the template path to match actual output
- Solution: Modify upstream node to produce the expected field
- Tip: Check if the node uses namespacing (data might be at ${node.result.field})

## Your Task
Analyze the error and fix the root cause, which may be in an upstream node. Only modify what's necessary to fix the issue.

Return ONLY the corrected workflow JSON.
```

### Error Structure

```python
{
    "source": "runtime",              # Where error originated
    "category": "template_error",     # Error classification
    "message": "Template ${data.field} not found",
    "node_id": "process",             # Failed node
    "fixable": True,                  # Repair eligibility
    "exception_type": "KeyError",     # Exception type (optional)
    "hint": "Check template path"     # Hint (optional)
}
```

### Checkpoint Data (from shared store)

```python
{
    "completed_nodes": ["fetch", "analyze"],
    "failed_node": "process",
    "node_actions": {
        "fetch": "default",
        "analyze": "default"
    }
}
```

### Category Guidance

Generic guidance per error category:
- `template_error`: "Check what fields the referenced node ACTUALLY outputs"
- `api_validation`: "Match the exact format the API expects"
- `execution_failure`: "Check the UPSTREAM node that produces the failing input"

**NO ACTUAL INTERFACE DATA** - Just generic advice!

---

## 3. Comparison: Planner vs Repair Context

| Information Type | Planner Context | Repair Context | Gap Impact |
|-----------------|-----------------|----------------|------------|
| **Node Interfaces** | Full specs (inputs/outputs/params with types) | ❌ None | **CRITICAL** - Can't verify template paths |
| **Output Structures** | Complete schemas with paths | ❌ None | **CRITICAL** - Can't fix template errors |
| **Type Information** | Explicit types (str, dict, list[dict]) | ❌ None | **HIGH** - Can't validate data flow |
| **Field Descriptions** | Clear descriptions for each field | ❌ None | **MEDIUM** - Harder to understand intent |
| **Available Fields** | Lists all available output fields | ❌ None | **CRITICAL** - Can't suggest corrections |
| **Registry Metadata** | Full registry access | ❌ None | **HIGH** - Can't verify node types |
| **Workflow Examples** | Saved workflow patterns | ❌ None | **MEDIUM** - No reference patterns |
| **Error Context** | ❌ None | Error messages + checkpoint | **N/A** |
| **Category Guidance** | ❌ None | Generic repair strategies | **LOW** - Too generic |
| **Original Request** | Full request in planner | Optional in repair | **MEDIUM** - May miss intent |

---

## 4. Template Resolution Error Example

### Scenario: Template Error

**Error:**
```
Template variable ${fetch.result.data.items} not found in shared store
```

### What Planner Would See:

```markdown
### fetch (github-list-issues)

**Outputs**:
- `result: dict` - API response data

Structure (JSON format):
```json
{
  "result": {
    "issues": [
      {
        "number": 123,
        "title": "string",
        "body": "string"
      }
    ],
    "total_count": 10
  }
}
```

Available paths:
- result.issues (list[dict]) - List of issues
- result.issues[].number (int) - Issue number
- result.issues[].title (str) - Issue title
- result.total_count (int) - Total issue count
```

**Planner can see:** The correct path is `${fetch.result.issues}` not `${fetch.result.data.items}`

### What Repair Currently Sees:

```markdown
## Errors to Fix
1. Template variable ${fetch.result.data.items} not found
   Category: template_error
   Node: process

## Repair Context
- Completed nodes: fetch
- Failed at node: process

### Template Variable Resolution Errors
- Check what fields the referenced node ACTUALLY outputs
- Solution: Correct the template path to match actual output
```

**Repair must guess:** No information about what fields `fetch` actually outputs!

---

## 5. What CLI Errors Show Users

From execution, users see:

```
Error in node 'process':
  Template variable '${fetch.result.data.items}' not found in shared store
  Available in shared store: fetch
  Available fields in fetch: result
```

**Better than repair gets, but still not complete!**

The runtime has access to the actual shared store data, so it can show:
- What keys exist (`fetch`)
- What nested fields exist (`result`)
- But NOT what fields SHOULD exist according to the interface

---

## 6. Recommendations for Agent Access

### High Priority - Critical for Repair

1. **Node Interface Lookup**
   - **What**: Get inputs/outputs/params for a specific node type
   - **Why**: Essential for template error repair
   - **Example**: `get_node_interface("github-list-issues")` → Full interface spec
   - **Impact**: Enables accurate template path corrections

2. **Output Structure Schema**
   - **What**: Get detailed structure for complex outputs
   - **Why**: Repair needs to know available paths
   - **Example**: `get_output_structure("github-list-issues", "result")` → Path list
   - **Impact**: Can suggest correct template variables

3. **Template Validation**
   - **What**: Validate template path against node interface
   - **Why**: Verify fixes before generating repair
   - **Example**: `validate_template("${fetch.result.issues}", workflow_ir)` → Valid/Invalid + suggestions
   - **Impact**: Prevents generating broken repairs

### Medium Priority - Helpful for Planning

4. **Node Discovery/Search**
   - **What**: Search nodes by capability/description
   - **Why**: Find alternative nodes when current approach fails
   - **Example**: `search_nodes("read file contents")` → List of file nodes
   - **Impact**: Can suggest different node types

5. **Workflow Examples**
   - **What**: Find similar saved workflows
   - **Why**: Learn patterns from working examples
   - **Example**: `find_workflows_using_node("github-list-issues")` → Example workflows
   - **Impact**: Copy proven patterns

6. **Dependency Analysis**
   - **What**: Understand data flow between nodes
   - **Why**: Identify upstream source of issues
   - **Example**: `get_data_dependencies("process")` → What nodes provide its inputs
   - **Impact**: Better upstream fix suggestions

### Lower Priority - Nice to Have

7. **Error Pattern Matching**
   - **What**: Match errors to common fix patterns
   - **Why**: Apply known solutions
   - **Example**: `match_error_pattern(error)` → Suggested fix pattern
   - **Impact**: Faster repairs for common issues

8. **Type Checking**
   - **What**: Validate type compatibility between nodes
   - **Why**: Catch type mismatches
   - **Example**: `check_type_compatibility(upstream, downstream)` → Compatible/Incompatible
   - **Impact**: Prevent type-related failures

---

## 7. Proposed CLI Commands for Agents

Based on gaps identified:

### Discovery Commands (for finding information)

```bash
# Get node interface specification
pflow registry show <node-type> [--format=json|yaml|markdown]

# Search for nodes by capability
pflow registry search "read file" [--format=json]

# List all nodes with brief descriptions
pflow registry list [--category=file|git|github|llm] [--format=json]

# Show output structure for a node
pflow registry describe <node-type> --output=<field-name>
```

### Validation Commands (for verifying fixes)

```bash
# Validate a workflow without running it
pflow validate workflow.json [--explain]

# Validate a specific template variable
pflow validate template '${node.field.path}' workflow.json

# Check type compatibility
pflow validate types workflow.json [--node=<id>]
```

### Analysis Commands (for understanding workflows)

```bash
# Show data flow through workflow
pflow analyze dataflow workflow.json

# Show dependencies for a node
pflow analyze dependencies workflow.json --node=<id>

# Find workflows using a specific node
pflow workflows find --using-node=<type>
```

---

## 8. Immediate Next Steps

### For Task 71 (CLI Agent Workflow)

1. **Start with Discovery Commands** (highest ROI)
   - `pflow registry show <node-type>` - Get full interface
   - `pflow registry search <query>` - Find nodes
   - `pflow registry list` - Browse available nodes

2. **Add Validation Commands**
   - `pflow validate workflow.json` - Validate before execution
   - `pflow validate template <var> workflow.json` - Template checking

3. **Consider Analysis Commands** (if time permits)
   - `pflow analyze dataflow workflow.json` - Understand flow
   - `pflow workflows find --using-node=<type>` - Find examples

### For Improving Repair (Future)

1. **Enhance Repair Context** (src/pflow/execution/repair_service.py)
   - Add node interface lookup in `_analyze_errors_for_repair()`
   - Include available fields for template errors
   - Show correct paths from interface schemas

2. **Template Error Enrichment**
   - When template error occurs, fetch node interface
   - Compare template path against actual output structure
   - Suggest correct paths in repair context

3. **Type Validation in Repair**
   - Check type compatibility when repairing
   - Verify upstream node outputs match downstream inputs

---

## 9. Key Insights

### Why Planner Works Better

1. **Proactive Context Building**: Planner builds full context upfront via `ComponentBrowsingNode`
2. **Structured Information**: Uses registry metadata systematically
3. **Schema-Driven**: Has complete type information for generation

### Why Repair Struggles

1. **Reactive Context**: Only gets error messages after failure
2. **No Interface Access**: Must guess what fields should exist
3. **Generic Guidance**: Category guidance is too abstract

### The Gap

**Planner has registry access during generation, repair doesn't during fixing.**

Solution: Give agents (and repair) the same registry access tools the planner has internally.

---

## 10. Conclusion

The repair system's context is **fundamentally incomplete** for fixing template errors and data flow issues. It lacks the node interface information that would enable:
- Accurate template path corrections
- Output structure validation
- Type compatibility checking

**Recommendation**: Prioritize CLI commands that expose registry information, starting with:
1. `pflow registry show <node-type>` (interface lookup)
2. `pflow registry search <query>` (node discovery)
3. `pflow validate template <var> workflow.json` (template validation)

These commands would benefit both:
- **Agents** building workflows (primary use case)
- **Repair system** fixing workflows (future enhancement)
