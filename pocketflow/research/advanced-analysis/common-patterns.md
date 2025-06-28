# Common Patterns Across Advanced PocketFlow Applications

## Natural Key Naming Convention

- **Frequency**: Found in ALL analyzed repositories
- **Why It's Common**: Eliminates key collisions without complex namespacing, reduces cognitive load, makes workflows self-documenting
- **Variations**:
  - Simple descriptive keys: `shared["content"]`, `shared["response"]`
  - Purpose-based keys: `shared["file_path"]`, `shared["issue_data"]`
  - Nested structures for complex data: `shared["config"]["max_retries"]`
- **Best Implementation**: Use intuitive names that describe data purpose, not origin
- **pflow Recommendation**: Enforce natural naming in documentation and examples. Make proxy pattern a last resort.
- **Tasks Benefited**:
  - Task 9 (Shared Store & Proxy) - Natural keys eliminate most proxy needs
  - Task 3 (Hello World) - Sets pattern from the start
  - All node implementation tasks (11-14, 25-29)

## Single-Purpose Node Design

- **Frequency**: Found in ALL analyzed repositories
- **Why It's Common**: Maintains clarity, testability, reusability. Unix philosophy applied to workflows.
- **Variations**:
  - Pure transformation nodes (input → output)
  - Side-effect nodes (file writes, API calls)
  - Validation nodes (check preconditions)
- **Best Implementation**: Each node does ONE thing well with clear input/output contract
- **pflow Recommendation**: Enforce through node templates and registry validation
- **Tasks Benefited**:
  - Task 11 (File I/O Nodes) - Template for all simple nodes
  - Task 12 (LLM Node) - Single responsibility pattern
  - Task 13 (GitHub Node) - Focused external API interaction
  - All future node implementations

## Structured LLM Communication (YAML Format)

- **Frequency**: 6 out of 7 repositories
- **Why It's Common**: YAML is more readable than JSON for LLMs, more reliable parsing, supports multi-line strings naturally
- **Variations**:
  - Simple key-value responses
  - Complex nested structures with lists
  - Multi-section documents with markdown content
- **Best Implementation**: YAML with explicit schema definition in prompt
- **pflow Recommendation**: Standardize on YAML for ALL structured LLM output
- **Tasks Benefited**:
  - Task 12 (LLM Node) - Reliable parsing approach
  - Task 17 (LLM Workflow Generation) - IR generation format
  - Task 18 (Prompt Templates) - Structured output templates

## Progressive State Building

- **Frequency**: Found in ALL analyzed repositories
- **Why It's Common**: Enables debugging, tracing, and checkpoint/resume. Natural audit trail.
- **Variations**:
  - Simple append-only pattern
  - Timestamped entries
  - Nested state sections
- **Best Implementation**: Each node adds new keys without removing existing data
- **pflow Recommendation**: Make this the default pattern, document as best practice
- **Tasks Benefited**:
  - Task 23 (Execution Tracing) - Natural audit trail
  - Task 3 (Execute Workflow) - State evolution pattern
  - Task 24 (Caching) - Checkpoint/resume capability

## Early Parameter Validation (Fail-Fast)

- **Frequency**: Found in ALL analyzed repositories
- **Why It's Common**: Prevents wasted computation, provides clear error messages, improves debugging
- **Variations**:
  - Required parameter checks
  - Type validation
  - Format validation (regex patterns)
  - Range/boundary checks
- **Best Implementation**: Validate in prep() phase with descriptive error messages
- **pflow Recommendation**: Make validation a required part of node template
- **Tasks Benefited**:
  - Task 9 (Shared Store Validation) - Input validation patterns
  - All node implementation tasks - Error handling pattern
  - Task 8 (Shell Integration) - Validate stdin data

## Deterministic Execution Configuration

- **Frequency**: Found in ALL repositories using LLMs
- **Why It's Common**: Enables caching, reproducible results, debugging, testing
- **Variations**:
  - Temperature=0 for LLM calls
  - Fixed seeds where supported
  - Sorted operations (file lists, etc.)
  - Stable defaults for missing values
- **Best Implementation**: All randomness removed or controlled by configuration
- **pflow Recommendation**: Enforce determinism by default, randomness only when explicitly configured
- **Tasks Benefited**:
  - Task 12 (LLM Node) - Deterministic by default
  - Task 24 (Caching) - Cache key generation
  - Task 17 (Workflow Generation) - Reproducible workflows

## Built-in Retry with Exponential Backoff

- **Frequency**: 5 out of 7 repositories
- **Why It's Common**: Handles transient failures gracefully, essential for external API calls
- **Variations**:
  - Simple retry count
  - Exponential backoff timing
  - Retry with different parameters
  - Circuit breaker patterns
- **Best Implementation**: Configure at node instantiation, not runtime
- **pflow Recommendation**: Built into base node class, configurable per instance
- **Tasks Benefited**:
  - Task 12 (LLM Node) - Handle API failures
  - Task 13 (GitHub Node) - Network reliability
  - Task 25 (Claude-code Node) - Rate limit handling

## Comprehensive Execution Logging

- **Frequency**: Found in ALL analyzed repositories
- **Why It's Common**: Essential for debugging, monitoring, and understanding workflow behavior
- **Variations**:
  - Simple print statements
  - Structured logging with levels
  - Context-aware logging (node name, phase)
  - Performance metrics logging
- **Best Implementation**: Structured logging with consistent format and context
- **pflow Recommendation**: Built-in logging with node context, configurable verbosity
- **Tasks Benefited**:
  - Task 23 (Execution Tracing) - Foundation for trace system
  - All node tasks - Standard logging pattern
  - Task 2 (CLI Setup) - Log level configuration

## Content-Based Caching

- **Frequency**: 4 out of 7 repositories
- **Why It's Common**: Dramatically improves performance, reduces API costs, enables offline work
- **Variations**:
  - File-based cache with hash keys
  - In-memory cache for current execution
  - Time-based cache expiration
  - Size-limited caches
- **Best Implementation**: Hash-based file cache with content addressing
- **pflow Recommendation**: Optional but encouraged, especially for LLM nodes
- **Tasks Benefited**:
  - Task 24 (Caching System) - Core implementation
  - Task 12 (LLM Node) - Avoid redundant API calls
  - Task 13 (GitHub Node) - Cache API responses

## CLI-to-Shared-Store Direct Mapping

- **Frequency**: 4 out of 7 repositories (all CLI tools)
- **Why It's Common**: Clean, predictable mapping from command line to workflow state
- **Variations**:
  - Direct flag mapping
  - Nested configuration from files
  - Environment variable integration
  - stdin handling patterns
- **Best Implementation**: CLI arguments map directly to shared store keys
- **pflow Recommendation**: Standardize this pattern for all CLI commands
- **Tasks Benefited**:
  - Task 2 (CLI Setup) - Argument handling pattern
  - Task 8 (Shell Integration) - stdin integration
  - Task 3 (Hello World) - Initial pattern example

## History-Based Debugging

- **Frequency**: 3 out of 7 repositories
- **Why It's Common**: Provides complete execution history for debugging complex workflows
- **Variations**:
  - Simple action list
  - Timestamped events
  - Full state snapshots
  - Structured trace data
- **Best Implementation**: Lightweight append-only list with essential data
- **pflow Recommendation**: Build into execution engine as opt-in feature
- **Tasks Benefited**:
  - Task 23 (Execution Tracing) - Core trace structure
  - Task 9 (Shared Store) - Debug information pattern
  - Task 24 (Caching) - Execution history for cache keys

## Template Variable Resolution

- **Frequency**: 3 out of 7 repositories
- **Why It's Common**: Enables dynamic prompts and configuration without code changes
- **Variations**:
  - Simple string replacement ($var syntax)
  - Jinja2-style templates
  - Python string formatting
  - Nested template resolution
- **Best Implementation**: Simple $variable replacement from shared store
- **pflow Recommendation**: Support simple variable substitution in prompts and parameters
- **Tasks Benefited**:
  - Task 19 (Template Resolver) - Core implementation
  - Task 18 (Prompt Templates) - Template usage
  - Task 17 (Workflow Generation) - Dynamic prompts

## Summary: MVP Pattern Priorities

For pflow's MVP, prioritize these patterns in order:

1. **Natural Key Naming** - Eliminates complexity from day one
2. **Single-Purpose Nodes** - Foundation for all node development
3. **Progressive State Building** - Enables debugging and tracing
4. **Early Validation** - Better user experience, faster failure
5. **Structured LLM Output (YAML)** - Reliable LLM integration
6. **Deterministic Execution** - Enables caching and testing

These patterns appear universally because they solve fundamental problems in workflow systems:
- **Simplicity** over clever abstractions
- **Debuggability** through transparency
- **Reliability** through validation and retries
- **Performance** through caching and minimal overhead
- **Usability** through clear errors and natural interfaces

The most successful PocketFlow applications use these patterns consistently, suggesting pflow should embed them deeply into its architecture rather than treating them as optional best practices.
