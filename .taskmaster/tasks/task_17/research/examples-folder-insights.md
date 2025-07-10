# Examples Folder: Hidden Gems for the Planner

The `examples/` folder contains JSON IR examples that show exactly what the Natural Language Planner needs to generate. Think of it as your target output reference.

## Why Look Here?

The planner's job is to transform natural language into JSON IR. These examples show all the patterns you'll need to generate.

## Key Resources

### Core Patterns
- [`examples/core/minimal.json`](../../../../examples/core/minimal.json) - Simplest valid output
- [`examples/core/simple-pipeline.json`](../../../../examples/core/simple-pipeline.json) - Basic node chaining
- [`examples/core/template-variables.json`](../../../../examples/core/template-variables.json) - **Critical**: Shows `$variable` syntax the planner must generate

### Advanced Patterns
- [`examples/advanced/github-workflow.json`](../../../../examples/advanced/github-workflow.json) - Complex real-world workflow with error paths
- [`examples/advanced/content-pipeline.json`](../../../../examples/advanced/content-pipeline.json) - Revision loops and conditional flows

### What NOT to Generate
- [`examples/invalid/`](../../../../examples/invalid/) - Common mistakes to avoid

## Hidden Insights

1. **Template Variables Everywhere**: Notice how `$variable` appears in params, prompts, and data fields
2. **Error Handling Pattern**: Look at `"action": "error"` edges in github-workflow
3. **Node Types**: The examples use node types that must exist in the registry
4. **Start Node**: Default is first node, but can be overridden

## The Planner's Target

When the planner receives "fix github issue 1234", it should generate something similar to `github-workflow.json`, with appropriate template variables for dynamic content.

Remember: The planner doesn't execute these - it just needs to generate valid IR that matches these patterns.

See also:
- [`examples/README.md`](../../../../examples/README.md) - Explains all patterns
- [`registry_demo.py`](../../../../examples/registry_demo.py) - Shows available node types
