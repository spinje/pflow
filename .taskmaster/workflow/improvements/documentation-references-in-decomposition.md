# Documentation References in Task Decomposition

## Why Documentation References Matter

When using `task-master expand`, the LLM generating subtasks has **ONLY** the decomposition plan file as context. Without explicit documentation references, it cannot know:

1. **Project Conventions**: How pflow structures its code, naming patterns, architectural decisions
2. **Framework Patterns**: How PocketFlow nodes work, lifecycle methods, shared store usage
3. **Existing Solutions**: What patterns are already established in cookbook examples
4. **Architectural Constraints**: What rules must be followed for consistency

## The Context Gap Problem

### Without Documentation References:
```
LLM sees: "Create node for file processing"
LLM generates: Generic subtask with no knowledge of pflow patterns
Result: Subtasks that don't align with project architecture
```

### With Documentation References:
```
LLM sees: "Create node for file processing
- Follow pflow pattern from docs/features/simple-nodes.md
- Use PocketFlow lifecycle from pocketflow/docs/core_abstraction/node.md
- Adapt pattern from pocketflow/cookbook/batch-file-processor/"

LLM generates: Subtask that specifically mentions these docs and patterns
Result: Subtasks that maintain architectural consistency
```

## Required Documentation Sections

### 1. Relevant pflow Documentation (ALWAYS include)
- Project-specific patterns from `docs/`
- Architecture decisions that affect the task
- Feature specifications that guide implementation

### 2. Relevant PocketFlow Documentation (if using framework)
- Core abstractions (Node, Flow, Shared Store)
- Design patterns applicable to the task
- Framework constraints and conventions

### 3. Relevant PocketFlow Examples (if not in research)
- Cookbook patterns that can be adapted
- Specific examples that demonstrate needed functionality
- Code organization patterns to follow

## Impact on Generated Subtasks

With proper documentation references, generated subtasks will:
- Reference specific docs in their descriptions
- Include implementation notes aligned with project patterns
- Maintain consistency with established architecture
- Avoid reinventing existing solutions
- Follow the principle of "build on what exists"

## Example References in Decomposition Plan

```markdown
## Relevant pflow Documentation

- `docs/features/cli-runtime.md` - Shared store patterns
  - Relevance: All nodes must follow store conventions
  - Key concepts: Store initialization, key naming
  - Applies to subtasks: 2, 3 (node implementation)

## Relevant PocketFlow Documentation

- `pocketflow/docs/core_abstraction/node.md` - Node lifecycle
  - Pattern: prep() -> exec() -> post() phases
  - Usage: All custom nodes in subtasks 2-4

## Relevant PocketFlow Examples

- `pocketflow/cookbook/rag-wiki-simple/` - RAG pattern
  - Adaptation: Replace wiki with our data source
  - Applies to: Subtask 3 search implementation
```

## Best Practices

1. **Be Specific**: Don't just list files - explain which sections and concepts apply
2. **Map to Subtasks**: Clearly indicate which subtasks should use which documentation
3. **Highlight Patterns**: Call out specific patterns or conventions to follow
4. **Include Adaptations**: Note how examples need to be modified for the current task

## The Compound Effect

When documentation is properly referenced:
- First task: Establishes pattern of following docs
- Later tasks: Build on established patterns
- Overall result: Coherent, consistent codebase

Without documentation references:
- Each task reinvents approaches
- Inconsistent implementations
- Technical debt accumulates

---

*Remember: The decomposition plan is the bridge between understanding and implementation. Documentation references are the guardrails that keep implementations on the right path.*
