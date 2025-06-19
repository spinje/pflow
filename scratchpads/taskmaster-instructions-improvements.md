# Taskmaster Instructions Document - Suggested Improvements

## 1. **Command Naming Consistency**
- Change all section headers from function-style names to match CLI commands exactly:
  - `### 1. Initialize Project (`init`)` → `### 1. Initialize Project (`init`)`
  - `### 2. Parse PRD (`parse_prd`)` → `### 2. Parse PRD (`parse-prd`)`
  - All other commands should follow this pattern (use hyphens, not underscores)

## 2. **Remove Redundant CLI Syntax in Parameter Descriptions**
Currently, parameters show redundant CLI syntax inline:
- Before: `input`: `Path to your PRD...` (CLI: `[file]` positional or `-i, --input <file>`)
- After: `input`: Path to your PRD... (Use `[file]` positional or `-i, --input <file>`)

Or better yet, show the CLI syntax in the parameter name itself:
- `[file] or -i, --input <file>`: Path to your PRD...

## 3. **Standardize Parameter Section Naming**
- Some sections use "Key Parameters/Options:" while others use "Key CLI Options:"
- Standardize all to "**Options:**" (simpler and cleaner)

## 4. **Remove Excessive Backticks**
Current format has backticks around entire descriptions:
- Before: `Set up the basic Taskmaster file structure...`
- After: Set up the basic Taskmaster file structure...

Keep backticks only for:
- Code/commands: `task-master init`
- File paths: `.taskmaster/config.json`
- Values: `pending`, `done`

## 5. **Create Common Parameters Section**
Many commands share the same parameters (e.g., `-f, --file <file>`). Create a "Common Options" section at the beginning and reference it to reduce redundancy.

## 6. **Standardize Command Documentation Structure**
Each command should have consistent sections in this order:
1. **Command:**
2. **Description:**
3. **Options:** (if any)
4. **Example:** (for complex commands)
5. **Notes:** (if needed)
6. **Important:** (for warnings/critical info)

## 7. **Add More Examples**
Commands that need examples but don't have them:
- `task-master update` (already has one, good)
- `task-master expand`
- `task-master add-task`
- `task-master move` (already has examples, good)
- `task-master add-dependency`

## 8. **Consolidate Important/Warning Messages**
Group all AI-related timing warnings into one section rather than repeating "This command makes AI calls and can take up to a minute" for each command.

## 9. **Fix Section Numbering**
- Section "### 2. Manage Models" appears after "### 2. Parse PRD"
- Renumber all sections sequentially

## 10. **Improve Section Organization**
Current organization mixes different concerns. Consider grouping by:
- **Project Setup** (init, parse-prd, models)
- **Task Management** (add-task, update-task, remove-task, set-status)
- **Task Organization** (add-subtask, remove-subtask, move, expand, clear-subtasks)
- **Dependencies** (add-dependency, remove-dependency, validate-dependencies, fix-dependencies)
- **Analysis & Reporting** (analyze-complexity, complexity-report, list, next, show)
- **File Operations** (generate)

## 11. **Simplify Option Descriptions**
Current format is verbose. Compare:
- Before: "Required. The ID of the Taskmaster task that will depend on another."
- After: "Required. Task ID that will depend on another."

## 12. **Add Command Shortcuts/Aliases**
If any commands have shortcuts, document them clearly.

## 13. **Create Quick Reference Table**
Add a table at the beginning with:
| Command | Description | AI-Powered |
|---------|-------------|------------|
| `init` | Initialize project | No |
| `parse-prd` | Parse requirements document | Yes |
| etc... | | |

## 14. **Improve Formatting Consistency**
- Some sections use `*` for bullet points in options, others don't
- Standardize indentation (currently mixes 4 spaces and varying indents)
- Consistent use of bold vs regular text

## 15. **Add Version/Compatibility Information**
Include what version of task-master this documentation applies to.

## Summary of Benefits:
- Reduces document length by ~30% through elimination of redundancy
- Improves scanability with consistent structure
- Makes it easier to find specific command information
- Reduces ambiguity in command naming
- Creates a more professional, polished appearance
