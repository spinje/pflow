# Architectural Decisions

A chronological record of significant architectural and design decisions made during the project. These decisions shape the project's direction and should be consulted when making related choices.

**Before adding**: Read this entire file and search for decisions in the same architectural area.

---

## Decision: File-Based Knowledge System Over Database
- **Date**: 2024-01-15
- **Made during**: Task 3.1 (Example)
- **Status**: Accepted
- **Context**: Need a system for storing and retrieving patterns, pitfalls, and decisions discovered during task implementation
- **Alternatives considered**:
  1. **SQLite database** - Structured queries, relationships between entries
     - Pros: Powerful queries, data integrity
     - Cons: Overhead for AI agents, needs SQL knowledge
  2. **Individual files per entry** - Each pattern/pitfall gets own file
     - Pros: Git-friendly, isolated entries
     - Cons: Hard to prevent duplicates, many files to read
  3. **Consolidated markdown files** - One file per knowledge type
     - Pros: Easy to read/append, simple duplicate checking
     - Cons: Could get large, less structured than database
- **Decision**: Use consolidated markdown files (one each for patterns, pitfalls, decisions)
- **Rationale**:
  - AI agents can easily read/write markdown
  - Full-file reading for duplicate check is fast for AI
  - Append-only pattern is simple and reliable
  - Git tracking shows knowledge evolution
  - No additional tooling required
- **Consequences**:
  - Must maintain consistent format for parsing
  - Agents must read entire file before adding
  - May need organization strategy if files get very large (>1000 entries)
- **Review date**: 2024-07-15 (6 months)

---

<!-- New decisions are appended below this line -->
