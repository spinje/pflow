# pflow MVP Implementation Plan: AI-Assisted Development Workflow Compiler

This document breaks down the MVP implementation into specific, actionable tasks organized by phases and priorities.

## 🎯 MVP Goal Reminder

**Transform AI-assisted development workflows from inefficient slash commands into deterministic, reusable CLI workflows**

Target transformation:
```bash
# From: /project:fix-github-issue 1234 (30-90s, variable, token-heavy)
# To: pflow fix-issue --issue=1234 (2-5s, consistent, token-efficient)
```

---

## 📋 Phase 1: Foundation (Weeks 1-2)

### 1.1 Project Structure Setup
- [ ] **Create main CLI entry point** (`src/pflow/cli.py`)
  - Basic click-based CLI framework
  - Handle natural language input detection
  - Route to appropriate handlers
- [ ] **Set up core package structure**
  - `src/pflow/core/` - Core runtime components
  - `src/pflow/planning/` - Natural language planning engine
  - `src/pflow/nodes/` - Built-in developer nodes
  - `src/pflow/registry/` - Node discovery and metadata
- [ ] **Integration with pocketflow**
  - Import and verify pocketflow framework works
  - Create base classes that extend pocketflow patterns
  - Test basic node execution with shared store

### 1.2 Basic Shared Store Implementation
- [ ] **Core shared store class** (`src/pflow/core/shared_store.py`)
  - Simple dictionary-based implementation
  - Reserved key handling (`shared["stdin"]`)
  - Validation for natural key patterns
- [ ] **NodeAwareSharedStore proxy** (`src/pflow/core/proxy.py`)
  - Transparent key mapping when needed
  - Zero overhead when no mappings defined
  - Integration with pocketflow node execution
- [ ] **Basic CLI flag resolution** (`src/pflow/core/cli_resolver.py`)
  - "Type flags; engine decides" algorithm
  - Data injection vs params vs execution config
  - Shell pipe input detection and handling

### 1.3 Simple Node Registry
- [ ] **Registry structure** (`src/pflow/registry/`)
  - File-based node discovery
  - Metadata extraction from docstrings
  - Basic indexing for fast lookups
- [ ] **Node metadata schema**
  - JSON schema for node interface definitions
  - Input/output key specifications
  - Action definitions and parameter schemas
- [ ] **Registry CLI commands**
  - `pflow registry list` - Show available nodes
  - `pflow registry describe <node>` - Show node details

### 1.4 Basic Testing Infrastructure
- [ ] **Test framework setup**
  - pytest configuration for project
  - Test utilities for shared store and node testing
  - Mock/stub helpers for external services
- [ ] **Foundation component tests**
  - Shared store functionality
  - CLI flag resolution
  - Node registry operations

---

## 📋 Phase 2: Natural Language Planning (Weeks 3-4)

### 2.1 LLM Integration Infrastructure
- [ ] **LLM client abstraction** (`src/pflow/planning/llm_client.py`)
  - Support for multiple models (Claude, OpenAI o1)
  - Thinking model integration for complex reasoning
  - Token usage tracking and optimization
- [ ] **Prompt engineering system** (`src/pflow/planning/prompts.py`)
  - Node selection prompts with metadata context
  - Workflow generation prompts
  - Error recovery and retry prompts
- [ ] **Model configuration**
  - Environment variable setup for API keys
  - Model selection logic (default to Claude Sonnet)
  - Fallback strategies for model failures

### 2.2 Metadata-Driven Node Selection
- [ ] **Metadata extraction system** (`src/pflow/planning/metadata_extractor.py`)
  - Parse node docstrings for interface definitions
  - Extract inputs, outputs, params, actions
  - Generate JSON metadata for LLM context
- [ ] **Node selection engine** (`src/pflow/planning/node_selector.py`)
  - Load available node metadata into LLM context
  - Intelligent node selection based on user intent
  - Validation of selected nodes and compatibility
- [ ] **Selection validation**
  - Verify selected nodes exist in registry
  - Check interface compatibility between nodes
  - Generate error messages for invalid selections

### 2.3 Workflow Generation
- [ ] **Flow structure generator** (`src/pflow/planning/flow_generator.py`)
  - Natural language → node sequence transformation
  - Basic linear workflows (A >> B >> C)
  - Parameter inference and default value assignment
- [ ] **CLI syntax compiler** (`src/pflow/planning/cli_compiler.py`)
  - JSON IR → CLI pipe syntax conversion
  - Natural parameter naming for user readability
  - User-friendly workflow previews
- [ ] **User verification system**
  - Show generated CLI workflow for approval
  - Allow parameter modifications before execution
  - Save approved workflows with meaningful names

### 2.4 Planning Pipeline Integration
- [ ] **End-to-end planning flow** (`src/pflow/planning/planner.py`)
  - Natural language input → validated workflow
  - Error handling and retry logic
  - Integration with workflow storage
- [ ] **Planning tests**
  - Test common development workflow descriptions
  - Validate generated CLI syntax
  - Error recovery scenarios

---

## 📋 Phase 3: Developer Nodes (Weeks 5-6)

### 3.1 GitHub Integration Node
- [ ] **GitHub node implementation** (`src/pflow/nodes/github.py`)
  - Actions: `view`, `create`, `comment`, `close` for issues
  - Actions: `list-prs`, `create-pr`, `merge-pr` for pull requests
  - Natural interface: `shared["repo"]`, `shared["issue"]`, `shared["pr"]`
- [ ] **GitHub API integration**
  - PyGithub or requests-based implementation
  - Authentication via environment variables
  - Error handling for API failures and rate limits
- [ ] **GitHub node tests**
  - Mock GitHub API responses
  - Test all supported actions
  - Integration tests with real GitHub API (optional)

### 3.2 Claude Code Integration Nodes
- [ ] **claude-analyze node** (`src/pflow/nodes/claude_analyze.py`)
  - One-shot analysis with focused context
  - Natural interface: `shared["code"]` → `shared["analysis"]`
  - Integration with headless claude-code CLI
- [ ] **claude-implement node** (`src/pflow/nodes/claude_implement.py`)
  - Code implementation with specific instructions
  - Natural interface: `shared["requirements"]` → `shared["code"]`
  - Dry-run support and safety measures
- [ ] **Claude Code node tests**
  - Mock claude-code CLI responses
  - Test safety measures and error handling
  - Validate output formats and interfaces

### 3.3 Development Tool Nodes
- [ ] **run-tests node** (`src/pflow/nodes/run_tests.py`)
  - Support multiple test frameworks (pytest, npm test, etc.)
  - Natural interface: `shared["test_command"]` → `shared["test_results"]`
  - Exit code handling and result parsing
- [ ] **lint node** (`src/pflow/nodes/lint.py`)
  - Support multiple linters (eslint, ruff, etc.)
  - Natural interface: `shared["lint_command"]` → `shared["lint_results"]`
  - Configuration file detection and handling
- [ ] **git-commit node** (`src/pflow/nodes/git_commit.py`)
  - Automatic commit message generation
  - Natural interface: `shared["changes"]` → `shared["commit_hash"]`
  - Safety checks and confirmation prompts

### 3.4 Shell Integration
- [ ] **shell-exec node** (`src/pflow/nodes/shell_exec.py`)
  - Execute arbitrary shell commands safely
  - Natural interface: `shared["command"]` → `shared["output"]`
  - Timeout handling and error reporting
- [ ] **Shell integration tests**
  - Test command execution and output capture
  - Error handling for failed commands
  - Security considerations and input validation

---

## 📋 Phase 4: Workflow Management (Weeks 7-8)

### 4.1 JSON IR System
- [ ] **IR schema definition** (`src/pflow/core/ir_schema.py`)
  - Complete JSON schema for workflow definitions
  - Node specifications with params and execution config
  - Edge definitions and mapping specifications
- [ ] **IR generation and validation** (`src/pflow/core/ir_generator.py`)
  - Convert planning output to validated JSON IR
  - Schema validation and error reporting
  - Provenance tracking and metadata inclusion
- [ ] **IR serialization and storage**
  - Save/load IR definitions
  - Version compatibility checking
  - Migration support for schema updates

### 4.2 Workflow Storage and Execution
- [ ] **Workflow storage system** (`src/pflow/core/workflow_storage.py`)
  - Save workflows with meaningful names
  - Local filesystem storage (~/.pflow/workflows/)
  - Workflow discovery and listing
- [ ] **Parameterized execution** (`src/pflow/core/executor.py`)
  - Load saved workflows with parameter overrides
  - CLI flag resolution and shared store population
  - Integration with pocketflow execution engine
- [ ] **Lockfile generation** (`src/pflow/core/lockfile.py`)
  - Generate deterministic lockfiles for reproducibility
  - Version pinning and hash validation
  - Signature verification for modified workflows

### 4.3 Execution Tracing and Observability
- [ ] **Execution tracing system** (`src/pflow/core/tracer.py`)
  - Step-by-step execution logging
  - Node input/output capture
  - Performance metrics and timing
- [ ] **Trace analysis and debugging** (`src/pflow/core/trace_analyzer.py`)
  - `pflow trace <run-id>` command implementation
  - Error correlation and debugging aids
  - Performance analysis and bottleneck identification
- [ ] **Observability dashboard** (CLI-based)
  - Execution history and statistics
  - Performance trends and optimization suggestions
  - Error patterns and resolution guidance

### 4.4 End-to-End Integration
- [ ] **Complete CLI integration** (`src/pflow/cli.py`)
  - Natural language workflow generation
  - Saved workflow execution
  - Registry management commands
  - Tracing and debugging commands
- [ ] **Integration tests**
  - End-to-end workflow generation and execution
  - Real GitHub and development tool integration
  - Performance benchmarking against slash commands
- [ ] **Documentation and examples**
  - User guide with real development scenarios
  - Example workflows for common tasks
  - Troubleshooting guide and FAQ

---

## 🧪 Validation and Testing Strategy

### Unit Tests (Per Phase)
- [ ] **Foundation tests** (Phase 1)
  - Shared store functionality
  - CLI flag resolution
  - Node registry operations
- [ ] **Planning tests** (Phase 2)
  - LLM integration and prompt engineering
  - Node selection and validation
  - Workflow generation and compilation
- [ ] **Node tests** (Phase 3)
  - Each developer node functionality
  - Error handling and edge cases
  - Integration with external services
- [ ] **Workflow tests** (Phase 4)
  - IR generation and validation
  - Workflow storage and execution
  - Tracing and observability

### Integration Tests
- [ ] **End-to-end workflow tests**
  - Generate workflows from natural language
  - Execute workflows with real tools
  - Validate output quality and performance
- [ ] **Performance benchmarks**
  - Planning latency measurements
  - Execution speed comparisons
  - Token usage optimization validation
- [ ] **Error recovery tests**
  - Invalid input handling
  - External service failures
  - Partial execution scenarios

### User Validation
- [ ] **Developer workflow scenarios**
  - GitHub issue analysis and resolution
  - Code review and testing workflows
  - Deployment and monitoring tasks
- [ ] **Slash command comparison**
  - Side-by-side efficiency demonstrations
  - Token usage and time savings measurements
  - User experience improvements
- [ ] **Team sharing validation**
  - Workflow portability between developers
  - Team adoption and usage patterns
  - Knowledge transfer and learning curves

---

## 📊 Success Metrics and Acceptance Criteria

### Technical Metrics
- [ ] **Planning Success Rate**: ≥95% of reasonable requests generate valid workflows
- [ ] **Execution Reliability**: ≥98% of valid workflows execute successfully
- [ ] **Planning Latency**: ≤800ms average for natural language → validated IR
- [ ] **Execution Speed**: ≤2s overhead vs raw Python for 3-node flows
- [ ] **Registry Scale**: Support ≥50 developer-focused nodes efficiently

### User Value Metrics
- [ ] **Efficiency Gain**: 10x improvement over slash commands (tokens + time)
- [ ] **User Adoption**: ≥90% approval rate for generated workflows
- [ ] **Workflow Reuse**: Saved workflows used multiple times per week
- [ ] **Team Sharing**: Workflows shared and adopted across development teams

### Capability Demonstrations
- [ ] **Natural Language Processing**: `pflow "fix this issue, test it, create PR"`
- [ ] **Workflow Reuse**: `pflow fix-issue --issue=1234 --severity=critical`
- [ ] **Developer Integration**: Works with existing GitHub/testing/linting workflows
- [ ] **Slash Command Migration**: Existing `.claude/commands/*.md` can be transformed

---

## 🚀 MVP Acceptance Criteria

**The MVP is complete when developers can successfully**:

1. **Generate workflows from natural language**:
   ```bash
   pflow "analyze this github issue and suggest a fix"
   # → Generates: gh-issue --action=view >> claude-analyze >> claude-implement
   ```

2. **Execute saved workflows with parameters**:
   ```bash
   pflow analyze-issue --issue=1234 --repo=myproject
   ```

3. **Get better observability than slash commands**:
   ```bash
   pflow trace run_2024-01-01_abc123
   # Shows: Step 1: gh-issue ✓ (0.2s), Step 2: claude-analyze ✓ (3.1s), etc.
   ```

4. **Achieve 10x efficiency improvement** over equivalent slash commands in terms of:
   - Execution time (consistent 2-5s vs variable 30-90s)
   - Token usage (minimal overhead vs 1000-2000 tokens per run)
   - Reliability (deterministic vs variable approaches)

**When these criteria are met, pflow MVP delivers transformational value to AI-assisted development workflows.**

---

## 📝 Implementation Notes

### Key Architectural Decisions
1. **Use pocketflow as foundation** - Leverage existing 100-line framework
2. **Impure nodes by default** - Realistic for development workflows
3. **General nodes with actions** - Reduce cognitive load vs specific nodes
4. **Natural shared store interfaces** - Intuitive key names for simplicity
5. **Metadata-driven planning** - Fast node selection without code inspection

### Critical Dependencies
1. **LLM access** - Claude/OpenAI API keys for planning
2. **GitHub access** - For realistic development workflow testing
3. **Claude Code CLI** - For AI-assisted coding node integration
4. **Development tools** - Git, test frameworks, linters for validation

### Risk Mitigation
1. **Start simple** - Linear workflows before complex branching
2. **Mock external services** - Reduce dependencies during development
3. **Incremental validation** - Test each phase thoroughly before proceeding
4. **User feedback early** - Validate assumptions with real developers

This implementation plan transforms pflow from a generic workflow tool into a focused solution for AI-assisted development workflow efficiency.
