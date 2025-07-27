# Natural Language Planner - Core Insights

## The "Find or Build" Pattern

The Natural Language Planner is THE core innovation of pflow. It implements a unified interface where the same command either finds an existing workflow or builds a new one:

```bash
pflow "analyze customer churn"
# → Found 'analyze-churn'. Running...
# OR
# → No workflow found. Creating...
```

This pattern is fundamentally different from any existing tool because it:
1. Removes the friction between "do I have this?" and "let me build this"
2. Makes discovery and creation seamless in the same interface
3. Allows users to build their library naturally as they work
4. Provides a universal automation interface

## Key Design Decisions

### 1. Semantic Discovery, Not String Matching

The planner MUST implement semantic similarity matching, not just fuzzy string matching:
- "analyze costs" should find "aws-cost-analyzer"
- "check production errors" should find "production-error-analysis"
- Uses LLM embeddings or similarity scoring
- Returns ranked list of potential matches

### 2. Parameter Flexibility is Core

Workflows are NOT static - they're parameterized templates:
```bash
pflow "analyze churn for last month"
pflow "analyze churn for enterprise customers since January"
```

The planner must:
- Extract parameters from natural language
- Map them to workflow template variables
- Support both positional and named parameters
- Handle missing parameters gracefully

### 3. Template Variables Enable Reuse

Workflows use template variables like `$issue_data`, `$customer_segment`:
- Variables are resolved at runtime, not compile time
- Enables the same workflow to handle different inputs
- Planner generates appropriate template variables
- Simple regex-based substitution (not a full templating engine)

## Integration Philosophy

### With Shared Store
- The planner understands shared store conventions
- Generates workflows that use natural keys
- Knows which data flows between nodes
- Can suggest proxy mappings when needed

### With Registry
- Uses registry metadata to understand available nodes
- Knows node inputs/outputs from metadata
- Builds context for LLM from registry
- Validates generated workflows against registry

### With CLI
- Receives raw input string from CLI
- Can interpret both natural language and CLI syntax
- Returns to CLI for approval flow
- Saves approved workflows for reuse

## Critical Success Factors

1. **≥95% Success Rate**: Natural language to workflow generation must be highly reliable
2. **≥90% Approval Rate**: Generated workflows should require minimal modification
3. **Fast Discovery**: Finding existing workflows must be near-instant
4. **Clear Approval**: Users must understand what workflow will do before execution

## Common Pitfalls to Avoid

1. **Over-engineering the matching**: Start with simple semantic similarity
2. **Making workflows too rigid**: Always design for parameter flexibility
3. **Hiding the generation**: Show users the generated workflow for trust
4. **Forgetting about discovery**: Build and find are equally important
5. **Complex template syntax**: Keep it simple - just $variable

## Implementation Order

1. Start with workflow generation (natural language → IR)
2. Add template variable support
3. Implement approval and storage
4. Add discovery last (can iterate on matching algorithm)

## The Mental Model

Think of the planner as a **compiler for natural language**:
- Input: User intent in natural language
- Parsing: Understanding nodes and connections
- Optimization: Finding existing workflows
- Code Generation: Creating new workflows
- Output: Executable workflow (JSON IR)

## Remember

The planner is what makes pflow magical. Without it, pflow is just another workflow engine. With it, pflow becomes an intelligent automation interface that learns and grows with use.
