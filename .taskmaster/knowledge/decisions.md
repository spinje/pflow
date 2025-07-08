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
- **Status**: Superseded (see "Limit PocketFlow Internal Usage to Natural Language Planner Only")
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
  - Originally planned for 6 tasks: 4, 8, 17, 20, 22, 23
  - This decision was later refined to only Task 17 - see next decision
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

## Decision: Modify PocketFlow Instead of Using Wrapper for Parameter Handling
- **Date**: 2025-01-07
- **Made during**: Task 3 (Execute a Hardcoded 'Hello World' Workflow)
- **Status**: Accepted (Temporary)
- **Context**: PocketFlow's Flow._orch() method overwrites node parameters with flow parameters, preventing pflow nodes from maintaining their configuration values set during compilation
- **Deep Dive**: See detailed analysis in `decision-deep-dives/pocketflow-parameter-handling/`
- **Alternatives considered**:
  1. **PreservingFlow wrapper** - Custom Flow subclass that preserves node parameters
     - Pros: Clean separation, no framework modification, clear intent
     - Cons: Extra wrapper layer, diverges from standard PocketFlow usage
  2. **Store configuration in shared store** - Use shared store for all configuration
     - Pros: Aligns with PocketFlow design, no modifications needed
     - Cons: Mixes config with runtime data, requires major refactoring, cluttered shared store
  3. **Modify PocketFlow directly** - Add conditional check in _orch()
     - Pros: Minimal change (3 lines), fixes root cause, no wrapper needed
     - Cons: Modifies external framework, breaks BatchFlow, temporary solution
  4. **Use Flow-level parameters** - Set all params on Flow instead of nodes
     - Pros: Works with current design
     - Cons: All nodes share params, no node-specific config, doesn't match pflow's model
- **Decision**: Modify PocketFlow's _orch() method to only override node parameters when explicitly passed
- **Rationale**:
  - MVP doesn't need BatchFlow functionality, so breaking it is acceptable temporarily
  - Minimal change (3 lines) reduces complexity
  - Direct fix is clearer than wrapper indirection
  - Easy to revert when BatchFlow support is needed
  - Pragmatic solution for current scope
  - Well-documented as temporary modification
- **Consequences**:
  - BatchFlow functionality will not work until this is addressed
  - Must document this modification clearly (PFLOW_MODIFICATIONS.md created)
  - Need to revisit before implementing any batch processing features
  - Future options include: reverting to wrapper, enhancing condition, redesigning parameter model, or forking
  - All pflow developers must be aware of this modification
  - Cannot update PocketFlow without careful consideration
- **Review date**: Before implementing BatchFlow support or at MVP completion

---

## Decision: All pflow Nodes Must Follow PocketFlow Retry Pattern
- **Date**: 2025-07-07
- **Made during**: PocketFlow anti-pattern investigation and refactoring
- **Status**: Accepted
- **Context**: Discovered that all file operation nodes in pflow were violating PocketFlow's most critical anti-pattern by catching exceptions in exec() methods, completely disabling the framework's automatic retry mechanism
- **Alternatives considered**:
  1. **Keep current pattern** - Continue catching exceptions for user-friendly error messages
     - Pros: Familiar error handling pattern, immediate error messages
     - Cons: No retry for transient errors, manual retry logic needed, defeats purpose of using PocketFlow
  2. **Partial adoption** - Only update critical nodes (file operations)
     - Pros: Less refactoring work, focused on high-impact areas
     - Cons: Inconsistent patterns, confusion about when to apply which pattern
  3. **Full adoption** - All nodes must follow PocketFlow retry pattern
     - Pros: Consistent architecture, automatic retries everywhere, simpler code
     - Cons: Requires refactoring all existing nodes, learning curve for developers
- **Decision**: Full adoption - ALL nodes in pflow must follow the PocketFlow retry pattern
- **Rationale**:
  - Retry mechanism is PocketFlow's core benefit - not using it defeats the purpose
  - Transient errors (file locks, network issues) are common and should be retried
  - Consistency across codebase prevents confusion and errors
  - Framework handles retry complexity (exponential backoff, max attempts)
  - Simpler code without manual retry loops and error handling
  - Better reliability for all operations, not just file I/O
- **Consequences**:
  - Must refactor all existing nodes to remove try/except from exec()
  - Create NonRetriableError exception class for validation errors
  - Document pattern prominently in node implementation guides
  - Update all tests to verify retry behavior
  - Train developers on counter-intuitive pattern (letting exceptions bubble up)
  - Create node implementation checklist and templates
  - Monitor for regression to old patterns in code reviews
- **Implementation Details**:
  - Nodes inherit from `Node` (not `BaseNode`) for retry support
  - exec() method lets exceptions bubble up (no try/except)
  - exec_fallback() handles final error messages after retries exhausted
  - NonRetriableError for validation errors that shouldn't retry
  - post() method checks for error prefix to detect failures
- **Review date**: After all nodes refactored (immediate priority)

---

<!-- New decisions are appended below this line -->
