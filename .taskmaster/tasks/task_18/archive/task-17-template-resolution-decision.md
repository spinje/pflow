# Task 17: Template Variable Resolution - Implementation Decision

**Date**: 2025-01-19
**Subject**: Template Variable Implementation via Proxy Pattern
**Decision**: Implement runtime proxy for transparent template resolution

## Problem
- Documentation describes `template_inputs` and `variable_flow` fields that don't exist in IR schema
- Need template variables for "Plan Once, Run Forever" without modifying nodes or PocketFlow

## Solution: Runtime Proxy Pattern

### How It Works
```python
# Workflow contains templates in params
{"type": "llm", "params": {"prompt": "Fix issue: $issue_data"}}

# Runtime wraps node in proxy
node = TemplateResolvingNodeProxy(original_node, template_params)

# During execution, proxy resolves templates transparently
# Node sees: {"prompt": "Fix issue: [actual issue content]"}
# Node remains completely unaware of templates
```

### Two Types of Variables
1. **CLI Parameters**: `$issue_number` → resolved from `--issue_number=1234`
2. **Shared Store**: `$issue_data` → resolved from `shared["issue_data"]`

### Implementation
- Create `TemplateResolvingNodeProxy` in pflow runtime (not PocketFlow)
- Wrap nodes during compilation when templates detected
- Proxy intercepts `_run()` to resolve templates just-in-time
- Works alongside existing `NodeAwareSharedStore` proxy

### Key Benefits
- **Nodes stay atomic** - No template awareness needed
- **No framework changes** - PocketFlow remains pure
- **Proven pattern** - Same approach as existing proxy mapping
- **Clean layers** - Template logic isolated in runtime

### Example Flow
```
User: "fix github issue 1234"
Planner: generates params with $issue_number and $issue_data
Runtime: CLI params → {"issue_number": "1234"}
Node 1: proxy resolves $issue_number → "1234", writes shared["issue_data"]
Node 2: proxy resolves $issue_data → actual issue content
Result: Workflow executes with all templates resolved transparently
```

## Decision
Implement template resolution via runtime proxy pattern for MVP. This enables workflow reusability without architectural changes.
