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

## Decision: Template Variable Resolution Using Proxy Pattern
- **Date**: 2025-07-19
- **Made during**: Task 17 (Natural Language Planner)
- **Status**: Accepted
- **Context**: The planner generates workflows with template variables ($variable syntax) for reusability, but these need resolution at runtime. The IR schema supports template variables in node params, but there's no built-in mechanism for substitution. We needed a way to resolve templates without modifying PocketFlow or breaking node atomicity.
- **Alternatives considered**:
  1. **Extend PocketFlow** - Add template resolution to the framework
     - Pros: Clean integration, works for all flows automatically
     - Cons: Violates PocketFlow's minimalist philosophy, adds complexity to generic framework
  2. **Node-level resolution** - Each node handles its own templates
     - Pros: Nodes control their own behavior
     - Cons: Breaks atomicity, every node needs template logic, violates single responsibility
  3. **Compile-time only** - Only substitute CLI parameters before creating Flow
     - Pros: Simple implementation, no runtime complexity
     - Cons: Can't reference shared store values, limits template usefulness
  4. **Runtime proxy wrapper** - Wrap nodes with template-resolving proxy
     - Pros: Preserves atomicity, uses proven pattern, composable with existing proxies
     - Cons: Adds runtime layer, slight performance overhead
- **Decision**: Runtime proxy wrapper pattern - similar to existing NodeAwareSharedStore
- **Rationale**:
  - Follows established proxy pattern already used for shared store mapping
  - Nodes remain completely unaware of templates (preserves atomicity)
  - No modifications to PocketFlow framework needed
  - Composable with existing NodeAwareSharedStore proxy
  - Clean separation between orchestration (PocketFlow) and application logic (pflow)
  - Allows both CLI parameter and shared store variable resolution
- **Consequences**:
  - Must implement TemplateResolvingNodeProxy in pflow runtime
  - Template resolution happens transparently just before node execution
  - Two-phase resolution: CLI params at compile time, shared store vars at runtime
  - Nodes see resolved values in params, original templates preserved for reuse
  - Performance overhead minimal (string substitution per node execution)
  - Can be implemented incrementally without breaking existing functionality
- **Implementation Details**:
  - TemplateResolvingNodeProxy wraps nodes that have template params
  - Proxy intercepts _run() to resolve templates from shared store
  - Original params restored after execution (keeps nodes reusable)
  - Works alongside NodeAwareSharedStore for complete proxy solution
  - Simple $variable → shared["variable"] mapping for MVP
- **Review date**: After template system implementation and initial usage

---

## Decision: Node IR for Accurate Template Validation
- **Date**: 2025-07-27
- **Made during**: Task 19 (Implement Node Interface Registry)
- **Status**: Accepted
- **Context**: Template validator was using hardcoded heuristics (a "magic list" of common variable names like "result", "output", "summary") to guess which variables come from the shared store vs CLI parameters. This caused false validation failures when nodes wrote variables not in the magic list (e.g., `$api_config`), even though the workflow was valid. Users saw confusing errors like "Missing required parameter: --api_config" when a node actually wrote that variable.
- **Alternatives considered**:
  1. **Expand the magic list** - Add more common variable names to the heuristic
     - Pros: Quick fix, no architectural changes needed
     - Cons: Whack-a-mole problem, always incomplete, fundamentally flawed approach
  2. **Runtime interface checking** - Parse node interfaces during validation
     - Pros: Accurate validation, no registry changes
     - Cons: Performance hit on every validation, redundant parsing, complex implementation
  3. **Node IR (Intermediate Representation)** - Parse interfaces at scan-time, store in registry
     - Pros: Single source of truth, parse once use many times, enables future features
     - Cons: Registry format change (breaking), larger registry size, one-time refactor needed
- **Decision**: Implement Node IR - move interface parsing from runtime to scan-time
- **Rationale**:
  - Eliminates the fundamental flaw of guessing what nodes write
  - Follows "parse once, use many times" principle (DRY)
  - Creates foundation for future features (type checking, better errors)
  - Performance improvement by removing runtime parsing
  - Clean architectural separation - scanner handles parsing, consumers just use data
  - Aligns with compiler design principles (separate parsing from execution)
- **Consequences**:
  - Registry format breaking change - added "interface" field with parsed metadata
  - Registry size increased from ~50KB to ~500KB-1MB (acceptable for MVP)
  - All nodes MUST have interface field (no fallbacks)
  - Context builder simplified by ~75 lines (removed dynamic imports)
  - Validator can now validate full paths (e.g., `$api_config.endpoint.url`)
  - Every pflow command loads larger registry (+50ms startup time)
  - Scanner must handle circular imports with lazy loading pattern
- **Implementation Details**:
  - Scanner uses singleton MetadataExtractor with dependency injection
  - MetadataExtractor always returns rich format: `[{"key": "x", "type": "str", "description": "..."}]`
  - Context builder now requires interface field (fails fast if missing)
  - Validator traverses nested structures for path validation
  - Compiler passes registry to validator (API change)
  - All 611 tests updated and passing
- **Review date**: After MVP completion (to assess performance impact)

---

<!-- New decisions are appended below this line -->
