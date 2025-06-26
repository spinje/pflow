# Knowledge Base Maintenance Guide

This directory contains consolidated knowledge from all task implementations. Each file aggregates a specific type of learning to prevent duplicates and improve knowledge discovery.

## Structure

- **patterns.md** - Successful patterns and approaches that worked well
- **pitfalls.md** - Failed approaches and anti-patterns to avoid
- **decisions.md** - Architectural decisions with rationale and context

## For AI Agents: How to Add Knowledge

### CRITICAL: Check for Duplicates First
Before adding ANY entry:
1. Read the entire target file
2. Search for key terms related to your entry
3. Check if similar knowledge already exists
4. Only add if genuinely new or significantly different

### Adding a Pattern

1. Read `patterns.md` completely
2. Search for keywords related to your pattern's problem/solution
3. If unique, append to end of file using this format:

```markdown
## Pattern: [Descriptive Name]
- **Date**: [YYYY-MM-DD]
- **Discovered in**: Task [X.Y]
- **Problem**: [What problem does this solve?]
- **Solution**: [How does the pattern solve it?]
- **Example**:
  ```[language]
  [Concrete code example]
  ```
- **When to use**: [Specific conditions where this applies]
- **Benefits**: [Why this is better than alternatives]

---
```

### Adding a Pitfall

1. Read `pitfalls.md` completely
2. Search for the approach/technology/pattern you tried
3. If unique, append using this format:

```markdown
## Pitfall: [What Not to Do]
- **Date**: [YYYY-MM-DD]
- **Discovered in**: Task [X.Y]
- **What we tried**: [The approach that failed]
- **Why it seemed good**: [Initial reasoning]
- **Why it failed**: [Root cause analysis]
- **Symptoms**: [How the problem manifests]
- **Better approach**: [What to do instead]
- **Example of failure**:
  ```[language]
  // DON'T DO THIS
  [Code that demonstrates the problem]
  ```

---
```

### Adding a Decision

1. Read `decisions.md` completely
2. Search for the architectural area/component
3. If this is a new decision area, append using:

```markdown
## Decision: [Clear Decision Title]
- **Date**: [YYYY-MM-DD]
- **Made during**: Task [X.Y]
- **Status**: [Accepted/Superseded/Deprecated]
- **Context**: [Why this decision was needed]
- **Alternatives considered**:
  1. [Option A] - [Pros/cons]
  2. [Option B] - [Pros/cons]
  3. [Option C] - [Pros/cons]
- **Decision**: [What was chosen]
- **Rationale**: [Why this was the best choice]
- **Consequences**: [What this means for the project]
- **Review date**: [When to revisit this decision]

---
```

## Important Guidelines

### 1. Maintain Consistency
- Always use the exact format shown above
- Include the `---` separator between entries
- Use clear, descriptive titles

### 2. Be Specific
- Include concrete code examples
- Reference specific task numbers
- Explain the "why" not just the "what"

### 3. Think Long-term
- Write for future implementers (including future AI agents)
- Explain context that might not be obvious later
- Include enough detail to apply the knowledge

### 4. Avoid Duplicates
- Similar patterns should be merged or cross-referenced
- Update existing entries if you have significant new insights
- Link related entries when appropriate

### 5. Quality over Quantity
- Only add knowledge that will genuinely help future tasks
- Ensure entries are well-reasoned and evidence-based
- Test patterns before documenting them

## Search Strategies for Duplicate Detection

### For Patterns:
- Search for: problem keywords, technology names, solution approaches
- Example: "auth", "validation", "caching", "async"

### For Pitfalls:
- Search for: technology names, error messages, approach keywords
- Example: "subprocess", "timeout", "race condition"

### For Decisions:
- Search for: component names, architectural concepts
- Example: "database", "API design", "testing strategy"

## File Maintenance

As these files grow:
- Entries remain chronological (newest at bottom)
- No need to reorganize unless explicitly requested
- Search is more important than organization
- Let patterns emerge naturally

## When to Extract from Subtask Reviews

During implementation (Phase 2), extract knowledge when:
- A pattern proves successful across multiple uses
- An approach fails in an instructive way
- An architectural decision has lasting impact
- The learning would help future tasks

Remember: The goal is to build a knowledge base that makes each subsequent task easier and better.
