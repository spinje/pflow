# Pitfalls to Avoid

A consolidated collection of failed approaches, anti-patterns, and mistakes discovered during task implementations. Learning from these failures prevents future repetition.

**Before adding**: Read this entire file and search for related pitfalls to avoid duplicates.

---

## Pitfall: Direct task-master Updates During Implementation
- **Date**: 2024-01-15
- **Discovered in**: Task 2.1 (Example)
- **What we tried**: Updating task-master continuously during implementation to track progress
- **Why it seemed good**: Wanted to maintain real-time progress visibility
- **Why it failed**: task-master is a simple task list, not a progress tracker. It doesn't support incremental updates or progress logs.
- **Symptoms**:
  - No ability to query progress history
  - Lost detailed learning logs
  - task-master commands failed or were ignored
- **Better approach**: Write all progress to `progress-log.md` files, update task-master only when marking tasks complete
- **Example of failure**:
  ```bash
  # DON'T DO THIS
  task-master update-subtask --id=1.2 --prompt="Found bug in auth module"
  task-master update-subtask --id=1.2 --prompt="Fixed bug, testing now"
  task-master update-subtask --id=1.2 --prompt="Tests passing"
  # None of these updates are actually stored or retrievable
  ```

---

<!-- New pitfalls are appended below this line -->
