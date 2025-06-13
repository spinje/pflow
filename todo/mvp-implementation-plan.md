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

## 📋 Phase 1: Core Infrastructure (Weeks 1-2)

### 1.1 Project Structure Setup
- [ ] **Create main CLI entry point** (`src/pflow/cli.py`)
  - Basic click-based CLI framework
  - Simple `--key=value` flag parsing (no sophisticated categorization)
  - Route to workflow execution handlers
- [ ] **Set up core package structure**
  - `src/pflow/core/` - Core runtime components
  - `src/pflow/registry/` - Node discovery and metadata
  - `src/pflow/nodes/` - Built-in platform nodes
  - `src/pflow/planning/` - Natural language planning (Phase 4)
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
- [ ] **Simple CLI flag resolution** (`src/pflow/core/cli_resolver.py`)
  - Basic `--key=value` parsing without sophisticated categorization
  - Manual parameter specification required
  - Shell pipe input detection and `shared["stdin"]` handling

### 1.3 Simple Node Registry
- [ ] **Registry structure** (`src/pflow/registry/`)
  - Simple file-based node discovery (no versioning in MVP)
  - Metadata extraction from docstrings
  - Basic indexing for fast lookups
- [ ] **Complete JSON IR system** (`src/pflow/core/ir_schema.py`)
  - Full schema with proxy mapping support
  - Node specifications with action dispatch
  - Edge definitions and mapping specifications
  - Provenance tracking and metadata inclusion
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

## 📋 Phase 2: Metadata & Registry Systems (Weeks 3-4)

### 2.1 Comprehensive Metadata Extraction
- [ ] **Docstring parsing system** (`src/pflow/registry/metadata_extractor.py`)
  - Full `docstring_parser` + custom regex implementation
  - Parse Interface sections with action-specific parameters
  - Extract inputs, outputs, params, actions per action
  - Support both simple and structured Interface formats
- [ ] **Action-specific parameter mapping**
  - Parameter availability mapping per action
  - Global parameters available across all actions
  - Validation of parameter consistency
- [ ] **JSON metadata generation**
  - Schema-compliant metadata for each node
  - Source hash computation for staleness detection
  - Extraction timestamp and version tracking

### 2.2 Enhanced Registry Infrastructure
- [ ] **Metadata indexing system** (`src/pflow/registry/index.py`)
  - Fast lookups by node ID and capabilities
  - Interface compatibility analysis
  - Action discovery and validation
- [ ] **Registry CLI commands** (`src/pflow/cli/registry.py`)
  - `pflow registry list` - Show platform nodes with actions
  - `pflow registry describe <node>` - Detailed node information
  - Rich formatting with action-specific parameters
- [ ] **Metadata validation**
  - Verify extracted metadata against actual code
  - Consistency checking for interface definitions
  - Error reporting for metadata mismatches

### 2.3 Interface Compatibility System
- [ ] **Compatibility analysis** (`src/pflow/core/compatibility.py`)
  - Shared store key matching between nodes
  - Type validation for interface connections
  - Proxy mapping generation for mismatches
- [ ] **Validation framework**
  - Pre-execution workflow validation
  - Parameter type checking
  - Action availability verification
- [ ] **Registry integration tests**
  - Test metadata extraction from real nodes
  - Validate registry CLI operations
  - Interface compatibility validation scenarios

---

## 📋 Phase 3: Action-Based Platform Nodes (Weeks 5-6)

### 3.1 GitHub Platform Node
- [ ] **GitHub node implementation** (`src/pflow/nodes/github.py`)
  - Action dispatch pattern with `self.params.get("action")`
  - Actions: `get-issue`, `create-issue`, `list-prs`, `create-pr`, `get-files`, `merge-pr`, `add-comment`
  - Natural interface: `shared["repo"]`, `shared["issue"]`, `shared["pr"]`, `shared["files"]`
  - Action-specific parameter handling
- [ ] **GitHub API integration**
  - PyGithub or requests-based implementation
  - Authentication via environment variables
  - Error handling for API failures and rate limits
- [ ] **GitHub node tests**
  - Mock GitHub API responses for each action
  - Test action dispatch and parameter routing
  - Integration tests with real GitHub API (optional)

### 3.2 Claude Platform Node
- [ ] **Claude node implementation** (`src/pflow/nodes/claude.py`)
  - Action dispatch pattern with multiple AI capabilities
  - Actions: `analyze`, `implement`, `review`, `explain`, `refactor`
  - Natural interface: `shared["code"]`, `shared["prompt"]` → `shared["result"]`
  - Integration with headless claude-code CLI for implement action
- [ ] **Action-specific implementations**
  - `analyze`: Code analysis and understanding
  - `implement`: Code generation and implementation
  - `review`: Code review and suggestions
  - `explain`: Code explanation and documentation
- [ ] **Claude node tests**
  - Mock claude-code CLI responses per action
  - Test action dispatch and safety measures
  - Validate output formats for each action

### 3.3 CI Platform Node
- [ ] **CI node implementation** (`src/pflow/nodes/ci.py`)
  - Action dispatch for continuous integration operations
  - Actions: `run-tests`, `get-status`, `trigger-build`, `get-logs`
  - Natural interface: `shared["test_command"]` → `shared["test_results"]`
  - Support multiple CI systems (GitHub Actions, local, etc.)
- [ ] **Framework detection and execution**
  - Auto-detect test frameworks (pytest, npm test, etc.)
  - Handle different exit codes and result formats
  - Configuration file detection and handling
- [ ] **CI node tests**
  - Mock test framework responses
  - Test action dispatch for different CI operations
  - Error handling for failed tests and builds

### 3.4 Git Platform Node
- [ ] **Git node implementation** (`src/pflow/nodes/git.py`)
  - Action dispatch for git operations
  - Actions: `commit`, `push`, `create-branch`, `merge`, `status`
  - Natural interface: `shared["changes"]` → `shared["commit_hash"]`
  - Automatic commit message generation for commit action
- [ ] **Git operations implementation**
  - Safety checks and confirmation prompts
  - Branch management and merging
  - Status reporting and change detection
- [ ] **Git node tests**
  - Mock git commands and responses
  - Test action dispatch and safety measures
  - Integration tests with real git repositories

### 3.5 File and Shell Platform Nodes
- [ ] **File node implementation** (`src/pflow/nodes/file.py`)
  - Actions: `read`, `write`, `copy`, `move`, `delete`
  - Natural interface: `shared["file_path"]`, `shared["content"]`
  - Safety checks for destructive operations
- [ ] **Shell node implementation** (`src/pflow/nodes/shell.py`)
  - Actions: `exec`, `pipe`, `background`
  - Natural interface: `shared["command"]` → `shared["output"]`
  - Timeout handling and security considerations
- [ ] **File and Shell tests**
  - Test action dispatch and parameter handling
  - Safety and security validation
  - Error handling for filesystem operations

---

## 📋 Phase 4: Natural Language Planning (Weeks 7-8)

### 4.1 LLM Integration Infrastructure
- [ ] **LLM client abstraction** (`src/pflow/planning/llm_client.py`)
  - Support for thinking models (Claude, OpenAI o1)
  - Token usage tracking and optimization
  - Error handling and retry logic
- [ ] **Prompt engineering system** (`src/pflow/planning/prompts.py`)
  - Node selection prompts with metadata context
  - Workflow generation prompts using extracted metadata
  - Error recovery and retry prompts
- [ ] **Model configuration**
  - Environment variable setup for API keys
  - Model selection logic (default to Claude Sonnet)
  - Fallback strategies for model failures

### 4.2 Metadata-Driven Planning
- [ ] **Planning context builder** (`src/pflow/planning/context_builder.py`)
  - Load available node metadata into LLM context
  - Generate compact, LLM-optimized descriptions
  - Include action-specific parameter information
- [ ] **Node selection engine** (`src/pflow/planning/node_selector.py`)
  - Intelligent node selection based on user intent
  - Use extracted metadata for compatibility checking
  - Validation of selected nodes and interfaces
- [ ] **Workflow generation** (`src/pflow/planning/flow_generator.py`)
  - Natural language → action-based CLI syntax compilation
  - Parameter inference using metadata
  - Basic linear workflows (A >> B >> C)

### 4.3 User Approval & Workflow Storage
- [ ] **User verification system** (`src/pflow/planning/approval.py`)
  - Show generated CLI workflow for approval
  - Allow parameter modifications before execution
  - Clear presentation of action-based syntax
- [ ] **Workflow storage system** (`src/pflow/core/workflow_storage.py`)
  - Save approved workflows with meaningful names
  - Local filesystem storage (~/.pflow/workflows/)
  - Workflow discovery and reuse
- [ ] **Pattern recognition**
  - Intelligent reuse of existing workflow definitions
  - Parameter extraction for similar requests
  - "Plan Once, Run Forever" optimization

### 4.4 End-to-End Integration & Validation
- [ ] **Complete planning pipeline** (`src/pflow/planning/planner.py`)
  - Natural language input → validated workflow
  - Integration with metadata systems
  - Performance optimization (≤800ms planning latency)
- [ ] **Planning validation tests**
  - Test common development workflow descriptions
  - Validate generated action-based CLI syntax
  - Success rate measurement (≥95% target)
- [ ] **User acceptance testing**
  - Real developer workflow scenarios
  - Approval rate measurement (≥90% target)
  - Performance benchmarking vs slash commands

---

## 🧪 Validation and Testing Strategy

### Unit Tests (Per Phase)
- [ ] **Foundation tests** (Phase 1)
  - Shared store functionality
  - CLI flag resolution
  - Node registry operations
- [ ] **Metadata tests** (Phase 2)
  - Docstring parsing and extraction
  - Registry operations and indexing
  - Interface compatibility validation
- [ ] **Node tests** (Phase 3)
  - Each developer node functionality
  - Error handling and edge cases
  - Integration with external services
- [ ] **Planning tests** (Phase 4)
  - LLM integration and prompt engineering
  - Natural language workflow generation
  - User approval and workflow storage

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
   # → Generates: github --action=get-issue >> claude --action=analyze >> claude --action=implement
   ```

2. **Execute saved workflows with parameters**:
   ```bash
   pflow analyze-issue --issue=1234 --repo=myproject
   ```

3. **Get better observability than slash commands**:
   ```bash
   pflow trace run_2024-01-01_abc123
   # Shows: Step 1: github --action=get-issue ✓ (0.2s), Step 2: claude --action=analyze ✓ (3.1s), etc.
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
2. **Action-based platform nodes** - Reduce cognitive load vs function-specific nodes
3. **Dependencies-first build order** - Infrastructure before natural language planning
4. **Simple flag parsing in MVP** - Basic `--key=value` without sophisticated categorization
5. **Comprehensive metadata extraction** - Rich docstring parsing for planning
6. **Complete IR with proxy mappings** - Future extensibility built-in
7. **Natural shared store interfaces** - Intuitive key names for simplicity

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
