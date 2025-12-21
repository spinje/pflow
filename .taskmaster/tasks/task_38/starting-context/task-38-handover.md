# Task 38 Handover Memo: Support Branching in Generated Workflows

**From**: Previous agent (context window closing)
**To**: Implementing agent
**Date**: 2024-12-21

---

## 🚨 The Most Important Thing You Need to Know

**The runtime ALREADY supports conditional branching.** This task is NOT about implementing branching - it's about ENABLING the planner to generate it and fixing documentation conflicts.

```python
# src/pflow/runtime/compiler.py:831-834 - THIS ALREADY WORKS
if action == "default":
    source >> target
else:
    source - action >> target  # Conditional routing WORKS
```

**Your actual work is:**
1. Remove "Linear execution only" from planner prompts
2. Add branching examples to prompts
3. Update conflicting documentation
4. Add tests that verify branching execution

---

## 🔑 Critical Context from This Session

### The Three Types of "Parallelism" - MUST UNDERSTAND

During this session, we deeply analyzed three related but DIFFERENT features:

| Feature | Task | What It Is | PocketFlow Support |
|---------|------|------------|-------------------|
| **Conditional Branching** | 38 (this) | ONE path executes based on action | ✅ Already works |
| **Data Parallelism** | 96 | Same op × N items concurrently | ✅ BatchNode exists |
| **Task Parallelism** | 39 | Different ops execute concurrently | ❌ Must build |

```
CONDITIONAL BRANCHING (Task 38 - this task):
validate → (error OR success OR retry)
           └── only ONE path executes ──┘

TASK PARALLELISM (Task 39 - different task):
fetch → [analyze AND visualize AND summarize] → combine
        └─── ALL paths execute concurrently ────┘
```

**Task 38 is about conditional branching (state machine pattern), NOT parallel execution.**

### The Research is ACCURATE

Unlike Task 39's research (which had inaccuracies we had to archive), Task 38's research is solid:
- `branching-deep-dive.md` correctly distinguishes Type 1 (parallel) from Type 2 (conditional)
- The task spec correctly identifies what needs to be done
- No misleading "blocker" claims

---

## 📍 Verified Working Code

### Runtime Support (Already Implemented)

**Compiler** (`src/pflow/runtime/compiler.py:831-834`):
```python
# Wire the nodes based on action
if action == "default":
    source >> target
else:
    source - action >> target
```

**IR Schema** (`src/pflow/core/ir_schema.py:158-162`):
```python
"action": {
    "type": "string",
    "description": "Action string for conditional routing",
    "default": "default"
}
```

**Working Example**: `examples/core/error-handling.json` demonstrates branching.

**Passing Tests**:
- `tests/test_runtime/test_compiler_integration.py::test_branching_flow_with_success_path`
- `tests/test_runtime/test_compiler_integration.py::test_branching_flow_with_failure_path`

---

## 🎯 What You Actually Need to Do

### Phase 1: Update Planner Prompts

**File to modify**: `src/pflow/planning/prompts/workflow_generator_instructions.md`

The task spec says line 189 has:
```
- Linear execution only (no branching)
```

You need to:
1. Remove this restriction
2. Add a section explaining conditional branching
3. Add examples showing proper edge syntax with actions

**Example to add**:
```json
{
  "edges": [
    {"from": "validate", "to": "process", "action": "default"},
    {"from": "validate", "to": "retry", "action": "retry"},
    {"from": "validate", "to": "error_log", "action": "error"}
  ]
}
```

### Phase 2: Fix Documentation Conflicts

**Files with conflicts**:

| File | Current State | Should Be |
|------|---------------|-----------|
| `CLAUDE.md:98` | "Excluded from MVP: Conditional transitions" | REMOVE this line |
| `CLAUDE.md:143` | "action-based transitions" | Keep (correct) |
| `architecture/features/mvp-implementation-guide.md:480` | "No branching in MVP" | Update |

### Phase 3: Add Tests

The current tests compile branching workflows but don't fully verify execution paths. You need:
1. Tests that verify WHICH path was taken based on action
2. Tests for error handling patterns
3. Planner tests that verify the LLM generates branching appropriately

---

## ⚠️ Gotchas and Warnings

### 1. Don't Confuse Conditional with Parallel

```python
# This is CONDITIONAL branching (Task 38) - WORKS
node - "error" >> error_handler
node - "success" >> continue

# This is PARALLEL fan-out (Task 39) - DOESN'T WORK in PocketFlow
node >> analyze
node >> visualize  # OVERWRITES previous edge!
```

PocketFlow only stores ONE successor per action. Multiple edges with same action = last one wins.

### 2. The "30% Branching" Statistic

The task spec says LLMs create branching in ~30% of complex workflows. This is DIFFERENT from the 40% figure for Task 39:
- 30%: LLMs naturally want conditional branching (error handling, retries)
- 40%: LLMs naturally want parallel fan-out (different operations)

### 3. Action String Conventions

Document these common patterns:
- `"default"` - Normal flow continuation
- `"error"` - Error handling path
- `"retry"` - Retry logic
- `"success"` / `"failure"` - Binary outcomes
- Custom actions from specific nodes

---

## 📚 Files to Read

| File | Why |
|------|-----|
| `.taskmaster/tasks/task_38/task-38.md` | Full task specification |
| `.taskmaster/tasks/task_38/research/branching-deep-dive.md` | Excellent research on two types of branching |
| `examples/core/error-handling.json` | Working branching example |
| `src/pflow/planning/prompts/workflow_generator_instructions.md` | Where the restriction likely is |

---

## 🔗 Relationship to Tasks 96 and 39

These three tasks are complementary:

```json
{
  "pipeline": [
    {"id": "fetch_files", "type": "http"},

    {
      "id": "process_all",
      "batch": {"items": "${fetch_files.files}", "parallel": true},  // Task 96
      "type": "llm"
    },

    {
      "parallel": [                                                   // Task 39
        {"id": "analyze", "type": "llm"},
        {"id": "visualize", "type": "llm"}
      ]
    },

    {
      "id": "review",
      "type": "llm",
      "next": {                                                       // Task 38
        "approved": "publish",
        "rejected": "archive"
      }
    }
  ]
}
```

**Order recommendation**:
1. Task 96 (batch) - Uses existing PocketFlow, highest impact
2. Task 38 (this) - Low effort, runtime already works
3. Task 39 (parallel) - Most complex, needs custom implementation

---

## 💡 Final Advice

1. **This is a LOW EFFORT task** - The spec estimates 2-4 hours
2. **Don't overthink it** - The runtime works, you're just enabling the planner
3. **Focus on prompts and docs** - That's where the real work is
4. **Add good examples** - The LLM needs to see proper branching patterns
5. **Test the planner** - Verify it generates branching for appropriate requests

---

## ⏸️ STOP - Do Not Begin Yet

Read the task specification at `.taskmaster/tasks/task_38/task-38.md` and the research at `.taskmaster/tasks/task_38/research/branching-deep-dive.md` before starting.

When you're ready, tell the user: **"I've read the handover and task specification. I'm ready to begin implementing Task 38."**
