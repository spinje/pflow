# Suggested Quick Reference Table

Add this at the beginning of the "Taskmaster Tool & Command Reference" section:

---

## Quick Command Reference

| Command | Description | Category | AI |
|---------|-------------|----------|-----|
| `init` | Initialize new project | Setup | ❌ |
| `parse-prd` | Parse requirements document | Setup | ✅ |
| `models` | Configure AI models | Setup | ❌ |
| `list` | List all tasks | Viewing | ❌ |
| `next` | Show next task to work on | Viewing | ❌ |
| `show <id>` | Show specific task details | Viewing | ❌ |
| `add-task` | Add new task | Creation | ✅ |
| `add-subtask` | Add or convert to subtask | Creation | ❌ |
| `update` | Update multiple future tasks | Modification | ✅ |
| `update-task` | Update specific task | Modification | ✅ |
| `update-subtask` | Append notes to subtask | Modification | ✅ |
| `set-status` | Change task status | Modification | ❌ |
| `remove-task` | Delete task | Modification | ❌ |
| `remove-subtask` | Delete or convert subtask | Modification | ❌ |
| `expand` | Break down into subtasks | Organization | ✅ |
| `clear-subtasks` | Remove all subtasks | Organization | ❌ |
| `move` | Reorganize task hierarchy | Organization | ❌ |
| `add-dependency` | Add task dependency | Dependencies | ❌ |
| `remove-dependency` | Remove task dependency | Dependencies | ❌ |
| `validate-dependencies` | Check for issues | Dependencies | ❌ |
| `fix-dependencies` | Auto-fix issues | Dependencies | ❌ |
| `analyze-complexity` | Analyze task complexity | Analysis | ✅ |
| `complexity-report` | View complexity report | Analysis | ❌ |
| `generate` | Generate task markdown files | Files | ❌ |

**Legend:** ✅ = AI-powered (requires API key), ❌ = Local operation

---

This provides:
1. At-a-glance view of all available commands
2. Clear categorization
3. Immediate visibility of which commands need API keys
4. Quick way to find the command you need without scrolling
