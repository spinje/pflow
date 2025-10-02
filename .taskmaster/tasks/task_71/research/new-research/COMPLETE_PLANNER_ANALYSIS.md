# Complete Planner Workflow & CLI Gap Analysis

## Executive Summary

**Purpose**: Identify ALL planner capabilities and determine which are missing from CLI for agent access.

**Key Finding**: Agents have NO ACCESS to the planner's core discovery and validation capabilities. They can only execute workflows, not build them intelligently.

---

## Part 1: Complete Planner Workflow Trace

### The 11-Node Planning Pipeline

The planner is a sophisticated meta-workflow with **11 nodes** that transform natural language into executable IR. Here's the complete flow:

```
┌─────────────────────────────────────────────────────────────┐
│                    PLANNER META-WORKFLOW                     │
│                   (Two-Path Architecture)                    │
└─────────────────────────────────────────────────────────────┘

START → WorkflowDiscoveryNode
         ↓
         ├─ "found_existing" (PATH A - Reuse) ──────────────┐
         │                                                   ↓
         └─ "not_found" (PATH B - Generate)          ParameterMappingNode
                  ↓                                          ↑
           ParameterDiscoveryNode                            │
                  ↓                                          │
           RequirementsAnalysisNode                          │
                  ↓                                          │
           ComponentBrowsingNode ─────────────────────────────┘
                  ↓                                    (after generation)
           PlanningNode
                  ↓
           WorkflowGeneratorNode ────────────────────────────┐
                  ↓                                           │
           ParameterMappingNode (CONVERGENCE POINT)          │
                  ↓                                           │
                  ├─ "params_complete_validate"               │
                  │        ↓                                  │
                  │   ValidatorNode                           │
                  │        ↓                                  │
                  │        ├─ "metadata_generation"           │
                  │        │        ↓                         │
                  │        │   MetadataGenerationNode         │
                  │        │        ↓                         │
                  │        │   ParameterPreparationNode ──┐   │
                  │        │                              │   │
                  │        ├─ "retry" ────────────────────┼───┘
                  │        │                              │  (up to 3x)
                  │        └─ "failed" ──────────────┐    │
                  │                                  │    │
                  └─ "params_incomplete" ────────────┼────┘
                                                     ↓
                                              ResultPreparationNode
                                                     ↓
                                                   END
```

### Node-by-Node Capabilities

#### 1. **WorkflowDiscoveryNode** (Entry Point)
- **Purpose**: Binary decision - reuse existing workflow OR generate new one
- **Inputs**: `user_input`, `stdin_data` (optional), `current_date` (optional)
- **Outputs**:
  - `discovery_context` (str) - Full context for LLM
  - `discovery_result` (dict) - Decision details
  - `found_workflow` (dict) - Workflow metadata if found (Path A only)
- **Actions**: `"found_existing"` (Path A) or `"not_found"` (Path B)
- **LLM Call**: Yes - uses structured output (WorkflowDecision schema)
- **Key Capability**: **Intelligent workflow matching** - not just name search, semantic understanding

#### 2. **ParameterDiscoveryNode** (Path B Only)
- **Purpose**: Extract named parameters from natural language BEFORE requirements analysis
- **Inputs**: `user_input`, `stdin_data` (optional)
- **Outputs**:
  - `parameter_discovery_result` (dict) - Extracted parameters
  - `discovered_params` (dict) - Key-value pairs
- **LLM Call**: Yes - uses structured output
- **Key Capability**: **Smart parameter extraction** - understands "analyze repo spinje/pflow PR #123" → `{repo: "spinje/pflow", pr_number: 123}`


#### 3. **RequirementsAnalysisNode** (Path B Only)
- **Purpose**: Extract abstract operational requirements AND determine complexity/thinking budget
- **Outputs**: `requirements_result`, `complexity_score`, `thinking_budget`
- **LLM Call**: Yes - with extended_thinking based on complexity
- **Key Capability**: **Complexity assessment** - allocates thinking tokens dynamically

#### 4. **ComponentBrowsingNode** (Path B Only)
- **Purpose**: LLM-powered selection of relevant nodes/workflows from entire registry
- **Outputs**: `planning_context`, `selected_components`
- **LLM Call**: Yes - uses structured output (ComponentSelection schema)
- **Key Capability**: **Intelligent component discovery** - filters 50+ nodes down to 3-5 relevant ones

#### 5. **PlanningNode** (Path B Only)
- **Purpose**: Create execution plan using selected components
- **Outputs**: `planning_result` (feasibility, plan, missing_capabilities, confidence)
- **Actions**: FEASIBLE/IMPOSSIBLE/PARTIAL
- **LLM Call**: Yes - with extended_thinking
- **Key Capability**: **Feasibility assessment** - prevents impossible workflows

#### 6. **ParameterMappingNode** (CONVERGENCE POINT - Both Paths)
- **Purpose**: Extract parameter VALUES from user input for workflow execution
- **Outputs**: `extracted_params`
- **LLM Call**: Yes
- **Key Capability**: **Intelligent parameter extraction** - maps natural language to structured inputs

#### 7. **WorkflowGeneratorNode** (Path B Only)
- **Purpose**: Generate workflow IR from execution plan
- **Outputs**: `generated_workflow_ir`
- **LLM Call**: Yes - uses structured output (IR schema)
- **Key Capability**: **IR generation from plan**

#### 8. **ValidatorNode** (Path B Only)
- **Purpose**: Multi-layer validation of generated workflow
- **Validation Layers**:
  1. IR Schema Validation (Pydantic)
  2. Template Validation (all variables have sources)
  3. Compilation Check (can it be built?)
  4. Runtime Dry-Run (optional)
- **LLM Call**: No - pure validation logic
- **Key Capability**: **Comprehensive validation**

#### 9. **MetadataGenerationNode** (Path B Only)
- **Purpose**: Generate rich, searchable metadata
- **Outputs**: `rich_metadata` (summary, capabilities, keywords, use_cases)
- **LLM Call**: Yes
- **Key Capability**: **Semantic metadata generation**

#### 10-11. **ParameterPreparationNode** and **ResultPreparationNode**
- Final formatting and packaging nodes

---

## Part 2: Supporting Infrastructure

### Context Building Functions (src/pflow/planning/context_builder.py)

1. **`build_nodes_context(node_ids, registry_metadata)`** - Numbered list of node details
2. **`build_workflows_context(workflow_names, workflow_manager)`** - Workflow descriptions
3. **`build_planning_context(selected_node_ids, selected_workflow_names, ...)`** - Full component details

### Validation Infrastructure (src/pflow/runtime/)

1. **`TemplateValidator.validate_workflow_templates(workflow_ir, available_params, registry)`**
2. **`validate_ir_structure(ir_dict)`** - Basic IR validation
3. **`validate_ir(data)`** - Pydantic schema validation
4. **`compile_ir_to_flow(workflow_ir, registry, ...)`** - Full compilation validation

### Template Resolution (src/pflow/runtime/template_resolver.py)

1. **`TemplateResolver.resolve(data, context)`** - Resolves ${variable} syntax

---

## Part 3: What CLI Currently Exposes

### Existing Commands

```bash
# Workflow Execution
pflow [WORKFLOW]...                    # Execute (file/name/NL)
pflow --trace                          # With trace
pflow --trace-planner                  # Planner trace

# Workflow Management
pflow workflow list                    # List saved workflows
pflow workflow describe NAME           # Show interface

# Registry
pflow registry list                    # List all nodes
pflow registry search TERM             # Search by name/description
pflow registry describe NODE_ID        # Show node details

# MCP
pflow mcp list/add                     # MCP server management
```

### What These Commands Do

1. **`pflow [WORKFLOW]`**: Invokes ENTIRE planner if NL - **agent can't control** node selection
2. **`pflow workflow list/describe`**: Shows saved workflows - **no semantic search**
3. **`pflow registry list/search`**: Simple keyword search - **no intelligent selection**
4. **`pflow registry describe NODE_ID`**: Shows single node - **must know ID already**

---

## Part 4: MISSING CLI Capabilities (The Gap)

### Critical Missing Functions

#### 1. **Intelligent Node Discovery**
- **What Planner Has**: ComponentBrowsingNode - LLM filters 50+ nodes → 3-5 relevant
- **What CLI Has**: `registry search` - keyword regex match
- **Gap**: Agents can't ask "what nodes do I need for X?"

#### 2. **Intelligent Workflow Discovery**
- **What Planner Has**: WorkflowDiscoveryNode - semantic matching
- **What CLI Has**: `workflow list` - shows all, no filtering
- **Gap**: Agents can't ask "what workflows exist for X?"

#### 3. **Template Validation**
- **What Planner Has**: ValidatorNode → TemplateValidator
- **What CLI Has**: Nothing (validation during execution only)
- **Gap**: Agents can't validate workflows BEFORE execution

#### 4. **IR Structure Validation**
- **What Planner Has**: ValidatorNode → validate_ir + validate_ir_structure
- **What CLI Has**: Nothing
- **Gap**: Agents can't check "is this IR valid?" pre-flight

#### 5. **Compilation Check**
- **What Planner Has**: ValidatorNode → compile_ir_to_flow
- **What CLI Has**: Nothing
- **Gap**: Agents can't test "will this compile?" before execution

#### 6-10. Other Missing Capabilities:
- Parameter extraction (ParameterMappingNode)
- Requirements analysis (RequirementsAnalysisNode)
- Feasibility planning (PlanningNode)
- Metadata generation (MetadataGenerationNode)
- Context building (build_*_context functions)

---

## Part 5: Specific Functions Agents Can't Access

### From Planning System

| Capability | Implementation | CLI Access |
|------------|----------------|------------|
| Intelligent node discovery | ComponentBrowsingNode.exec() | ❌ None |
| Intelligent workflow discovery | WorkflowDiscoveryNode.exec() | ❌ None |
| Parameter extraction (NL → values) | ParameterMappingNode.exec() | ❌ None |
| Parameter discovery (NL → names) | ParameterDiscoveryNode.exec() | ❌ None |
| Requirements analysis | RequirementsAnalysisNode.exec() | ❌ None |
| Feasibility planning | PlanningNode.exec() | ❌ None |
| IR generation | WorkflowGeneratorNode.exec() | ❌ None |
| Metadata generation | MetadataGenerationNode.exec() | ❌ None |
| Bulk node context | build_nodes_context() | ❌ None |
| Bulk workflow context | build_workflows_context() | ❌ None |

### From Runtime System

| Capability | Implementation | CLI Access |
|------------|----------------|------------|
| Template validation | TemplateValidator.validate_workflow_templates() | ❌ None |
| IR structure validation | validate_ir_structure() | ❌ None |
| IR schema validation | validate_ir() | ❌ None |
| Compilation check | compile_ir_to_flow() (validation mode) | ❌ None |

---

## Part 6: Prioritized Recommendations

### Tier 1: CRITICAL (Enables Basic Agent Workflow Building)

1. **`pflow discover-nodes QUERY`**
   - Reuses: ComponentBrowsingNode.exec()
   - Impact: Intelligent node discovery
   - Complexity: Medium (LLM integration)

2. **`pflow discover-workflows QUERY`**
   - Reuses: WorkflowDiscoveryNode.exec()
   - Impact: Semantic workflow matching
   - Complexity: Medium (LLM integration)

3. **`pflow validate-workflow FILE [--params JSON]`**
   - Reuses: ValidatorNode logic
   - Impact: Pre-flight validation
   - Complexity: Low (pure validation)

4. **`pflow workflow save FILE NAME DESC [--generate-metadata]`**
   - Reuses: WorkflowManager.save() + MetadataGenerationNode (if flag)
   - Impact: Save with rich metadata
   - Complexity: Low-Medium

### Tier 2: ENHANCES WORKFLOW

5. **`pflow build-context NODE_ID [NODE_ID...]`**
   - Reuses: build_nodes_context()
   - Impact: Bulk node details
   - Complexity: Low

6. **`pflow analyze-requirements QUERY`**
   - Reuses: RequirementsAnalysisNode.exec()
   - Impact: Complexity assessment
   - Complexity: Medium (LLM)

7. **`pflow check-feasibility QUERY`**
   - Reuses: RequirementsAnalysisNode + PlanningNode
   - Impact: Feasibility check
   - Complexity: High (multi-node)

### Tier 3: ADVANCED

8. **`pflow extract-parameters QUERY --workflow FILE`**
9. **`pflow generate-plan QUERY`**
10. **`pflow workflow describe NAME --json`** (enhancement)

---

## Part 7: Implementation Strategy

### Reusable Components

**High Reuse Potential** (>80%):
- discover-nodes ← ComponentBrowsingNode.exec()
- discover-workflows ← WorkflowDiscoveryNode.exec()
- validate-workflow ← ValidatorNode logic
- build-context ← build_*_context() functions

**Medium Reuse** (50-80%):
- analyze-requirements ← RequirementsAnalysisNode.exec()
- check-feasibility ← PlanningNode.exec()
- workflow save --generate-metadata ← MetadataGenerationNode.exec()

**Already Exists & Can Be Extracted**:
1. LLM call logic (shared across nodes)
2. Context building functions
3. Validation functions
4. Registry access patterns
5. WorkflowManager operations

---

## Conclusion

**The Gap**: Agents have **ZERO access** to planner's intelligent capabilities:
- List/search nodes/workflows (dumb keyword search only)
- Execute workflows (all-or-nothing, no control)
- Describe components (one at a time)

**What's Missing**: Entire **discovery, validation, and planning** infrastructure.

**Impact**: Agents **cannot build workflows intelligently** - blind to capabilities, no pre-flight validation, no feasibility checks.

**Solution**: Expose planner capabilities as CLI commands.
- **Tier 1** (4 commands) = Enable basic agent workflow building
- **Tier 2** (3 commands) = Better UX
- **Tier 3** (3 commands) = Advanced features

**Effort**: Most functionality exists, needs CLI wrappers + output formatting.

**Priority**: **Tier 1 is critical** - without it, agents cannot effectively discover, validate, or save workflows.
