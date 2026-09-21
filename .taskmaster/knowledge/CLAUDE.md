# Knowledge base maintenance

- `patterns.md`: successful approaches.
- `pitfalls.md`: failed approaches and their replacements.
- `decisions.md`: architectural choices and rationale.
- `historical/pre-task-135.md` and `historical/pocketflow-parameter-handling/`: superseded execution designs and investigations.

Entries are evidence from their task's context, not automatically current instructions. Even entries without a superseded label can describe obsolete behavior; verify against source before applying them.

## Contribution policy

Add only codebase-specific or difficult, non-obvious knowledge that will help multiple areas or future coding agents. Do not add standard practice or generic advice.

Before adding an entry, read the entire target file and search for related problem, component, and approach terms. Update, merge, or cross-reference related entries instead of duplicating them. Append only genuinely new or significantly different knowledge.

Include concrete examples, task references, evidence, and the reason the approach worked or failed. Test patterns before documenting them. Capture reusable successes, instructive failures, and decisions with lasting impact; include enough context for a future implementer to apply the learning.

## Entry format

Use the exact heading and field labels below, in the listed order. Fields are markdown bullets formatted as `- **Label**: value`. Use descriptive titles, `YYYY-MM-DD` dates, and `Task X.Y` references. Examples are language-tagged fenced code blocks; list alternatives as numbered options with their tradeoffs.

| File | Heading | Fields |
|------|---------|--------|
| `patterns.md` | `## Pattern: [Descriptive Name]` | Date; Discovered in; Problem; Solution; Example; When to use; Benefits |
| `pitfalls.md` | `## Pitfall: [What Not to Do]` | Date; Discovered in; What we tried; Why it seemed good; Why it failed; Symptoms; Better approach; Example of failure |
| `decisions.md` | `## Decision: [Clear Decision Title]` | Date; Made during; Status; Context; Alternatives considered; Decision; Rationale; Consequences; Review date |

Decision status is `Accepted`, `Superseded`, or `Deprecated`. Separate entries with `---`. Keep new entries chronological, newest at the bottom; do not reorganize existing files unless explicitly requested.
