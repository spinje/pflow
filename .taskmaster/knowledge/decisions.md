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

## Decision: Integrated Testing Instead of Separate Test Tasks
- **Date**: 2025-06-27
- **Made during**: Task 1.3
- **Status**: Accepted
- **Context**: Task 1.3 was entirely dedicated to testing already-implemented code from 1.1 and 1.2, creating redundancy and delaying validation
- **Alternatives considered**:
  1. **Separate test tasks/subtasks** - Dedicated tasks for writing tests after implementation
     - Pros: Clear separation of concerns, focused testing phase
     - Cons: Delays validation, creates task overhead, code might need fixes after testing
  2. **Test-first (TDD)** - Write tests before implementation
     - Pros: Clear specifications, design guidance
     - Cons: Slower initial progress, requires more upfront design
  3. **Test-as-you-go** - Write tests immediately as part of each implementation task
     - Pros: Immediate validation, single unit of work, faster feedback
     - Cons: Tasks take longer individually
- **Decision**: Adopt test-as-you-go approach - every implementation task includes its own tests
- **Rationale**:
  - Reduces total number of tasks/subtasks
  - Provides immediate validation of implementation
  - Tests and code evolve together naturally
  - Prevents accumulation of untested code
  - Single commit contains both feature and its tests
  - More efficient use of context and time
- **Consequences**:
  - Task definitions should include test requirements
  - Test strategy becomes part of implementation planning
  - No separate "verification" subtasks needed
  - Each PR/commit is complete with tests
  - Implementation time estimates must include testing
- **Review date**: After MVP completion

---

## Decision: Direct Command Execution Over Subcommands for Workflow Syntax
- **Date**: 2025-06-28
- **Made during**: Task 2.2
- **Status**: Accepted
- **Context**: Initial implementation used `pflow run node1 >> node2` but all documentation showed `pflow node1 >> node2`
- **Alternatives considered**:
  1. **Keep run subcommand** - Explicit subcommand for workflow execution
     - Pros: Clear separation of concerns, room for other subcommands
     - Cons: Extra typing, doesn't match documentation, less intuitive
  2. **Direct execution** - Workflow syntax directly after pflow command
     - Pros: Matches all documentation, more intuitive, cleaner syntax
     - Cons: Slightly more complex CLI parsing
  3. **Both approaches** - Support both with and without run
     - Pros: Backwards compatible, flexible
     - Cons: Confusing, maintenance burden, unclear which is canonical
- **Decision**: Use direct command execution without subcommands
- **Rationale**:
  - All documentation consistently shows direct usage
  - More intuitive for users (less typing)
  - Aligns with Unix philosophy of simple commands
  - The 'run' subcommand was a task decomposition error
  - Direct execution feels more like a compiler/interpreter
- **Consequences**:
  - CLI uses @click.command() instead of @click.group()
  - Version becomes a flag (--version) instead of subcommand
  - All workflow arguments collected directly
  - Future subcommands would need careful design
  - Documentation remains consistent with implementation
- **Review date**: After MVP completion

---

<!-- New decisions are appended below this line -->
