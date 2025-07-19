# Task 17: Natural Language Planner - Context and Implementation Details

This document synthesizes key insights from research files to provide actionable implementation guidance for the Natural Language Planner System. It complements the ambiguities document by providing concrete architectural decisions and implementation patterns.

## 1. Architectural Decision: PocketFlow for Planner Orchestration

### Core Decision
The Natural Language Planner is the **ONLY** component in the entire pflow system that uses PocketFlow for internal orchestration. This decision is based on the planner's unique complexity requirements.

### Justification for PocketFlow Usage
The planner genuinely benefits from PocketFlow's orchestration capabilities due to:
- **Complex retry strategies** with multiple approaches
- **Self-correcting loops** for LLM validation and error recovery
- **Branching logic** based on LLM responses and validation outcomes
- **Progressive enhancement** of generated workflows
- **Multiple fallback paths** for different error types
- **State accumulation** across retry attempts

### Implementation Pattern
```python
# The planner uses PocketFlow internally
class DiscoveryNode(Node):
    """Uses context builder to find available components"""

class GeneratorNode(Node):
    """Generates workflow using LLM with retries"""

class ValidatorNode(Node):
    """Three-tier validation with error feedback"""

class ApprovalNode(Node):
    """Shows CLI syntax for user approval"""

# Orchestrated as a flow
discovery >> generator >> validator >> approval
generator - "malformed_json" >> generator  # Self-retry
validator - "unknown_nodes" >> error_feedback >> generator
```

### What This Means for Implementation
1. **All other components use traditional Python** - No PocketFlow elsewhere
2. **Planner gets retry/fallback benefits** - Built-in fault tolerance
3. **Clear architectural boundary** - Only planner uses flow patterns internally

## 2. Directory Structure Decision

### ✅ RESOLVED
Use `src/pflow/planning/` for the planner implementation.

**Rationale**:
- Maintains consistency with existing module structure (`src/pflow/nodes/` for CLI nodes)
- Aligns with the ambiguities document specification
- Preserves `src/pflow/flows/` for potential future use for packaged pflow CLI workflows (not user-generated)
- Follows the established pattern of organizing by functionality rather than implementation detail

**Implementation Structure**:
```
src/pflow/planning/
├── __init__.py       # Module exports
├── nodes.py          # Planner nodes (discovery, generator, validator, approval)
├── flow.py           # create_planner_flow() - orchestrates the nodes
├── ir_models.py      # Pydantic models for IR generation
├── utils/            # Helper utilities
└── prompts/
    └── templates.py  # Prompt templates
```

## 3. Complex Orchestration Patterns

### Retry Strategies
The planner must implement sophisticated retry logic:
1. **Malformed JSON** → Add format example to prompt (max 2 retries)
2. **Unknown nodes** → Suggest similar nodes from registry (max 3 retries)
3. **Missing data flow** → Add hint about node outputs (max 3 retries)
4. **Template unresolved** → Show available variables (max 2 retries)
5. **Circular dependency** → Simplify to sequential flow (max 1 retry)

### Self-Correcting Loops
```python
# Conceptual flow with PocketFlow
generator_node = WorkflowGeneratorNode(max_retries=3)
validator_node = ValidatorNode()

# Self-correcting pattern
flow = generator_node >> validator_node
validator_node - "validation_failed" >> generator_node
```

### Progressive Enhancement
Each retry attempt should:
1. Preserve what worked from previous attempt
2. Add specific corrections based on error type
3. Accumulate context about what's been tried
4. Adjust prompt strategy based on failure pattern

## 4. Integration Points and Dependencies

### Critical Dependencies
1. **Context Builder** (Task 15/16) - Provides discovery and planning contexts
2. **JSON IR Schema** - Defines valid workflow structure
3. **Node Registry** - Source of available components
4. **LLM Library** - Simon Willison's `llm` with structured outputs

### Integration Requirements
1. **CLI Integration**: Planner receives raw input string from CLI
2. **Workflow Storage**: Saves to `~/.pflow/workflows/` with template variables
3. **Runtime Handoff**: Generates validated JSON IR for execution
4. **Error Reporting**: Clear, actionable error messages

## 5. Risk Mitigation Strategies

### Hybrid Architecture Risk
**Risk**: Confusion about why only planner uses PocketFlow
**Mitigation**:
- Clear documentation in module docstring
- Explicit comments explaining the architectural decision
- Consistent pattern within the planner module

### Complex State Management
**Risk**: Difficult to track state across retries
**Mitigation**:
- Use PocketFlow's shared dict for retry context
- Clear logging of each attempt
- Preserve successful partial results

### LLM Non-Determinism
**Risk**: Different outputs for same input
**Mitigation**:
- Structured output with Pydantic schemas
- Three-tier validation pipeline
- Clear success criteria (≥95% accuracy target)

## 6. Key Implementation Principles

### From Research Analysis
1. **Focused Complexity** - PocketFlow only where it truly adds value
2. **Clear Boundaries** - Planner is special, everything else is traditional
3. **Selective Dogfooding** - Validates PocketFlow for its best use case

### Decision Criteria for Future Changes
Use PocketFlow when a component has:
- Complex retry strategies with multiple approaches
- Self-correcting loops (e.g., LLM validation)
- Genuinely complex branching logic
- Multiple interdependent external API calls
- Benefits from visual flow representation

Use traditional code for everything else.

## 7. Open Questions and Decisions Needed

1. ~~**Directory Structure**: Which path to use?~~ **RESOLVED**: Use `src/pflow/planning/`
2. **Approval Node Placement**: Is approval part of the planner flow or separate?
3. **Error Feedback Node**: Should this be a separate node or part of validator?

## Next Steps

With the directory structure resolved, the implementation should:
1. Create the planner module at `src/pflow/planning/` with PocketFlow patterns
2. Implement the four core nodes (discovery, generator, validator, approval)
3. Wire up retry logic and error recovery paths
4. Integrate with existing context builder and CLI

---

*Note: This document will be updated as additional research files are analyzed and integrated.*
