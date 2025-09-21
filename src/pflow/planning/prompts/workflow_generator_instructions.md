---
name: workflow_generator_instructions
test_path: tests/test_planning/llm/prompts/test_workflow_generator_context_prompt.py::TestWorkflowGeneratorContextPrompt
test_command: uv run python tools/test_prompt_accuracy.py workflow_generator_instructions
version: '1.1'
latest_accuracy: 100.0
test_runs: [100.0]
average_accuracy: 100.0
test_count: 15
previous_version_accuracy: 86.7
last_tested: '2025-09-21'
prompt_hash: 48cf6632
last_test_cost: 0.455727
---

# Workflow Generation Instructions

## Your Task

Based on the context provided above (user request, workflow system overview, requirements, plan, and components), generate the complete JSON workflow following the execution plan. Ensure:
- All template variables are properly declared as inputs
- Node outputs are referenced correctly using ${node_id.output_key}
- The workflow follows the sequential execution pattern
- Every input parameter is actually used in at least one node
- The workflow follows the EXACT output format shown in the Workflow System Overview
- You understand and follow the Execution Plan
- You understand and follow the requirements outlined below

## Purpose Field Requirements

Every node MUST have a "purpose" field (10-200 chars) that:
- Explains its role in THIS specific workflow
- Is contextual, not generic
- ✅ GOOD: "Fetch closed issues for changelog generation"
- ❌ BAD: "Process data" or "Use LLM"
- Never include the actual values of input parameters in the purpose field
- ✅ GOOD: "Saves the response from the LLM to a file"
- ❌ BAD: "Saves the response from the LLM to cat-story.txt"

## Workflow Structure Requirements

1. **Start with the first operation** from the plan's node chain
2. **Follow the exact sequence** specified in the plan
3. **Each node must have**:
   - Unique `id` matching the plan (or descriptive if not specified)
   - Correct `type` from available components
   - Clear `purpose` (10-200 chars)
   - Properly templated `params` using ${variables}

4. **The inputs section must include**:
   - Every parameter the user needs to provide
   - Follow the format shown in the Workflow System Overview
   - Each input MUST be an object with: type, description, required fields
   - NO node outputs (those are referenced as ${node_id.output_key})

5. **Create edges to connect nodes** in sequence
6. **Set start_node** to the first node's id

## Important Reminders

- Refer to the **Workflow System Overview** above for:
  - How template variables work
  - Input format requirements
  - Sequential execution rules
  - Node output patterns
- Follow the **Execution Plan** for the node sequence
- Use the **Selected Components** for node types
- Map **Discovered Parameters** to workflow inputs
- Select outputs based on workflow purpose (save vs display)
