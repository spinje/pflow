# Anti-Patterns and Warnings for pflow

This document identifies anti-patterns, complexity warnings, and common mistakes found in the analyzed PocketFlow repositories that would hurt pflow's goals of deterministic, CLI-first, 10x efficient workflows.

## Anti-Pattern: Agent-Based Iterative Loops
- **Found In**: Tutorial-Cursor (MainDecisionAgent loop), PocketFlow-Tutorial-Website-Chatbot (explore/answer loop)
- **Why It's Problematic**: Non-deterministic execution, unbounded runtime, difficult to cache/replay
- **Impact on pflow**: Breaks "Plan Once, Run Forever" philosophy - same input may produce different flows
- **Alternative Approach**: Generate complete workflow upfront with fixed node sequence
- **Tasks to Avoid In**: Task 17 (LLM Workflow Generation), Task 3 (Execute Workflow)

## Anti-Pattern: Async/Parallel Execution in MVP
- **Found In**: PocketFlow-Tutorial-Danganronpa-Simulator (AsyncFlow, AsyncParallelBatchFlow)
- **Why It's Problematic**: Adds complexity, race conditions, harder debugging, non-deterministic ordering
- **Impact on pflow**: Violates MVP simplicity, makes execution tracing difficult
- **Alternative Approach**: Synchronous execution only for MVP, defer async to v2.0
- **Tasks to Avoid In**: All MVP tasks - use simple synchronous nodes

## Anti-Pattern: Over-Complex Batch Processing
- **Found In**: Multiple repos using BatchNode for parallel processing
- **Why It's Problematic**: Hidden complexity, memory overhead, difficult error handling
- **Impact on pflow**: Complicates simple workflows, harder to understand execution flow
- **Alternative Approach**: Process items sequentially in MVP, or use simple list comprehensions
- **Tasks to Avoid In**: Task 11 (File Nodes), Task 12 (LLM Node) - keep nodes simple

## Anti-Pattern: Database-Driven State Persistence
- **Found In**: PocketFlow-Tutorial-Danganronpa-Simulator (SQLite for game state)
- **Why It's Problematic**: Adds dependencies, complexity, not CLI-friendly
- **Impact on pflow**: Breaks simplicity, requires database setup/management
- **Alternative Approach**: File-based state (JSON/YAML) or ephemeral shared store only
- **Tasks to Avoid In**: Task 24 (Caching), Task 23 (Tracing) - use simple file storage

## Anti-Pattern: Complex Conditional Branching
- **Found In**: Tutorial-Cursor (multiple action branches), Website Chatbot (explore/answer decision)
- **Why It's Problematic**: Makes flows hard to visualize, test, and cache
- **Impact on pflow**: Exponential complexity growth, harder to achieve determinism
- **Alternative Approach**: Linear flows for MVP, data-driven behavior through shared store
- **Tasks to Avoid In**: Task 4 (IR Compiler), Task 6 (JSON IR Schema) - defer conditionals

## Anti-Pattern: Deep Shared Store Nesting
- **Found In**: Some repos use 3+ levels of nested dictionaries in shared store
- **Why It's Problematic**: Hard to document, validate, and debug
- **Impact on pflow**: Makes collision detection complex, harder to use from CLI
- **Alternative Approach**: Flat key structure with descriptive names, max 2 levels
- **Tasks to Avoid In**: Task 9 (Shared Store & Proxy), Task 3 (Hello World)

## Anti-Pattern: History-Based Parameter Passing
- **Found In**: Tutorial-Cursor (params from last history entry)
- **Why It's Problematic**: Implicit dependencies, order-dependent execution
- **Impact on pflow**: Breaks node independence, makes testing difficult
- **Alternative Approach**: Explicit parameters from IR or shared store keys
- **Tasks to Avoid In**: All node implementation tasks - use explicit interfaces

## Anti-Pattern: Web UI Integration in Core
- **Found In**: Multiple repos with Streamlit/FastAPI servers
- **Why It's Problematic**: Adds dependencies, not CLI-first, complicates deployment
- **Impact on pflow**: Distracts from CLI focus, adds unnecessary complexity
- **Alternative Approach**: Pure CLI interface, output to files/stdout
- **Tasks to Avoid In**: All MVP tasks - focus on CLI only

## Anti-Pattern: Implicit Error Swallowing
- **Found In**: Some repos catch all exceptions and return defaults
- **Why It's Problematic**: Hides real errors, makes debugging impossible
- **Impact on pflow**: Silent failures lead to incorrect results
- **Alternative Approach**: Fail fast with clear errors, use exec_fallback selectively
- **Tasks to Avoid In**: All node tasks - explicit error handling only

## Anti-Pattern: Non-Deterministic Node Behavior
- **Found In**: Nodes using random selection, time-based decisions
- **Why It's Problematic**: Breaks reproducibility, can't cache results
- **Impact on pflow**: Violates core "deterministic execution" principle
- **Alternative Approach**: Always use temperature=0, sorted lists, hash-based selection
- **Tasks to Avoid In**: Task 12 (LLM Node), Task 17 (Workflow Generation)

## Anti-Pattern: Over-Engineered Node Abstractions
- **Found In**: Complex inheritance hierarchies, abstract base classes
- **Why It's Problematic**: Harder to understand, more code to maintain
- **Impact on pflow**: Slows development, confuses users
- **Alternative Approach**: Simple Node class, composition over inheritance
- **Tasks to Avoid In**: Task 5 (Node Discovery), all node implementation tasks

## Anti-Pattern: Magic String Keys
- **Found In**: Hardcoded strings scattered throughout code
- **Why It's Problematic**: Typos cause silent failures, hard to refactor
- **Impact on pflow**: Reduces reliability, harder to maintain
- **Alternative Approach**: Constants for common keys, validate in prep()
- **Tasks to Avoid In**: Task 9 (Shared Store), all node tasks

## Anti-Pattern: Unbounded Resource Consumption
- **Found In**: Website Chatbot (100 pages max), unlimited retries
- **Why It's Problematic**: Can hang indefinitely, consume excessive resources
- **Impact on pflow**: Poor user experience, unpredictable runtime
- **Alternative Approach**: Hard limits on iterations, timeouts, file sizes
- **Tasks to Avoid In**: Task 11 (File Nodes), Task 12 (LLM Node)

## Anti-Pattern: Complex State Transactions
- **Found In**: Danganronpa's transactional state updates
- **Why It's Problematic**: Over-engineering for simple workflows
- **Impact on pflow**: Adds complexity without clear benefit
- **Alternative Approach**: Simple additive state building, immutable by default
- **Tasks to Avoid In**: Task 9 (Shared Store), Task 3 (Execute Workflow)

## Anti-Pattern: External Service Tight Coupling
- **Found In**: Direct API calls in node exec() methods
- **Why It's Problematic**: Hard to test, no retry logic, coupling
- **Impact on pflow**: Fragile nodes, difficult mocking
- **Alternative Approach**: Utils for external calls, dependency injection
- **Tasks to Avoid In**: Task 13 (GitHub Node), Task 12 (LLM Node)

## Anti-Pattern: Ignored Pre-commit Hooks
- **Found In**: Some repos have pre-commit configs but don't use them
- **Why It's Problematic**: Code quality degradation, inconsistent formatting
- **Impact on pflow**: Technical debt accumulation
- **Alternative Approach**: Enforce pre-commit hooks, fail CI on violations
- **Tasks to Avoid In**: Task 1 (Setup) - configure and enforce from start

## Performance Anti-Patterns

### Anti-Pattern: Synchronous External API Calls in Loops
- **Found In**: Sequential processing of multiple URLs/files
- **Why It's Problematic**: 10x slower than necessary
- **Impact on pflow**: Defeats 10x efficiency goal
- **Alternative Approach**: Batch where possible, cache aggressively
- **Tasks to Avoid In**: Task 11 (File Nodes), Task 13 (GitHub Node)

### Anti-Pattern: Loading Entire Files into Memory
- **Found In**: Reading large files completely before processing
- **Why It's Problematic**: Memory exhaustion, slow startup
- **Impact on pflow**: Can't handle large inputs
- **Alternative Approach**: Stream processing, content truncation
- **Tasks to Avoid In**: Task 11 (File Nodes)

### Anti-Pattern: No Output Streaming
- **Found In**: Collecting all output before displaying
- **Why It's Problematic**: Poor user experience, appears frozen
- **Impact on pflow**: Users think it's not working
- **Alternative Approach**: Progressive output, status updates
- **Tasks to Avoid In**: Task 23 (Execution Tracing), CLI tasks

## Maintenance Anti-Patterns

### Anti-Pattern: Scattered Configuration
- **Found In**: Config in multiple places, env vars, hardcoded values
- **Why It's Problematic**: Hard to configure, easy to miss settings
- **Impact on pflow**: Poor user experience, configuration errors
- **Alternative Approach**: Centralized config with clear defaults
- **Tasks to Avoid In**: Task 2 (CLI Setup), Task 15 (LLM Client)

### Anti-Pattern: Missing Error Context
- **Found In**: Generic error messages without actionable info
- **Why It's Problematic**: Users can't fix problems themselves
- **Impact on pflow**: Support burden, poor UX
- **Alternative Approach**: Rich error messages with fix suggestions
- **Tasks to Avoid In**: All tasks - always provide context

### Anti-Pattern: Assuming Environment State
- **Found In**: Expecting certain tools/files to exist
- **Why It's Problematic**: Fails in different environments
- **Impact on pflow**: Not portable, setup friction
- **Alternative Approach**: Check prerequisites, clear error messages
- **Tasks to Avoid In**: Task 14 (Shell Nodes), Task 1 (Setup)

## Summary: What to Avoid for pflow Success

1. **Avoid Loops**: No agent loops, use deterministic flows
2. **Avoid Async**: Keep it synchronous for MVP
3. **Avoid Databases**: Use files for persistence
4. **Avoid Conditionals**: Linear flows only in MVP
5. **Avoid Deep Nesting**: Flat shared store structure
6. **Avoid Implicit State**: Explicit parameters always
7. **Avoid Web UIs**: CLI-first, always
8. **Avoid Silent Failures**: Fail fast and loud
9. **Avoid Randomness**: Deterministic execution only
10. **Avoid Over-Engineering**: Simple nodes, simple flows

The key insight: **Complexity is the enemy of reliability**. Every anti-pattern adds complexity that makes pflow less deterministic, less efficient, and harder to debug. By avoiding these patterns, pflow can achieve its goal of 10x efficiency through simplicity and determinism.
