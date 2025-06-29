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

## Decision: Use PocketFlow for Internal Orchestration
- **Date**: 2025-06-29
- **Made during**: Architecture analysis before task implementation
- **Status**: Accepted
- **Context**: pflow is built on PocketFlow framework, but we needed to decide whether to use PocketFlow internally for pflow's own implementation or stick to traditional imperative Python code
- **Alternatives considered**:
  1. **Traditional imperative code** - Standard Python functions and classes
     - Pros: Familiar patterns, no learning curve, direct control
     - Cons: Manual retry loops, nested try/catch blocks, hidden control flow, inconsistent error handling
  2. **PocketFlow for everything** - Use PocketFlow for all components
     - Pros: Consistent patterns everywhere
     - Cons: Over-engineering simple operations, performance overhead for utilities
  3. **Hybrid approach** - PocketFlow for orchestration, traditional for utilities
     - Pros: Right tool for right job, clear architecture zones, optimal performance
     - Cons: Two patterns to understand, need clear decision criteria
- **Decision**: Use hybrid approach - PocketFlow for complex orchestrations (6 specific tasks), traditional code for utilities
- **Rationale**:
  - PocketFlow is only ~100 lines - it's a pattern, not a heavy framework
  - Many pflow operations are multi-step orchestrations that need retry logic
  - Built-in retry/fallback eliminates manual error handling code
  - Visual flow representation with >> operator aids understanding
  - Isolated nodes improve testability
  - We prove PocketFlow works by using it ourselves
  - Traditional code remains best for pure computations and data structures
- **Consequences**:
  - 5 core orchestration tasks will use PocketFlow: Tasks 8, 17, 20, 22, 23 (Task 4 removed - see separate decision)
  - Tasks 17 (planner) and 8 (shell integration) has been identified as the best candidates for PocketFlow orchestration
  - Clear directory structure: flows/ for PocketFlow, core/ for traditional
  - Each PocketFlow component follows the implementation template
  - Developers need to understand both patterns
  - Architecture is explicit in CLAUDE.md and ADR-001
  - Future tasks must evaluate which pattern fits best
- **Review date**: After MVP completion

---

## Decision: Traditional Function Implementation for IR Compiler (Task 4)
- **Date**: 2025-06-29
- **Made during**: Task 4.1
- **Status**: Accepted
- **Context**: Task 4 (IR-to-PocketFlow compiler) was originally planned to use PocketFlow orchestration, but during implementation we needed to choose between two approaches
- **Alternatives considered**:
  1. **Option A: Traditional Function** - Simple Python functions with helper utilities
     - Pros: Simple, direct, easy to test and debug
     - Cons: Manual error handling, no built-in retry
  2. **Option B: PocketFlow Orchestration** - Use PocketFlow nodes for compilation steps
     - Pros: Built-in retry, visual flow, consistent with other orchestrations
     - Cons: Over-engineering for simple transformation, meta-complexity (using PocketFlow to compile PocketFlow)
- **Decision**: Use Option A - Traditional function implementation
- **Rationale**:
  - The compiler is fundamentally a simple transformation: IR → Flow object
  - No retry logic needed (compilation either works or fails immediately)
  - No async operations or external I/O involved
  - No branching logic or complex error recovery paths
  - Easier to test with standard unit testing approaches
  - Avoids the conceptual complexity of using PocketFlow to compile PocketFlow workflows
  - The transformation is linear and deterministic
- **Consequences**:
  - Compiler implemented as `compile_ir_to_flow(ir_json, registry)` function
  - Helper functions for specific concerns (parsing, validation, import, wiring)
  - Standard exception handling with CompilationError class
  - Traditional unit tests without PocketFlow test utilities
  - Removes Task 4 from the list of PocketFlow-based components
  - Sets precedent that not everything needs PocketFlow - use it where it adds value
- **Review date**: After compiler implementation complete

---

## Decision: Limit PocketFlow Internal Usage to Natural Language Planner Only
- **Date**: 2025-06-29 (Revised from earlier decision)
- **Made during**: Post-implementation architecture review
- **Status**: Accepted (Supersedes partial previous decision)
- **Context**: Initial analysis suggested 6 tasks could benefit from PocketFlow orchestration. Further review revealed only Task 17 (Natural Language Planner) has genuinely complex orchestration needs
- **Alternatives considered**:
  1. **Original plan: 6 tasks** - Use PocketFlow for Tasks 4, 8, 17, 20, 22, 23
     - Pros: Consistent approach, comprehensive dogfooding
     - Cons: Over-engineering simple operations, cognitive overhead, violates simplicity principle
  2. **Scaled back: 2-3 tasks** - Use for most complex tasks only
     - Pros: Balanced approach, proves value incrementally
     - Cons: Still adds complexity where not truly needed
  3. **Focused: Task 17 only** - Use PocketFlow only for the Natural Language Planner
     - Pros: Right tool for right job, maximum simplicity, clear value
     - Cons: Less comprehensive validation of PocketFlow capabilities
- **Decision**: Use PocketFlow ONLY for Task 17 (Natural Language Planner)
- **Rationale**:
  - Task 17 has genuinely complex needs: multiple LLM retries, self-correcting loops, branching paths
  - Other tasks are straightforward: simple I/O, linear execution, basic error handling
  - Avoids "hammer looking for nails" anti-pattern
  - Keeps codebase accessible to contributors familiar with traditional Python
  - PocketFlow's retry mechanism and flow orchestration truly benefit the planner
  - Simplicity is a core project principle - don't add complexity without clear value
- **Consequences**:
  - Only src/pflow/flows/planner/ will use PocketFlow patterns
  - All other components use traditional Python functions and classes
  - Deleted generic PocketFlow templates and interface guides
  - Updated ADR-001 to reflect focused approach
  - Clear architectural boundary: PocketFlow for complex AI orchestration only
  - Future components default to traditional code unless complexity justifies PocketFlow
- **Review date**: After Task 17 implementation

---

<!-- New decisions are appended below this line -->
