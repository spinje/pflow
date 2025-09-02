Improve planner

1. The planner needs to make a "plan" before writing the json ir

2. The planner needs to define requirements before starting to write the json ir
This could include:
    - How many nodes are needed
    - Required node types that should be used
    - The order of the nodes? (might be to strict, im not sure about this)
    - How many sub workflows are needed (sub workflows are not yet supported but these could be defined as an entry to the json schema with a detailed "prompt" for the sub workflow with clear requirements)
    - Anything else?

This will be used in the validator to validate these "dynamic" validation criteria

## Implementation Insights (Added During Discussion)

### Why Requirements and Planning Steps are Critical

The planner is generating structured JSON, which is essentially code. Just like modern AI coding assistants (Claude, Cursor, GitHub Copilot), having explicit requirements and planning steps before implementation dramatically improves output quality.

**Evidence from pflow development:**
- When AI agents working on pflow tasks use requirements + planning, implementation success rate is much higher
- Requirements catch missing context before expensive generation
- Planning prevents architectural mistakes that cascade through the pipeline

### Proposed Pipeline Enhancement

**Current 9-stage pipeline:**
discovery → browsing → parameter-discovery → generator → parameter-mapping → validation → metadata → param-prep → result-prep

**Proposed 11-stage pipeline:**
discovery → browsing → **requirements** → **planning** → parameter-discovery → generator → parameter-mapping → validation → metadata → param-prep → result-prep

### What Each New Step Would Do

**Requirements Step:**
- Extract ALL explicit and implied requirements from user input
- Enumerate constraints and edge cases
- Define clear success criteria
- Output: Structured list of requirements the workflow must meet

**Planning Step:**
- Design the workflow structure before implementation
- Decide on specific nodes and their ordering
- Plan data flow between nodes
- Consider error handling approach
- Output: High-level plan that generator will implement

### Expected Benefits

1. **Higher first-time success rate** - Less likely to miss requirements
2. **Better error messages** - Can trace failures back to specific unmet requirements
3. **Improved test coverage** - Requirements become test cases
4. **More maintainable** - Clear separation between "what" (requirements) and "how" (plan/implementation)

### Cost Analysis

- **Additional cost**: ~$0.001-0.002 per workflow (2 more LLM calls)
- **Benefit**: Reduces failed generation attempts and retries
- **ROI**: Since workflows run forever after compilation, the marginal cost is negligible

### Implementation Priority

This could be implemented either:
1. **v0.1**: If current success rate is <90% on complex workflows
2. **v0.2**: If current success rate is acceptable, ship first and enhance based on user feedback

The decision depends on current planner reliability metrics and user tolerance for retry attempts.