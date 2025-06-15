# pflow MVP Implementation Plan: AI-Assisted Development Workflow Compiler

This document breaks down the MVP implementation into specific, actionable tasks organized by phases and priorities.

## 🎯 MVP Goal Reminder

**Transform AI-assisted development workflows from inefficient slash commands into deterministic, reusable CLI workflows**

Target transformation:
```bash
# From: /project:fix-github-issue 1234 (30-90s, variable, token-heavy)
# To: pflow fix-issue --issue=1234 (2-5s, consistent, token-efficient)
# Under the hood fix-issue is a deterministic template-driven workflow:
```bash
github-get-issue >> \
claude-code --prompt="<generated_instructions>" >> \
llm --prompt="Write commit message for: $code_report" >> \
git-commit --message="$commit_message" >> \
git-push >> \
github-create-pr --title="Fix: $issue_title" --body="$code_report"
```

**Core Architecture**: Template-driven workflows with context-aware parameter resolution, $ variable substitution, and planner-generated prompts.

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
- [ ] **Context-aware CLI parameter resolution** (`src/pflow/core/cli_resolver.py`)
  - Basic `--key=value` parsing with context-aware routing
  - Data flags → shared store (`--issue=1234` → `shared["issue_number"]`)
  - Behavior flags → node.set_params() (`--temperature=0.3` → `node.set_params({"temperature": 0.3})`)
  - Shell pipe input detection and `shared["stdin"]` handling
  - JSON IR → compiled Python code execution pipeline
- [ ] **Template resolution system** (`src/pflow/core/template_resolver.py`)
  - $ variable substitution engine (`$code_report`, `$commit_message`, etc.)
  - Automatic mapping from shared store keys to template variables
  - Template validation and error handling for missing variables
  - Missing input detection and user prompting (especially for first nodes expecting user input)
- [ ] **Shared store inspection utilities** (`src/pflow/core/inspector.py`)
  - `pflow inspect shared-store` - Show current shared store state
  - `pflow inspect params --node=<node>` - Show node parameters
  - `pflow inspect template-vars` - Show available template variables
    ```bash
    # Example output:
    # Available template variables:
    #   $issue - GitHub issue content (from: github-get-issue)
    #   $code_report - Development report (from: claude-code)
    #   $commit_message - Generated message (from: llm)
    ```

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
- [ ] **Enhanced docstring parsing system** (`src/pflow/registry/metadata_extractor.py`)
  - Full `docstring_parser` + custom regex implementation
  - Parse Interface sections with parameter type classification
  - Extract inputs, outputs, data_params, behavior_params for each node
  - Support both simple and structured Interface formats
  - Template variable tracking (which keys nodes produce/consume)
- [ ] **Parameter classification system**
  - Distinguish data parameters (→ shared store) from behavior parameters (→ node.set_params())
  - Parameter availability mapping per individual node
  - Global parameters available across all nodes in a flow
  - Template variable dependency mapping
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
  - `pflow registry list` - Show individual platform nodes
  - `pflow registry describe <node>` - Detailed node information
  - Rich formatting with node-specific parameters
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

## 📋 Phase 3: Simple Platform Nodes (Weeks 5-6)

### 3.1 GitHub Platform Nodes
- [ ] **Individual GitHub node implementations** (`src/pflow/nodes/github/`)
  - Simple, single-purpose nodes: `github-get-issue`, `github-create-issue`, `github-list-prs`, `github-create-pr`, `github-get-files`, `github-merge-pr`, `github-add-comment`
  - Natural interface: `shared["repo"]`, `shared["issue"]`, `shared["pr"]`, `shared["files"]`
  - Clear, focused parameter handling per node
- [ ] **GitHub API integration**
  - PyGithub or requests-based implementation
  - Authentication via environment variables
  - Error handling for API failures and rate limits
- [ ] **GitHub node tests**
  - Mock GitHub API responses for each individual node
  - Test simple node interfaces and parameter handling
  - Integration tests with real GitHub API (optional)

### 3.2 Claude Code Super Node
- [ ] **Claude Code comprehensive node** (`src/pflow/nodes/claude_code.py`)
  - Single powerful node with instruction-based interface
  - Complex prompt generation with structured instructions
  - Project-aware AI with file system access and comprehensive development capabilities
  - Natural interface: `shared["prompt"]` → `shared["code_report"]` (comprehensive development report)
  - Integration with headless Claude Code CLI for full project context
- [ ] **Claude Code CLI integration**
  - Headless mode execution for workflow automation
  - Project context and file system access
  - Model selection and parameter handling
  - Structured output parsing for comprehensive development reports
- [ ] **Claude Code node tests**
  - Mock Claude Code CLI responses for comprehensive instructions
  - Test project context integration with complex multi-step instructions
  - Validate comprehensive development outputs and reports

### 3.3 LLM Node
- [ ] **General LLM node implementation** (`src/pflow/nodes/llm.py`)
  - Simple interface for general text processing and analysis
  - Natural interface: `shared["prompt"]` → `shared["response"]`
  - Integration with multiple LLM providers (Claude API, OpenAI, local models)
  - Used for prompt generation, log analysis, data processing
- [ ] **LLM integration implementations**
  - Claude via Anthropic API (for text processing, not development tasks)
  - OpenAI via OpenAI API
  - Simon Willison's `llm` CLI integration
  - Local model support for privacy-sensitive workflows
- [ ] **LLM node tests**
  - Mock LLM API responses for different providers
  - Test text processing and analysis capabilities
  - Validate output formats and error handling
  - Test log analysis and pattern recognition use cases

### 3.4 CI Platform Nodes
- [ ] **Individual CI node implementations** (`src/pflow/nodes/ci/`)
  - Simple nodes: `ci-run-tests`, `ci-get-status`, `ci-trigger-build`, `ci-get-logs`
  - Natural interface: `shared["test_command"]` → `shared["test_results"]`
  - Support multiple CI systems (GitHub Actions, local, etc.)
  - Each node focused on single CI operation
- [ ] **Framework detection and execution**
  - Auto-detect test frameworks (pytest, npm test, etc.)
  - Handle different exit codes and result formats
  - Configuration file detection and handling
- [ ] **CI node tests**
  - Mock test framework responses for each node
  - Test simple interfaces for different CI operations
  - Error handling for failed tests and builds

### 3.5 Git Platform Nodes
- [ ] **Individual Git node implementations** (`src/pflow/nodes/git/`)
  - Simple nodes: `git-commit`, `git-push`, `git-create-branch`, `git-merge`, `git-status`
  - Natural interface: `shared["changes"]` → `shared["commit_hash"]`
  - Automatic commit message generation for git-commit node
  - Each node focused on single git operation
- [ ] **Git operations implementation**
  - Safety checks and confirmation prompts
  - Branch management and merging
  - Status reporting and change detection
- [ ] **Git node tests**
  - Mock git commands and responses for each node
  - Test simple interfaces and safety measures
  - Integration tests with real git repositories

### 3.6 File and Shell Platform Nodes
- [ ] **Individual File node implementations** (`src/pflow/nodes/file/`)
  - Simple nodes: `read-file`, `write-file`, `copy-file`, `move-file`, `delete-file`
  - Natural interface: `shared["file_path"]`, `shared["content"]`
  - Safety checks for destructive operations
- [ ] **Individual Shell node implementations** (`src/pflow/nodes/shell/`)
  - Simple nodes: `shell-exec`, `shell-pipe`, `shell-background`
  - Natural interface: `shared["command"]` → `shared["output"]`
  - Timeout handling and security considerations
- [ ] **File and Shell tests**
  - Test simple interfaces and parameter handling
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
- [ ] **Sophisticated planning context builder** (`src/pflow/planning/context_builder.py`)
  - Load available node metadata with parameter classification
  - Generate compact, LLM-optimized descriptions
  - Include template variable mapping information
  - Context for prompt and instruction generation
- [ ] **Advanced workflow generation engine** (`src/pflow/planning/flow_generator.py`)
  - Natural language → template-driven CLI syntax compilation
  - Template string composition with embedded $variables for all node inputs
  - Automatic prompt and instruction generation for complex nodes
  - Parameter value generation (not just parameter inference)
  - Template variable creation and mapping ($code_report, $commit_message, etc.)
  - Context-aware parameter routing (data vs behavior)
  - Missing input detection and user prompting for required parameters
  - JSON IR → compiled Python code generation with template resolution

### 4.3 User Approval & Workflow Storage
- [ ] **User verification system** (`src/pflow/planning/approval.py`)
  - Show generated CLI workflow for approval
  - Allow parameter modifications before execution
  - Clear presentation of individual node syntax
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
  - Validate generated individual node CLI syntax
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

1. **Generate template-driven workflows from natural language**:
   ```bash
   # Primary workflow: GitHub issue resolution
   pflow "fix this github issue completely"
   # → Generates template-driven workflow:
  github-get-issue >> \
  claude-code --prompt="<instructions>
                          1. Understand the problem described in the issue
                          2. Search the codebase for relevant files
                          3. Implement the necessary changes to fix the issue
                          4. Write and run tests to verify the fix
                          5. Return a report of what you have done as output
                        </instructions>
                        This is the issue: $issue" >> \
  llm --prompt="Write a descriptive commit message for these changes: $code_report" >> \
  git-commit --message="$commit_message" >> \
  git-push >> \
  github-create-pr --title="Fix: $issue_title" --body="$code_report"
   ```

2. **Execute saved workflows with parameters**:
   ```bash
   pflow analyze-issue --issue=1234 --repo=myproject
   ```

3. **Get better observability than slash commands**:
   ```bash
   pflow trace run_2024-01-01_abc123
   # Primary workflow trace:
   #   Step 1: github-get-issue ✓ (0.2s)
   #   Step 2: claude-code ✓ (8.3s) [comprehensive development with template-driven instructions]
   #   Step 3: llm ✓ (1.2s) [commit message generation]
   #   Step 4: git-commit ✓ (0.1s)
   #   Step 5: github-create-pr ✓ (0.3s)
   # Secondary workflow trace: Step 1: read-file ✓ (0.1s), Step 2: llm ✓ (2.3s), Step 3: write-file ✓ (0.1s)
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
2. **Template-driven workflow architecture** - Planner does template string composition with embedded $variables, creating complete prompts like `"...This is the issue: $issue"` where variables resolve to shared store values at runtime
3. **Individual nodes + super nodes** - Simple nodes (`github-get-issue`) + powerful nodes (`claude-code`) with instruction-based interfaces
4. **Context-aware parameter resolution** - Data flags → shared store, behavior flags → node.set_params()
5. **JSON IR → compiled Python with templates** - CLI syntax → JSON IR → compiled Python code execution with template resolution
6. **Sophisticated planner** - Generates prompts, instructions, parameter values, and template mappings; detects missing inputs and prompts users (e.g., "Please provide --issue=<issue_number>")
7. **Shared store inspection capabilities** - Debug commands for transparency and workflow state inspection
8. **Two-tier AI approach** - Claude Code super node for comprehensive development, LLM node for text processing
9. **Core use case driven** - Primary focus on realistic end-to-end GitHub issue resolution workflow
10. **Dependencies-first build order** - Infrastructure before natural language planning
11. **Fail fast error handling** - Clear error messages, no complex retry mechanisms in MVP
12. **Environment variable authentication** - GITHUB_TOKEN, ANTHROPIC_API_KEY, etc.
13. **Enhanced metadata extraction** - Parameter classification (data vs behavior) and template variable tracking

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
