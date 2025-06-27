---
description: Refine and decompose a main task using the epistemic workflow
allowed-tools: Bash(task-master show:*), Bash(task-master update-task:*), Bash(task-master expand:*), Bash(task-master update-subtask:*), Task, Read, Write, Edit
---

Follow the epistemic task decomposition workflow for task $ARGUMENTS.

**CRITICAL**: Read and follow the complete workflow in `.taskmaster/workflow/refine-task.md`

This workflow has 4 phases:
- Phase 0: Task Understanding (create project context)
- Phase 1: Task Refinement (clarify requirements)
- Phase 2: Subtask Generation (decompose intelligently)
- Phase 3: Subtask Refinement (ensure clarity)

Key files you'll create:
- `.taskmaster/tasks/task_$ARGUMENTS/project-context.md`
- Update to `.taskmaster/reports/task-complexity-report.json`

Remember: Deep understanding drives good decomposition. Don't skip Phase 0!
