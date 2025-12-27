---
description: Log completed bug fix to knowledge base
---

You have just fixed a bug. You need to log the bug fix in the bug fix log and optionally add a new knowledge base entry (pitfall or pattern) to the knowledge base.

The bug fix log is in the .taskmaster/bugfix/bugfix-log.md file.

This log exists for future developers or AI agents to learn from the bug fix and avoid similar bugs in the future.

Before you log the bug fix, you need to:
1. Read the CLAUDE.md file in the .taskmaster/bugfix folder to learn about the bug fix process and understand the template.
2. Think hard about what you did and why you did it and what you learned from the bug fix.
3. Write down the most important lessons and heuristics you learned from the bug fix into .taskmaster/bugfix/bugfix-log.md following the template as closely as possible while still being true to your own experience and learning. 
4. (Optional) If you've made significant discoveries and applied a new pattern or uncovered a new pitfall, add a new knowledge base entry in the .taskmaster/knowledge/pitfalls.md or .taskmaster/knowledge/patterns.md file.

Rules for adding to the shared knowledge base:
- Only add new knowledge that is genuinely new to this codebase (not already widely known or standard practice for humans or llms)
- Prioritize quality over quantity—each entry should be highly valuable for this specific codebase
- Patterns included here should be broadly applicable and beneficial to multiple areas of the codebase or valuable to know for AI coding agents reading the knowledge base
- If you are not sure whether to add a new knowledge base entry, you probably shouldn't add it. Only add 10/10 knowledge base entries with a high level of confidence and CLEAR value and generalizability.
- Avoid boilerplate or standard knowledge that you allready knew about before solving the bug (only NEW knowledge that you learned from solving the bug should considered).
