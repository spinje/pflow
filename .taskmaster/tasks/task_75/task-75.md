# Task 75: Execution Preview in Validation

## Description
Enhance the `--validate-only` flag to show a comprehensive execution preview that displays what will execute, in what order, data flow between nodes, required credentials, and estimated execution time/cost. This transforms validation from a simple "valid ✓" into an informative preview that helps agents understand exactly what will happen before execution.

## Status
not started

## Dependencies
- Task 71: Extend CLI Commands for Agent Workflow Building - The `--validate-only` flag was implemented in Task 71, this task enhances its output

## Priority
high

## Details

### Current Problem
The `--validate-only` flag currently only shows basic validation results:
```
✓ Schema validation passed
✓ Data flow validation passed
✓ Template structure validation passed
✓ Node types validation passed

Workflow is valid and ready to execute!
```

This tells agents the workflow is structurally valid but doesn't answer critical questions:
- What will actually execute?
- In what order will nodes run?
- How does data flow between nodes?
- What credentials are needed at runtime?
- What will it cost (LLM tokens)?
- How long will it take?

### Solution: Comprehensive Execution Preview

Transform validation output to show:

#### 1. Node Execution Order
Display all nodes in execution order with:
- Node ID and type
- What outputs each node produces
- Command/configuration preview where relevant
- Dependencies on previous nodes

#### 2. Data Flow Visualization
Show template resolution flow:
- Source node output → destination node input
- Template variable paths (e.g., `${fetch.result.messages[0].text}`)
- Clear visualization of data dependencies

#### 3. Required Credentials Detection
Analyze node types and detect required environment variables:
- Check for LLM nodes → Need ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.
- Check for MCP nodes → Need COMPOSIO_API_KEY or service-specific keys
- Check for Shell nodes → Show commands that will execute
- Indicate which credentials are present ✓ or missing ✗

#### 4. Execution Estimates
Provide rough estimates:
- Duration: Based on node types (shell: <1s, API: 2-3s, LLM: 3-5s)
- Cost: Token estimates for LLM nodes
- API calls: Count of external service calls

### Implementation Approach (MVP)

**Create new module**: `src/pflow/runtime/execution_preview.py`

```python
def generate_execution_preview(
    ir_data: dict,
    registry: Registry,
    execution_params: dict
) -> dict:
    """Generate comprehensive execution preview from validated workflow.

    Returns:
        {
            "execution_order": [...],    # From data flow validation
            "data_flow": [...],          # Template resolution paths
            "required_credentials": {...},  # Detected from node types
            "estimates": {...}           # Time and cost estimates
        }
    """
```

**Enhance**: `src/pflow/cli/main.py` - Update `--validate-only` handler to:
1. Call existing validation (keep current behavior)
2. If valid, call `generate_execution_preview()`
3. Format and display preview
4. Exit without execution

**Key Technical Considerations:**

1. **Execution Order** - Already calculated during data flow validation
   - Reuse `WorkflowValidator.validate()` results
   - Topological sort already determines execution order

2. **Template Tracing** - Extend existing template validator
   - Parse all `${...}` templates in node parameters
   - Map source node.output → destination node.param
   - Show full resolution path

3. **Credential Detection** - Pattern matching on node types
   ```python
   def detect_required_credentials(node_type: str) -> list[str]:
       if node_type == "llm":
           return ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]  # OR
       if node_type.startswith("mcp-"):
           return ["COMPOSIO_API_KEY", f"{server.upper()}_API_KEY"]
       if node_type == "shell":
           return []  # Show command instead
       return []
   ```

4. **Environment Check** - Verify credentials at validation time
   ```python
   import os
   for cred in required_credentials:
       present = os.environ.get(cred) is not None
       status[cred] = "✓" if present else "✗"
   ```

5. **Cost Estimation** - Simple heuristics
   - LLM nodes: Estimate tokens based on prompt length
   - Use default model costs (e.g., Sonnet 4: $3/M input, $15/M output)
   - Rough estimate only (actual may vary)

### MVP Constraints

**What to include:**
- Execution order (node IDs + types)
- Template flow (source → destination mapping)
- Credential detection (env var checks)
- Simple estimates (count-based)

**What to exclude (future):**
- Interactive graph visualization
- Detailed cost breakdowns per model
- Performance profiling
- Dry-run execution with mocks

**Keep it simple:**
- Text output only (no ASCII graphs in MVP)
- Heuristic-based estimates (not precise)
- Basic credential detection (common patterns)
- Informative but not exhaustive

### Example Output Format

```
✓ Workflow is valid and ready to execute!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 Execution Preview
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Node Execution Order:
  1. get-date (shell) → stdout, stderr
  2. fetch-messages (mcp-slack) → result
  3. analyze (llm) → response, llm_usage
  4. send-response (mcp-slack) → result
  5. log (mcp-sheets) → result

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔗 Data Flow
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

get-date.stdout → fetch-messages.params.since
fetch-messages.result → analyze.params.prompt
analyze.response → send-response.params.markdown_text
analyze.response → log.params.values

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔐 Required Credentials
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✗ ANTHROPIC_API_KEY (for: analyze)
✓ COMPOSIO_API_KEY (for: fetch-messages, send-response, log)

⚠️  Missing credentials will cause runtime failures

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⏱️  Estimates
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Duration: ~8-12 seconds
Cost: ~$0.05 (LLM tokens)
API Calls: 4 external requests
```

### Integration Points

1. **WorkflowValidator** (`src/pflow/runtime/workflow_validator.py`)
   - Already computes execution order during data flow validation
   - Provides topological sort of nodes
   - Can extract this data without re-computation

2. **TemplateValidator** (`src/pflow/runtime/template_validator.py`)
   - Already parses all templates
   - Knows which templates reference which node outputs
   - Can be extended to return full resolution map

3. **Registry** (`src/pflow/registry/registry.py`)
   - Node metadata includes output specifications
   - Can be queried for node type information
   - Used to determine credential requirements

4. **CLI Main** (`src/pflow/cli/main.py`)
   - Enhance `--validate-only` handler (currently around line 2950)
   - Add preview generation after successful validation
   - Format and display results

### Design Decisions

**Why not use actual compilation?**
- Preview should be fast (no node instantiation)
- Static analysis is sufficient for preview
- Keeps validation truly read-only

**Why not execute with mocks?**
- That's a different feature (dry-run testing)
- Preview is informational, not execution
- Keeps scope reasonable for MVP

**Why simple text output?**
- ASCII graphs add complexity
- Text is parseable by agents
- Can add visualization later

**Why heuristic estimates?**
- Precise cost calculation requires model loading
- Rough estimates are good enough for preview
- Actual costs shown after execution

## Test Strategy

### Unit Tests
Test each component of the preview system:

1. **Execution Order Extraction**
   - Test with linear workflows (A → B → C)
   - Test with parallel branches (A → B, A → C)
   - Test with complex DAGs
   - Verify topological sort is correct

2. **Template Flow Mapping**
   - Test simple templates: `${node.output}`
   - Test nested paths: `${node.result.data[0].field}`
   - Test multiple templates in one parameter
   - Verify source → destination mapping

3. **Credential Detection**
   - Test LLM nodes detect ANTHROPIC_API_KEY
   - Test MCP nodes detect service-specific keys
   - Test shell nodes show commands
   - Test environment variable checking

4. **Estimate Calculation**
   - Test duration estimates for different node types
   - Test cost estimates for LLM nodes
   - Test API call counting

### Integration Tests
Test the complete preview generation:

1. **Simple Workflow Preview**
   - 3-node workflow (read → llm → write)
   - Verify all sections present
   - Verify correct execution order

2. **Complex Workflow Preview**
   - 8-node workflow with branches
   - Verify data flow visualization
   - Verify credential detection

3. **CLI Integration**
   - Test `--validate-only` displays preview
   - Test with valid workflow
   - Test with invalid workflow (no preview shown)
   - Test output format (text mode)

### Test Coverage Requirements
- Execution order extraction: 100%
- Template flow mapping: 100%
- Credential detection: 90%+ (cover major node types)
- CLI integration: 80%+ (mock preview generation)

### Manual Testing Scenarios
1. Run `--validate-only` on Task 71 test workflows
2. Verify preview matches actual execution behavior
3. Test with workflows missing credentials
4. Verify estimates are reasonable approximations

### Edge Cases to Test
- Empty workflows (no nodes)
- Single-node workflows
- Workflows with no templates
- Workflows with circular dependencies (should fail validation before preview)
- Workflows with unknown node types
- Workflows with mixed credential requirements
