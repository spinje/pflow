# Refined Specification for 15.2

## Clear Objective
Implement two-phase context building functions that enable the Natural Language Planner to browse components efficiently (discovery) and get detailed information only for selected items (planning), preventing LLM overwhelm.

## Context from Knowledge Base
- Building on: `_load_saved_workflows()` from 15.1, existing helper methods from Task 16
- Avoiding: Parser regex modifications, function complexity limits, silent component skipping
- Following: Exclusive params pattern, no placeholder text convention, error dict format
- Cookbook patterns to apply: Not applicable (no PocketFlow usage in this task)

## Technical Specification

### Function 1: build_discovery_context()

#### Inputs
- `node_ids: list[str] | None` - Node IDs to include (None = all nodes)
- `workflow_names: list[str] | None` - Workflow names to include (None = all workflows)

#### Outputs
- `str` - Markdown formatted discovery context with names/descriptions only

#### Implementation Details
- Get registry using singleton pattern: `registry = get_registry()`
- Extract registry metadata: `registry_metadata = registry.get_metadata()`
- If node_ids is None, use all nodes from registry
- Call `_load_saved_workflows()` to get workflow list
- If workflow_names is None, include all workflows
- Group nodes by category using `_group_nodes_by_category()`
- Format as lightweight markdown (name + description only)
- Add "Available Workflows" section after node categories
- Omit entries with missing descriptions (no placeholders)

### Function 2: build_planning_context()

#### Inputs
- `selected_node_ids: list[str]` - Node IDs to include (required)
- `selected_workflow_names: list[str]` - Workflow names to include (required)
- `registry_metadata: dict[str, dict]` - Full registry metadata
- `saved_workflows: list[dict] | None` - Workflow list (optional, will load if None)

#### Outputs
- `str | dict` - Either markdown formatted planning context OR error dict

#### Implementation Details
- First check for missing components:
  - Check each node_id exists in registry_metadata
  - Check each workflow_name exists in saved_workflows (use pattern: `any(w['name'] == name for w in workflows)`)
- If any missing, return error dict:
  ```python
  {
      "error": "Missing components detected:\n...",
      "missing_nodes": ["node-id-1", "node-id-2"],
      "missing_workflows": ["workflow-name-1"]
  }
  ```
- If all found, build detailed context:
  - Use `_format_node_section()` for each node
  - Create new `_format_structure_combined()` for structure display
  - Apply exclusive params pattern (already in _format_node_section)
  - Include workflow details similar to nodes

### Helper Function: _format_structure_combined()

#### Purpose
Transform nested structure data into combined JSON + paths format for optimal LLM comprehension

#### Implementation
- Takes structure data from metadata
- Generates two representations:
  1. Clean JSON showing structure (types only, no descriptions)
  2. Flat path list with descriptions (e.g., `issue_data.user.login (str) - Username`)
- Returns formatted markdown with both representations

## Implementation Constraints
- Must use: Existing helper methods where applicable
- Must avoid: Modifying parser regex patterns
- Must maintain: Exclusive params pattern, empty params for fallback-only nodes

## Success Criteria
- [ ] Discovery context shows all available components with names/descriptions
- [ ] Planning context shows full details for selected components only
- [ ] Error dict returned when any components missing
- [ ] Structure display uses combined JSON + paths format
- [ ] All existing tests pass
- [ ] No parser modifications made
- [ ] Workflows appear in both contexts appropriately

## Test Strategy
- Unit tests:
  - Discovery with 0, 10, 100 nodes
  - Discovery with and without workflows
  - Planning with valid selections
  - Planning with missing components (error dict)
  - Structure formatting (JSON + paths)
- Integration tests:
  - Full discovery → planning flow
  - Error recovery flow
  - Verify exclusive params still work
- Manual verification:
  - Check markdown formatting is clean
  - Verify structure paths are correct

## Dependencies
- Requires: `_load_saved_workflows()` from subtask 15.1 (completed)
- Requires: Existing helper methods from context_builder.py
- Impacts: Task 17 (Natural Language Planner) will use these functions

## Decisions Made
- Structure enhancement: New helper method approach (confirmed above)
- Workflow organization: Single "Available Workflows" section (confirmed above)
- Test workflow filtering: No filtering for MVP (confirmed above)
