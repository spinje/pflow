# Cookbook Patterns for Subtask 6.3

## Relevant PocketFlow Patterns

### 1. **pocketflow-flow**: Interactive Flow with Action-Based Routing
- **Relevance**: Shows how to represent conditional workflows in IR
- **Key Insight**: Action strings enable dynamic flow control
- **Adaptation**: Create IR example with menu-driven workflow using action-based edges

### 2. **pocketflow-workflow**: Multi-Stage Sequential Processing
- **Relevance**: Demonstrates pipeline pattern common in pflow
- **Key Insight**: Clean data flow through shared store keys
- **Adaptation**: Create IR example of content generation pipeline

### 3. **pocketflow-text2sql**: Error Handling with Retry Loop
- **Relevance**: Shows error recovery patterns
- **Key Insight**: Action-based routing for error handling
- **Adaptation**: Create IR example with error handling and retry logic

## Patterns to Demonstrate in Examples

### From Cookbook Analysis:
1. **Sequential Pipeline**: nodes connected in order (workflow pattern)
2. **Conditional Routing**: action-based edges for decisions (flow pattern)
3. **Error Recovery**: error action routes with retry limits (text2sql pattern)
4. **User Interaction**: loops with user-driven actions (flow pattern)

### From Documentation Analysis:
1. **Template Variables**: $variable syntax in params
2. **Proxy Mappings**: Input/output key transformations
3. **Complex Workflows**: Multi-branch, parallel paths
4. **Real-World Flows**: GitHub automation, CI/CD, content generation

## Example Categories to Create

### Core Examples (MVP Priority):
1. **hello-world.json**: Minimal single-node example
2. **simple-pipeline.json**: 3-node sequential flow (read → process → write)
3. **template-variables.json**: Using $variables in node params
4. **error-handling.json**: Try-catch pattern with action routing
5. **proxy-mappings.json**: Node interface adaptation example

### Advanced Examples (Demonstrate Power):
1. **github-automation.json**: Real-world GitHub issue workflow
2. **content-pipeline.json**: Multi-stage content generation
3. **conditional-flow.json**: Decision tree with multiple paths

## Documentation Patterns to Follow

### From Successful Examples:
1. **Clear Purpose Statement**: What the workflow accomplishes
2. **Visual Representation**: ASCII or diagram of flow
3. **Step-by-Step Explanation**: What each node does
4. **Variations**: How to modify for different use cases
5. **Common Errors**: What mistakes to avoid

### Structure for Each Example:
```
examples/
├── core/
│   ├── hello-world.json
│   ├── hello-world.md         # Explanation
│   ├── simple-pipeline.json
│   ├── simple-pipeline.md
│   └── ...
├── advanced/
│   ├── github-automation.json
│   ├── github-automation.md
│   └── ...
└── README.md                  # Example index and guide
```
