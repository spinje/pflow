---
description: Refine a subtask before implementation using epistemic workflow
allowed-tools: Bash(task-master show:*), Bash(task-master update-subtask:*), Read, Write, Edit
---

Refine subtask $ARGUMENTS using the epistemic refinement workflow.

**CRITICAL**: Read and follow the complete workflow in `.taskmaster/workflow/refine-subtask.md`

This workflow has 2 phases:
- Phase 0: Knowledge Loading (synthesize relevant learnings)
- Phase 1: Refinement (resolve ambiguities)

Key files you'll create in `.taskmaster/tasks/task_X/subtask_$ARGUMENTS/refinement/`:
- `knowledge-synthesis.md`
- `evaluation.md`
- `refined-spec.md`
- Create marker: `ready-for-implementation`

Always READ the project context from parent task first!
