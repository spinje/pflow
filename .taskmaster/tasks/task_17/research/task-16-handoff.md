# Handoff Memo: From Task 16 (Context Builder) to Task 17 (Natural Language Planner)

**Context**: Task 16 (Create planning context builder) is complete. This memo transfers critical knowledge to the agent implementing Task 17 (Implement Natural Language Planner System).

## 🎯 Core Outcomes You're Building On

### What Task 16 Created

The context builder (`/Users/andfal/projects/pflow/src/pflow/planning/context_builder.py`) produces clean, LLM-optimized markdown that describes all available nodes:

```markdown
## File Operations

### read-file
Read content from a file and add line numbers for display.

**Inputs**: `file_path`, `encoding`
**Outputs**: `content`, `error` (error)
**Parameters**: none

### write-file
Write content to a file with automatic directory creation.

**Inputs**: `content`, `file_path`, `encoding`
**Outputs**: `written`, `error` (error)
**Parameters**: `append`
```

**Key characteristics**:
- Categories group related nodes (File Operations, Git Operations, etc.)
- Exclusive parameters only (configuration params, not data params)
- Clean, consistent format optimized for LLM parsing
- Actions mapped to outputs (e.g., `error` (error))

### The Exclusive Parameter Pattern (Critical!)

This is THE most important thing to understand:

```python
# In EVERY node's prep() method:
file_path = shared.get("file_path") or self.params.get("file_path")
```

**What this means for the planner**:
- ALL inputs can also be provided as parameters
- The context builder shows only "exclusive parameters" (params NOT in inputs)
- When generating workflows, the planner can set ANY input as a parameter

Example: Even though `file_path` is listed as an input, this is valid:
```json
{
  "type": "read-file",
  "params": {"file_path": "config.json"}  // Works! Falls back from shared store
}
```

## 🔍 Unexpected Discoveries and Edge Cases

### 1. Registry Contains Test Nodes

The registry includes test nodes that the context builder filters out. But if filtering logic changes, the planner might see nodes like `test-retry-node`. These should NEVER appear in generated workflows.

### 2. Import Failures Are Normal

During context building, many nodes fail to import due to missing dependencies. The context only includes successfully imported nodes. Your planner won't see broken nodes, but the available node set might be smaller than expected during development.

### 3. The Format Is Already Optimized

The current format matches what's in `docs/features/planner.md` Section 6.1. Don't try to parse a different format - use exactly what the context builder provides.

## 💡 Patterns to Reuse

### 1. Phased Processing Pattern

From Task 16 and Task 7, we use clear phases:
```python
# Phase 1: Parse/understand input
# Phase 2: Process/transform
# Phase 3: Format/output
# Phase 4: Validate/verify
```

This makes debugging much easier when things go wrong.

### 2. Graceful Degradation

When the planner can't understand something, don't crash. Generate a workflow that asks for clarification or provide the best guess with a warning.

### 3. The Context is Your Dictionary

The context builder output is the planner's "dictionary" of available tools. Treat it as the single source of truth for what nodes exist and how they work.

## ⚠️ Anti-Patterns to Avoid

### 1. Don't Hardcode Node Names

Always use the context to discover available nodes. Nodes might be added/removed/renamed.

### 2. Don't Parse Raw Docstrings

The context builder already extracts and formats everything. Use the clean markdown, not raw registry data.

### 3. Don't Assume Parameter Requirements

Just because a parameter isn't listed doesn't mean it can't be used. Remember: ALL inputs can be parameters too.

## 🐛 Subtle Issues and Caveats

### 1. Action String Complexity

Nodes can have multiple actions (`default`, `error`, `success`). The context shows which outputs correspond to which actions. The planner needs to handle branching workflows.

### 2. Optional Parameters in Context

Currently, the context doesn't distinguish between optional and required inputs. The planner might need to be forgiving about missing inputs and let nodes fail fast with clear errors.

### 3. Template Variables

The planner needs to generate template variables like `$issue_data` for data flow between nodes. These aren't in the context but are critical for workflow composition.

## 🔗 Critical Files and References

### Implementation Files
- **Context Builder**: `/Users/andfal/projects/pflow/src/pflow/planning/context_builder.py`
- **Tests**: `/Users/andfal/projects/pflow/tests/test_planning/test_context_builder.py`
- **Registry**: `/Users/andfal/projects/pflow/src/pflow/registry/registry.py`
- **Metadata Extractor**: `/Users/andfal/projects/pflow/src/pflow/registry/metadata_extractor.py`

### Documentation
- **Planner Spec**: `/Users/andfal/projects/pflow/docs/features/planner.md` (Section 6.1 shows expected format)
- **Workflow Analysis**: `/Users/andfal/projects/pflow/docs/features/workflow-analysis.md`
- **Strategic Vision**: `/Users/andfal/projects/pflow/.taskmaster/tasks/task_16/16-strategic-vision.md`

### Key Patterns
- **Exclusive Parameters**: `/Users/andfal/projects/pflow/.taskmaster/knowledge/patterns.md` (search for "Shared Store Inputs as Automatic Parameter Fallbacks")

## 📊 Performance Considerations

The context builder takes ~50-100ms to build context for 5-10 nodes. For 50+ nodes, it might take 500ms+. The planner should:
1. Cache the context between planning requests
2. Only rebuild when the registry changes
3. Consider context size in prompt token usage

## 🎨 Interface Contract

The planner will call the context builder like this:
```python
from pflow.registry import Registry
from pflow.planning.context_builder import build_context

registry = Registry()
registry_data = registry.load()
context = build_context(registry_data)  # This is your node dictionary
```

The context is a string, not structured data. Parse it as markdown if needed, but it's designed for direct LLM consumption.

## 🚀 What Would Make Me Furious If I Forgot

1. **The exclusive parameter pattern** - This is subtle but critical. ALL inputs can be params.

2. **The context builder already handles test node filtering** - Don't filter again in the planner.

3. **Actions map to outputs** - The format `error` (error) means the error output corresponds to the error action. This is how you build error handling flows.

4. **Categories are already logical** - Don't reorganize. Use the grouping as-is.

5. **The 5x cost multiplier** - Bad context led to 5x more LLM calls. The context builder solves this. Don't break it.

## 💭 Strategic Context for Task 17

From the strategic vision, the planner is THE core feature that makes pflow unique. The context builder was built specifically to enable 95% success rate for natural language → workflow generation.

The context format is optimized for:
- Node discovery ("find the right tool")
- Parameter understanding ("what inputs does it need")
- Connection inference ("what outputs can feed what inputs")
- Category browsing ("what file operations are available")

Use this format as designed. It's the result of solving the exact problems the planner faces.

## 🎯 Your Mission

Transform natural language like "fix github issue 123" into workflows using the context as your tool dictionary. The context builder gives you everything needed to understand what tools are available. Now make them discoverable through natural language.

Remember: The better you use the context, the fewer retries users experience. That's the difference between a tool they love and one they abandon.
