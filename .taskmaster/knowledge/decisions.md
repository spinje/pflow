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

## Decision: Traditional Function Implementation for IR Compiler (Task 4)
- **Date**: 2025-06-29
- **Made during**: Task 4.1
- **Status**: Accepted (updated Task 135 — compiler function renamed from `compile_ir_to_flow` to `compile_workflow`, returns `CompiledWorkflow` instead of `Flow`)
- **Context**: The compiler is a traditional function, not a PocketFlow-based orchestration
- **Decision**: Use traditional function implementation
- **Rationale**: The compiler is a deterministic transformation (IR → CompiledWorkflow). No retry, no I/O, no branching.
- **Current state**: `compile_workflow()` in `runtime/compilation/compiler.py`. Returns `CompiledWorkflow` with bare nodes + `NodeConfig` per node.
- **Review date**: Complete

> **Historical context**: Several earlier decisions about PocketFlow usage (internal orchestration, planner-only, parameter handling hack) were moved to `knowledge/historical/pre-task-135.md` after Task 135 removed `Flow` and the wrapper chain entirely.

---

## Decision: All pflow Nodes Must Follow Node Retry Pattern
- **Date**: 2025-07-07
- **Made during**: Node anti-pattern investigation and refactoring
- **Status**: Accepted
- **Context**: Discovered that all file operation nodes were catching exceptions in exec() methods, completely disabling the automatic retry mechanism provided by `Node._exec()` (in `pflow.core.node`)
- **Alternatives considered**:
  1. **Keep current pattern** - Continue catching exceptions for user-friendly error messages
     - Pros: Familiar error handling pattern, immediate error messages
     - Cons: No retry for transient errors, manual retry logic needed, defeats purpose of Node's retry mechanism
  2. **Partial adoption** - Only update critical nodes (file operations)
     - Pros: Less refactoring work, focused on high-impact areas
     - Cons: Inconsistent patterns, confusion about when to apply which pattern
  3. **Full adoption** - All nodes must follow Node retry pattern
     - Pros: Consistent architecture, automatic retries everywhere, simpler code
     - Cons: Requires refactoring all existing nodes, learning curve for developers
- **Decision**: Full adoption - ALL nodes must follow the Node retry pattern
- **Rationale**:
  - Retry mechanism is Node's core benefit - not using it defeats the purpose
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

## Decision: Template Variable Resolution — Runtime, Not Compile-Time
- **Date**: 2025-07-19 (original), 2026-03-31 (updated Task 135)
- **Made during**: Task 17 (original), Task 135 (mechanism changed)
- **Status**: Accepted (mechanism updated — wrapper → engine function)
- **Context**: Template variables (`${node.output}`) need resolution at runtime against the shared store, not at compile time (shared store values don't exist yet during compilation).
- **Decision**: Runtime resolution via standalone function called by the execution engine.
- **Current implementation**: `engine/template_resolution.py:resolve_templates()` called by `WorkflowEngine._execute_node()`. Resolution context is `dict(shared)` only — no `initial_params` override.
- **History**: Originally implemented as `TemplateAwareNodeWrapper` proxy (Task 17). Wrapper removed in Task 135; logic extracted to standalone function. The core principle (resolve at runtime, nodes see resolved values) is unchanged.
- **Review date**: Complete

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

## Decision: Automatic Namespacing Instead of Manual Proxy Mappings
- **Date**: 2025-08-14
- **Made during**: Task 9 (Shared Store Collision Detection and Proxy Mapping)
- **Status**: Accepted
- **Context**: Multiple nodes of the same type writing to the same shared store keys caused data collisions. The original plan was to implement manual proxy mappings where users/LLMs would explicitly configure input/output remappings. However, analysis revealed this added significant complexity for both users and the planner LLM.
- **Alternatives considered**:
  1. **Manual Proxy Mappings** - Explicit configuration of input/output remappings per node
     - Pros: Maximum flexibility, explicit control, can handle complex transformations
     - Cons: Complex configuration, verbose workflows, steep learning curve, error-prone
  2. **Automatic Proxy Mapping** - System detects collisions and generates mappings transparently
     - Pros: No user configuration, LLM never sees mappings, transparent handling
     - Cons: Hidden magic, complex edge cases, debugging challenges
  3. **Automatic Namespacing** - All node outputs automatically wrapped under node ID
     - Pros: Simple rule, no collisions possible, natural template syntax, minimal code
     - Cons: Changes shared store structure, requires explicit routing, breaks implicit connections
  4. **Force Unique Output Names** - Make every node output unique keys
     - Pros: No architectural changes needed
     - Cons: Breaks node abstraction, makes reuse harder, requires rewriting all nodes
- **Decision**: Implement automatic namespacing - all node outputs go to `shared[node_id][key]`
- **Rationale**:
  - Simplest solution that completely solves the collision problem (~200 lines vs ~500)
  - One consistent pattern for LLMs: always use `$node_id.output_key` references
  - Eliminates entire class of collision bugs without configuration
  - Template resolver already supports path syntax (`$node.key`)
  - Makes data lineage explicit and debuggable
  - Easier for LLMs to generate correct workflows (no collision avoidance puzzle)
  - Worth trading implicit connections for explicit, collision-free routing
- **Consequences**:
  - All inter-node communication now requires explicit template variables in params
  - Shared store becomes a "workflow state registry" rather than shared blackboard
  - Workflows must use `$node_id.output` pattern for all data references
  - Node reads from shared store (`shared.get("key")`) always miss, forcing param usage
  - CLI inputs remain at root level and are still accessible
  - Enabled by default for MVP (no backward compatibility concerns)
  - Tests updated to expect namespaced outputs
  - Planner generates workflows with explicit connections
- **Implementation Details**:
  - `NamespacedSharedStore` proxy redirects writes to `shared[node_id][key]` (in `runtime/engine/namespaced_store.py`)
  - Engine creates the proxy per-node: `store = NamespacedSharedStore(shared, node_id) if config.namespaced else shared`
  - Full dict protocol implemented for template resolution compatibility
  - `enable_namespacing` field in IR schema (default: true)
  - *Updated Task 135*: namespacing was originally applied via `NamespacedNodeWrapper`. Now the engine creates the proxy directly — same behavior, no wrapper indirection.
- **Review date**: Complete

---

## Decision: Orchestration Engine Over Wrapper Chain
- **Date**: 2026-03-30
- **Made during**: Task 135 (Execution Core Redesign)
- **Status**: Accepted
- **Context**: pflow had a 4-layer wrapper chain (3,924 lines) wrapping ~205 lines of PocketFlow. The chain conflated compiled structure with runtime state: `initial_params` baked runtime data into compiled nodes, the `_orch()` hack prevented param overwriting, `PflowBatchNode` reimplemented BatchFlow, sub-workflows recompiled per batch item (O(N) at 20-50ms each). Cross-cutting concerns (template resolution, namespacing, caching, tracing, batch) were distributed across 4 wrappers with chain-traversal coupling.
- **Alternatives considered**:
  1. **Fix data model only** — Remove `initial_params` override, keep wrappers
     - Pros: Smallest change, fixes compile-once
     - Cons: Wrappers still 3,920 lines, still cross-wrapper coupling, still copy.copy() gotchas
  2. **Slim PocketFlow + fix data model** — Remove unused PocketFlow classes, fix initial_params
     - Pros: Smaller PocketFlow, clean data model
     - Cons: Wrapper complexity unchanged
  3. **Full execution engine rewrite** — Replace everything including node lifecycle
     - Pros: Cleanest possible, linear execution
     - Cons: Changes BaseNode contract, all 28 nodes need updating, massive risk
  4. **Orchestration-level concerns** — Move runtime concerns from wrappers to engine, keep BaseNode/Node
     - Pros: Linear execution, no wrapper indirection, nodes unchanged, compile-once natural
     - Cons: Larger scope than option 1, touches many tests
- **Decision**: Option 4 — orchestration engine with concerns as standalone functions
- **Rationale**:
  - Wrappers solve "add behavior to components you can't modify." pflow controls everything — the framework, compiler, execution loop, and nodes. Direct orchestration is the natural pattern.
  - All 28 nodes follow identical contract: `self.params` in `prep()`, `shared` writes in `post()`. Engine sets params, nodes run unchanged.
  - Cross-cutting concerns become standalone functions with explicit parameters — no chain traversal, no instance state sharing.
  - Compile-once is a natural property: `CompiledWorkflow` is structural/immutable, runtime data flows through shared store only.
- **Consequences**:
  - `WorkflowEngine` handles all runtime concerns (~2,021 lines across 6 modules vs 3,924 lines in 4 wrappers)
  - `compile_workflow()` returns `CompiledWorkflow` (bare nodes + configs), not wrapped `Flow`
  - `_execute_node` is a ~190-line method with 17 sequential steps — long but linear and readable
  - **Don't add instance state to the engine** — parallel batch will race on it (5/8 review agents flagged this)
  - **Don't reintroduce `initial_params` as runtime data carrier** — the root cause of every prior hack
  - Subsumes Task 140 (Wrapper Chain Refactoring)
- **Review date**: N/A — foundational architecture

---

## Decision: Shared Store as Single Source of Runtime Data
- **Date**: 2026-03-30
- **Made during**: Task 135 (Execution Core Redesign)
- **Status**: Accepted
- **Context**: Template resolution used a dual-data-path: `_build_resolution_context()` did `context = dict(shared); context.update(self.initial_params)` — so `initial_params` always won over shared store. This made compile-once impossible (per-item values baked into `initial_params` at compile time couldn't be updated at runtime via shared store). Every downstream hack (`_orch()` modification, PflowBatchNode reimplementing BatchFlow, per-item recompilation) traced back to this.
- **Decision**: `context = dict(shared)` only. No override. All runtime data (CLI params, defaults, per-item batch values) flows through the shared store.
- **How it works**:
  - Runner seeds `shared_store.update(params)` (CLI values) then `shared_store.update(workflow.resolved_defaults)` (from `prepare_inputs`)
  - For sub-workflows: `child_storage.update(resolved_defaults)` then `child_storage.update(child_params)` (per-item values override defaults)
  - Template resolution reads from shared store only
- **Consequences**:
  - Compile-once works: `CompiledWorkflow` is structural, doesn't carry per-item data
  - Tests that asserted `initial_params` priority behavior document REMOVED behavior — replacements verify defaults flow through shared store
  - `resolved_defaults` only seeds keys NOT already in child_params (prevents first-item values leaking to subsequent batch items)
- **Review date**: N/A — foundational architecture

---

## Decision: Single Compilation Callsite (WorkflowRunner)
- **Date**: 2026-03-29
- **Made during**: Task 138 (Shared Execution Pipeline)
- **Status**: Accepted
- **Context**: CLI and MCP had parallel orchestration layers (~1,740 lines of duplicated glue code). `prepare_inputs()` was called 2-3 times per execution from different paths. Validation ran in both the Runner and the compiler.
- **Decision**: Single `WorkflowRunner` that both CLI and MCP call. Owns full lifecycle: resolution → file refs → validation → compilation → execution → cleanup → metadata.
- **Consequences**:
  - `prepare_inputs()` runs exactly once (in the compiler's `_prepare_compilation`)
  - `WorkflowValidator.validate()` runs exactly once (in the Runner, before compilation)
  - Template validation is in the Runner (pre-execution UX check), not the compiler
  - Made Task 135 safe: single compilation callsite means compiler changes have controlled blast radius
- **Review date**: N/A — foundational architecture

---

<!-- New decisions are appended below this line -->

## Decision: Remove Shared Store Fallback Pattern - Nodes Read From Params Only
- **Date**: 2025-12-30
- **Made during**: Namespace Collision Bug Fix
- **Status**: Accepted
- **Context**: A critical bug was discovered where node IDs or workflow inputs matching parameter names caused silent failures. For example, a node named `images` would create `shared["images"] = {stdout: ...}`, and the LLM node's fallback pattern `shared.get("images") or self.params.get("images")` would find this namespace dict instead of the template-resolved image URL, causing cryptic errors like "Image must be a string, got: dict".

  Investigation revealed the "shared store takes precedence" fallback pattern was:
  1. **Not from PocketFlow** - The node lifecycle (`BaseNode`) treats params and shared store as completely separate channels
  2. **Introduced in Task 11** (first file nodes) with no documented rationale
  3. **Redundant with template resolution** - templates like `${var}` already wire shared store values into params
  4. **In conflict with namespacing** (Task 9) which creates `shared[node_id]` dicts at root level

- **Alternatives considered**:
  1. **Filter node namespaces from visibility** - Modify `NamespacedSharedStore.keys()` and `__contains__()` to hide node namespace dicts using heuristics
     - Pros: No node code changes, backward compatible
     - Cons: Heuristic-based (needs maintenance), doesn't fix semantic issue, preserves confusing architecture
  2. **Invert priority (params first, then shared)** - Change to `self.params.get("x") or shared.get("x")`
     - Pros: Template-resolved values take precedence, fixes the bug
     - Cons: Still has implicit fallback behavior, naming coincidences still create connections
  3. **Remove fallback entirely (params only)** - Nodes read only from `self.params`
     - Pros: Explicit data flow, no implicit connections, aligns with node lifecycle design, templates are the single wiring mechanism
     - Cons: Requires updating all nodes and tests, removes "convenience" of same-name wiring
  4. **Add collision detection** - Error at compile time when names collide
     - Pros: Explicit error with fix suggestion
     - Cons: Only addresses symptom, not root cause

- **Decision**: Remove the shared store fallback pattern entirely - nodes read only from `self.params`
- **Rationale**:
  - **Aligns with node lifecycle design**: Params for static configuration (set by engine before `_run()`), shared store for explicit inter-node data flow
  - **Templates are the proper wiring mechanism**: `"input": "${node.output}"` explicitly declares data dependencies
  - **Eliminates entire class of bugs**: No implicit connections means no namespace collisions
  - **Simpler mental model**: Params contain resolved values, period. No magic based on naming.
  - **Redundancy removed**: The fallback was created before templates existed; now templates handle all data wiring
  - **No users yet**: Per CLAUDE.md, we have no production users, so this isn't a breaking change concern
  - **Explicit > Implicit**: If you want data from shared store, use a template. If you hardcode a value, it stays hardcoded.

- **Consequences**:
  - Updated ~60 parameters across 20 node implementations
  - Changed pattern from `shared.get("x") or self.params.get("x")` to `self.params.get("x")`
  - Updated all documentation (CLAUDE.md files, architecture docs, node reference)
  - Updated ~150 tests that relied on shared store fallback behavior
  - Templates like `${var}` are now the ONLY way to wire shared store data to nodes
  - Workflow inputs must be explicitly wired: `"url": "${input_url}"` instead of implicit same-name matching
  - Error messages updated from "shared store or params" to just "parameter"
  - Sets precedent: new features should favor explicit over implicit behavior

- **Implementation Details**:
  - Three pattern variants were replaced:
    1. `shared.get("x") or self.params.get("x")` → `self.params.get("x")`
    2. `shared.get("x") if "x" in shared else self.params.get("x")` → `self.params.get("x")`
    3. `if "x" in shared: ... elif "x" in self.params: ...` → `self.params.get("x")`
  - Tests that explicitly tested "shared takes precedence" were removed
  - Tests that put data in shared store expecting nodes to read it now use `node.set_params()` or `node.params = {}`

- **Review date**: After MVP completion (to validate the explicit approach works well in practice)


---

## Decision: Workflow Composition via Runtime Component Instead of User-Facing Node
- **Date**: 2025-07-27
- **Made during**: Task 20 (Nested Workflows) and subsequent refactoring
- **Status**: Accepted
- **Context**: Needed to enable workflows to execute other workflows as sub-components for reusability and composition. Initial implementation created WorkflowNode as a regular node, but this violated the conceptual model where nodes are building blocks and workflows are compositions.
- **Alternatives considered**:
  1. **WorkflowNode as regular node** - Implement as standard node in nodes/ directory
     - Pros: Consistent with "everything is a node" philosophy, simple implementation
     - Cons: Appears in planner as selectable node, confuses users ("is workflow a building block?"), violates conceptual model
  2. **Explicit workflow references in IR** - Extend IR schema with top-level workflow references
     - Pros: Most conceptually pure, clear separation in IR structure
     - Cons: Major architectural change, breaks existing IR schema, complex implementation
  3. **WorkflowExecutor as runtime component** - Move to runtime/ with compiler special handling
     - Pros: Maintains conceptual clarity, hidden from users, clean planner output
     - Cons: Requires compiler special case, deviates from "all nodes equal" principle
- **Decision**: Implement as WorkflowExecutor in runtime/ directory with special compiler handling for `type: "workflow"`
- **Rationale**:
  - Preserves user mental model: nodes are ingredients, workflows are recipes, runtime components are kitchen appliances
  - Keeps planner clean - only shows actual building blocks, not infrastructure
  - Users still write simple `type: "workflow"` in IR without knowing about WorkflowExecutor
  - Follows existing pattern of runtime components in `runtime/`
  - Small compiler special case is worthwhile trade-off for conceptual clarity
- **Consequences**:
  - Compiler has one special case for workflow type
  - WorkflowExecutor doesn't appear in registry or planner
  - Clear separation between user features (nodes/) and infrastructure (runtime/)
  - Future workflow execution improvements can be made without affecting node system
  - Sets precedent that some execution machinery belongs in runtime, not nodes
- **Review date**: 2026-01-27 (6 months)
EOF < /dev/null
