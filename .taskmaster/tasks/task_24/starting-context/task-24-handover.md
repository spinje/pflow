# Task 24 (WorkflowManager) Handover Memo

## 🚨 Critical Discovery: This Isn't What You Think It Is

WorkflowManager started as a simple name-to-path resolver for Task 17 (Natural Language Planner). **It's now revealed as essential infrastructure** that must solve THREE fundamental problems:

1. **No workflow saving exists** - The entire "Plan Once, Run Forever" philosophy is blocked
2. **Format mismatch between components** - Workflows can't move between Context Builder and WorkflowExecutor
3. **Name vs path impedance** - The planner thinks in names, runtime thinks in file paths

## 🔥 The Format Mismatch That Changes Everything

Task 21's implementation exposed a critical inconsistency:

```python
# Context Builder expects (and _load_saved_workflows validates for):
{
    "name": "fix-issue",
    "description": "Fixes GitHub issues",
    "ir": {
        "ir_version": "0.1.0",
        "inputs": {...},    # Task 21's new rich schemas
        "outputs": {...},   # Task 21's new rich schemas
        "nodes": [...],
        "edges": [...]
    }
}

# WorkflowExecutor expects (both for files AND inline):
{
    "ir_version": "0.1.0",
    "inputs": {...},
    "outputs": {...},
    "nodes": [...],
    "edges": [...]
}
```

**This means workflows saved in Context Builder format CAN'T be executed by WorkflowExecutor!**

See: `/scratchpads/task-17-implementation/task-21-impact-on-task-24.md`

## 🎯 What Task 17 (Planner) Desperately Needs

The planner is blocked without these capabilities:

1. **Structured workflow access after LLM selection**
   - Context builder provides markdown for LLM browsing
   - But planner needs the actual workflow object after selection
   - Currently `_load_saved_workflows()` is private!

2. **Name-based workflow references**
   ```json
   // Planner wants to generate:
   {"type": "workflow", "params": {"workflow_name": "fix-issue"}}

   // But WorkflowExecutor only accepts:
   {"type": "workflow", "params": {"workflow_ref": "./path/to/file.json"}}
   ```

3. **Workflow composition with Task 20**
   - Task 20 added WorkflowExecutor for nested workflows
   - But it's unusable without name resolution!

See: `/scratchpads/task-17-implementation/context-builder-gap-analysis.md`

## 🏗️ The Architecture You're Inheriting

### Scattered Workflow Loading (4 implementations!)
1. `context_builder._load_saved_workflows()` - For discovery, expects metadata wrapper
2. `workflow_executor._load_workflow_file()` - For execution, expects raw IR
3. `cli.read_workflow_from_file()` - Basic file reading
4. No save functionality anywhere!

### WorkflowExecutor's Design Assumptions
- Uses file paths, not names (`./sub-workflow.json`)
- Doesn't expand tilde (`~`) in paths
- Relative paths resolve from parent workflow location
- See examples in `/examples/nested/` for intended patterns

### Task 21's New World
- Workflows now have rich `inputs`/`outputs` schemas in the IR
- Types, descriptions, required flags, defaults
- Context Builder already updated to read from IR
- Compiler validates against these declarations

## ⚡ Critical Design Decisions

### 1. Storage Format (Choose Metadata Wrapper)
```python
# Store with metadata wrapper (Context Builder format):
{
    "name": "fix-issue",
    "description": "...",
    "ir": {...},
    "created_at": "...",
    "version": "1.0.0"
}

# But provide clean extraction:
def load_ir(name: str) -> dict:
    """Returns just the IR for WorkflowExecutor"""
    workflow = self.load(name)
    return workflow["ir"]
```

**Why**: Preserves identity, enables metadata, already expected by Context Builder

### 2. Name Resolution Strategy
The user pushed me to think about registry patterns. Consider:
- Option A: Minimal - just assume `~/.pflow/workflows/{name}.json`
- Option B: Better - maintain name→path mapping
- Option C: Best? - Follow registry pattern with proper lookups

See: `/scratchpads/task-17-implementation/workflow-reference-resolution.md`

### 3. API Surface
Must support both format needs:
```python
load(name) -> dict          # Full metadata for Context Builder
load_ir(name) -> dict       # Just IR for WorkflowExecutor
save(name, ir) -> str       # Wrap IR with metadata
get_path(name) -> str       # For components that need paths
list_all() -> List[dict]    # For discovery
```

## 🚧 Implementation Warnings

### Don't Trust The Examples
- Examples use raw IR format (no metadata wrapper)
- But Context Builder expects metadata wrapper
- WorkflowManager must bridge this gap

### The Tilde Trap
WorkflowExecutor doesn't expand `~` in paths. I initially suggested adding `os.path.expanduser()` as a quick fix. The user correctly pushed back - this is a symptom, not the disease. Focus on name resolution instead.

### Format Validation
Context Builder's `_validate_workflow_fields()` is strict:
- MUST have: `name`, `description`, `ir`
- Types must match exactly
- Will skip invalid files with warnings

### Missing Integration Points
1. CLI doesn't implement workflow saving after approval
2. No workflow management commands (list, delete, etc.)
3. WorkflowExecutor has no name resolution logic

## 🔗 Essential Code to Study

### For Format Understanding:
- `/src/pflow/planning/context_builder.py` - See `_load_saved_workflows()` for expected format
- `/src/pflow/runtime/workflow_executor.py` - See `_load_workflow_file()` for what it expects
- `/tests/test_planning/test_workflow_loading.py` - Tests show format expectations

### For Patterns to Follow:
- `/src/pflow/registry/registry.py` - How the node registry works (inspiration)
- `/src/pflow/core/ir_schema.py` - The new workflow schema with inputs/outputs

### Critical Docs:
- `/architecture/features/nested-workflows.md` - How workflow composition works
- `/.taskmaster/tasks/task_20/task-review.md` - WorkflowExecutor implementation
- `/.taskmaster/tasks/task_21/task-review.md` - Input/output declarations

## 💡 The Deeper Insight

The user's question "what about the registry, isn't there where you 'request' a workflow by name?" revealed the core issue. The system has a clean registry pattern for nodes but treats workflows as second-class citizens with file-based references.

WorkflowManager isn't just fixing a gap - it's establishing workflows as first-class entities with proper lifecycle management. Think of it as creating a "workflow registry" that parallels the node registry conceptually but serves a different purpose.

## ⚠️ What Will Break Without This

1. **Task 17 can't reference workflows** - Planner generates invalid JSON
2. **Workflows can't be saved** - "Plan Once, Run Forever" is impossible
3. **Components can't share workflows** - Format mismatch prevents interop
4. **Task 20's composition is unusable** - No way to reference sub-workflows by name

## 🎁 The Hidden Opportunity

Task 21's rich input/output schemas enable powerful new features:
- Find workflows by interface (what inputs/outputs they have)
- Validate workflow compatibility for composition
- Generate better documentation
- Enable semantic workflow search

Don't just implement the minimum - the foundation you lay here will determine how sophisticated workflow management can become.

## 📋 Your TODO After Reading This

1. Read the critical decision documents in `/scratchpads/task-17-implementation/critical-user-decisions/`
2. Study the format mismatch details in `/scratchpads/task-17-implementation/task-21-impact-on-task-24.md`
3. Understand why Context Builder needs public methods in `/scratchpads/task-17-implementation/context-builder-gap-analysis.md`
4. Look at the workflow examples in `/examples/nested/` to see file-based patterns
5. Check `_load_saved_workflows()` to understand the exact format expected

---

**DO NOT START IMPLEMENTING YET!** Read through all the linked documents, understand the architectural tensions, and confirm you grasp why this component evolved from "nice to have" to "essential infrastructure." When you're ready, simply state that you understand the critical issues and are ready to begin implementation.
