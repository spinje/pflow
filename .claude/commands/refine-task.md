---
description: Refine and decompose a main task using the epistemic workflow
allowed-tools: Bash(task-master show:*), Bash(task-master update-task:*), Bash(task-master expand:*), Bash(task-master update-subtask:*), Task, Read, Write, Edit
---

Follow the epistemic task decomposition workflow for task $ARGUMENTS.

**FOUNDATION** (required reading in order):
1. **Mindset**: Read `.taskmaster/workflow/epistemic-manifesto.md` to understand the epistemic approach
2. **System**: Read `.taskmaster/workflow/workflow-overview.md` to see how all workflows connect
3. **Execution**: Read and follow `.taskmaster/workflow/refine-task.md` for specific steps

This reading order ensures you understand WHY before learning HOW.

**Returning users**: If you've already internalized the epistemic approach, jump directly to `.taskmaster/workflow/refine-task.md`

**YOUR POSITION in the workflow:**
You are at the BEGINNING of the epistemic workflow (see diagram in workflow-overview.md):
- **You handle**: Main Task → Task Understanding → Task Refinement → Subtask Generation → Subtask Validation
- **Prerequisites**: A task ID exists in task-master
- **Your output enables**: Subtask refinement and implementation by other agents (see workflow-overview.md)

Key outputs:
- `.taskmaster/tasks/task_$ARGUMENTS/project-context.md`
- Update to `.taskmaster/reports/task-complexity-report.json`

Remember: Deep understanding drives good decomposition. Don't skip Phase 0!
