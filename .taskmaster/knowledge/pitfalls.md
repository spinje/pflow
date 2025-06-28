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

## Pitfall: Shell Operator Conflicts in CLI Design
- **Date**: 2025-06-28
- **Discovered in**: Task 2.2
- **What we tried**: Using >> as a flow operator in CLI syntax without considering shell behavior
- **Why it seemed good**: The >> operator visually represents data flow and is used in documentation
- **Why it failed**: Shell intercepts >> for output redirection before the command sees it
- **Symptoms**:
  - `pflow node1 >> node2` creates a file named "node2" instead of passing >> as argument
  - Users forced to quote the operator: `pflow node1 ">>" node2`
  - Poor user experience requiring special escaping
- **Better approach**: Choose operators without shell conflicts: =>, |>, ~>, ::, ++, etc.
- **Example of failure**:
  ```bash
  # DON'T DO THIS
  pflow read-file >> process-text
  # Shell redirects stdout to file "process-text"
  # pflow only sees: ["read-file"]

  # Required workaround (poor UX)
  pflow read-file ">>" process-text
  ```

---

<!-- New pitfalls are appended below this line -->
