# MVP Implementation Guide: From Vision to Reality

## Navigation

**Quick Links**:
- [Executive Summary](#executive-summary)
- [Core Vision & Value Proposition](#core-vision--value-proposition)
- [MVP Feature Scope](#mvp-feature-scope)
- [Implementation Roadmap](#implementation-roadmap)
- [Success Metrics & Acceptance Criteria](#success-metrics--acceptance-criteria)
- [Technical Implementation Details](#technical-implementation-details)
- [Validation Strategy](#validation-strategy)
- [Launch Readiness](#launch-readiness)

**Related Documents**:
- **Architecture**: [PRD](../prd.md) | [Architecture](../architecture/architecture.md) | [Components](../architecture/components.md)
- **Patterns**: [Shared Store](../core-concepts/shared-store.md) | [Simple Nodes](./simple-nodes.md)
- **Planning**: [Natural Language Planner](./planner.md) | [Workflow Analysis](./workflow-analysis.md)
- **Integration**: [PocketFlow Integration Guide](../architecture/pflow-pocketflow-integration-guide.md)

---

## Executive Summary

pflow is an AI workflow compiler that transforms natural language and CLI pipe syntax into permanent, deterministic CLI commands, following a "Plan Once, Run Forever" philosophy.

**Key Facts**:
- **Scope**: 40 MVP tasks across 4 phases (8 tasks deferred to v2.0)
- **Timeline**: 9 weeks total (6-7 weeks with parallelization)
- **Core Innovation**: Natural Language Planner (Task 17) - THE feature that enables "find or build" workflows
- **Value Proposition**: 10x efficiency improvement over slash commands through workflow compilation and reuse

**What We're Building**: A system that transforms inefficient AI-assisted development from heavy slash commands into lightweight, deterministic CLI workflows that run forever after planning once.

---

## Core Vision & Value Proposition

### "Plan Once, Run Forever"

**Transform this inefficient pattern**:
```markdown
# Claude Code slash command - runs entire AI reasoning chain every time
/project:fix-github-issue 1234
# 50-90 seconds, 1000-2000 tokens, $0.10-2.00 per run
```

**Into this efficient workflow**:
```bash
# First run: AI plans the workflow (30s, ~$0.10)
pflow "fix github issue 1234"
# → Generates and saves workflow

# Every run after: Instant execution (2s, free)
pflow fix-issue --issue=1234
# → Executes deterministic workflow without AI overhead
```

### The Problem We're Solving

AI-assisted development workflows suffer from:
1. **Token Waste**: Re-reasoning through orchestration logic on every execution
2. **Time Inefficiency**: 30-90s for slash commands vs 2-5s for compiled workflows
3. **Unpredictability**: Variable approaches each time vs deterministic execution
4. **Poor Observability**: Conversation logs vs step-by-step execution traces

### Real-World Use Case

**Current Claude Code Slash Command** (from Anthropic blog post):
```markdown
/project:fix-github-issue 1234

Please analyze and fix the GitHub issue: $ARGUMENTS.

Follow these steps:
1. Use `gh issue view` to get the issue details
2. Understand the problem described in the issue
3. Search the codebase for relevant files
4. Implement the necessary changes to fix the issue
5. Write and run tests to verify the fix
6. Ensure code passes linting and type checking
7. Create a descriptive commit message
8. Push and create a PR
```

**pflow Transformation**:
```bash
# Natural language input
pflow "get github issue, analyze it, implement fix, test, and create PR"

# Generates deterministic workflow:
github-get-issue --issue=1234 >> \
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

# Saved as 'fix-issue' for instant reuse:
pflow fix-issue --issue=5678  # 20-50s vs 50-90s, minimal tokens
```

### Value for Different Users

1. **For Humans**: Never lose a script again. Your workflows are always one natural command away.
2. **For AI Agents**: Stop re-reasoning through repetitive tasks. Compile reasoning once, execute forever.
3. **The Hidden Gem**: Parameter handling - `pflow "analyze costs for last month"` uses the same workflow as `pflow "analyze costs for this week"`

---

## MVP Feature Scope

### ✅ What's Included (v0.1)

#### 1. Natural Language Planning Engine (Task 17) - THE Core Feature
**Purpose**: Transform natural language descriptions into deterministic CLI workflows

**Capabilities**:
- Input: `pflow "analyze github issue, search codebase, implement fix, test"`
- Output: Deterministic CLI workflow using developer-focused nodes
- Workflow discovery: Find existing workflows by semantic meaning
- LLM Integration: Use thinking models for intelligent node selection
- User verification: Show generated workflow for approval before execution

**Critical MVP Approach**:
```bash
# In MVP, everything after 'pflow' is natural language:
pflow "fix github issue 1234"
# → Entire string sent to LLM for interpretation

# Even with CLI-like syntax, it's still interpreted as natural language:
pflow read-file --path=data.txt => analyze => write report
# → LLM interprets this string and generates the workflow
```

#### 2. Developer-Focused Node Registry (Tasks 12-17, 25)

**Two-Tier AI Architecture**:
1. **Claude Code Super Node** (Task 25): Comprehensive AI agent with project context
   - Receives complex instructions with template variables
   - Returns detailed development reports: `shared["code_report"]`
   - Handles multi-step development tasks with file system access

2. **General LLM Node** (Task 12): Fast text processing without context
   - Simple prompts for commit messages, summaries
   - Quick responses without file system access: `shared["response"]`
   - Lightweight alternative to claude-code

**Core Simple Nodes** (Tasks 13-17):
- **GitHub**: `github-get-issue`, `github-create-pr` (Task 13)
- **File**: `read-file`, `write-file` (Task 14)
- **Git**: `git-commit`, `git-push` (Tasks 15-16)
- **Shell**: `shell-exec` (Task 17)

**Simple Node Philosophy**:
- Each node does ONE thing well
- Natural shared store keys (`shared["issue"]`, `shared["code_report"]`)
- Exception: general `llm` node to prevent prompt proliferation

#### 3. CLI Execution & Workflow Management (Tasks 2, 30-31)
- `pflow "natural language"` - Generate workflow from description
- `pflow <saved-workflow> --params` - Execute saved workflow
- `pflow registry list` - Show available nodes (Task 28)
- `pflow trace <run-id>` - Detailed execution debugging (Task 23)

#### 4. Foundation Infrastructure (Tasks 1-11)
- Package setup with CLI entry point (Task 1)
- Basic CLI for argument collection (Task 2)
- Integration test with hardcoded workflow (Task 3)
- Node discovery and registry (Tasks 8, 11)
- IR schema and validation (Task 7)
- IR-to-PocketFlow converter (Task 4)
- Shared store validation (Task 6)
- Metadata extraction (Task 9)
- NodeAwareSharedStore proxy (Task 10)

### ❌ Explicitly Excluded from MVP

**Deferred to v2.0** (8 tasks):
1. Trace Persistence and Retrieval (Task 44)
2. Node Version Tracking (Task 45)
3. Interface Compatibility System (Task 46)
4. Success Metrics Instrumentation (Task 47)
5. Direct CLI Parsing (Task 48)
6. CLI Autocomplete (Task 49)
7. Nested Proxy Mappings (Task 50)
8. CLI Parameter Resolution (Task 51)

**Important**: Task 51 is what enables real CLI parsing. In MVP, the entire user input after 'pflow' is sent as natural language to the LLM.

**Deferred to v3.0 (Cloud Platform)**:
- Multi-user authentication
- Web UI
- Distributed execution
- Advanced caching
- Marketplace

---

## Implementation Roadmap

### Overview

**Total Scope**: 40 MVP tasks organized into 4 phases
**Timeline**: 9 weeks sequential, 6-7 weeks with parallelization
**Strategy**: Test-as-you-go - each task includes its own test strategy

📌 **MVP Natural Language Approach**: In the MVP, pflow does NOT parse CLI syntax directly. Everything after the 'pflow' command is treated as a natural language string and sent to the LLM for interpretation.

### Phase 1: Foundation & Core Execution (Weeks 1-3)

**Goal**: Build essential infrastructure and validate with an integration test
**Tasks**: 1-11 (11 tasks)

**Key Deliverables**:
- **Package Setup** (Task 1): Create package structure with CLI entry point
- **CLI Framework** (Task 2): Basic click framework for argument collection (NOT parsing)
- **Integration Test** (Task 3): Execute hardcoded "Hello World" workflow to validate pipeline
- **JSON IR Schema** (Task 7): Minimal workflow representation format
- **Node Discovery** (Task 8): Filesystem scanning to find pocketflow.Node subclasses
- **Node Registry** (Task 11): System for tracking and querying available nodes
- **IR-to-Flow Converter** (Task 4): Convert JSON IR to pocketflow.Flow objects
- **Shared Store Validation** (Task 6): Simple validation functions for the dict pattern
- **Metadata Extraction** (Task 9): Parse docstrings to understand node interfaces
- **NodeAwareSharedStore Proxy** (Task 10): Transparent key mapping with validation
- **Template Substitution** (Task 5): Planner-internal `$variable` replacement utility

**Success Criteria**:
```bash
# Task 3 validates the entire pipeline:
echo "Hello from pflow" > /tmp/test.txt
pflow run hello_workflow.json
cat /tmp/output.txt  # Shows: "HELLO FROM PFLOW"
# ✓ IR loaded, Flow created, Nodes executed, Shared store worked
```

### Phase 2: Node Ecosystem & CLI Polish (Weeks 4-5)

**Goal**: Implement platform nodes and enhance CLI usability
**Tasks**: 12-17, 18, 25, 28 (9 tasks)

**Platform Nodes**:
- **General LLM node** (Task 12): Fast text processing without project context
- **GitHub nodes** (Task 13): `github-get-issue`, `github-create-pr`
- **File nodes** (Task 14): `read-file`, `write-file`
- **Git nodes** (Tasks 15-16): `git-commit`, `git-push`
- **Shell node** (Task 17): `shell-exec` for command execution
- **Claude Code Super Node** (Task 25): Comprehensive AI agent with project context

**Supporting Components**:
- **LLM API Client** (Task 18): Simple client for Claude/OpenAI integration
- **Registry CLI Commands** (Task 28): `pflow registry list` and `describe`

**Node Implementation Focus**:
- Simple, focused functionality per node
- Natural shared store patterns
- Comprehensive test coverage
- Clear documentation

### Phase 3: Natural Language Planning (Weeks 6-7)

**Goal**: Enable workflow generation from natural language input - THE CORE FEATURE
**Tasks**: 19-21, 29-31 (6 tasks)

**Key Components**:
- **Workflow Generation Engine** (Task 19): Transform natural language → template-driven workflows
- **Template Resolution** (Task 20): Planner-internal variable substitution (`$var` → `shared["var"]`)
- **Planning Context Builder** (Task 21): Format node metadata for LLM understanding
- **Prompt Templates** (Task 29): Well-crafted prompts for reliable generation
- **Approval & Storage System** (Task 30): User verification and workflow persistence
- **Named Workflow Execution** (Task 31): Execute saved workflows by name with parameters

**Critical Feature - Pattern Recognition**:
```bash
# First time: generates workflow
pflow "analyze error logs and create report"
# → User approves → Saves as 'analyze-logs'

# Similar request: reuses existing workflow
pflow "analyze server.log and create analysis"
# → Recognizes pattern → Suggests: "Use 'analyze-logs' workflow?"
```

**Planning Success Metrics**:
- ≥95% planning success rate for reasonable requests
- ≥90% user approval rate for generated workflows
- ≤800ms planning latency
- Effective workflow reuse for similar requests

### Phase 4: Persistence, Usability & Optimization (Weeks 8-9)

**Goal**: Build execution engine, enhance UX, and validate MVP readiness
**Tasks**: 22-24, 26-27, 32-40 (14 tasks)

**Core Runtime & Storage**:
- **Workflow Lockfile System** (Task 22): Generate lockfiles for deterministic execution
- **Execution Tracing** (Task 23): Comprehensive visibility into workflow execution
- **Runtime Configuration** (Task 24): Manage execution settings and environment
- **Validation System** (Task 26): Validate IR structure and node compatibility
- **Caching System** (Task 27): Optional optimization for @flow_safe nodes

**Testing & Polish**:
- **Comprehensive Tests** (Task 32): Integration test coverage across all features
- **Error Messages & Help** (Task 33): Clear, actionable error messages
- **Documentation Updates** (Task 34): User guides and API documentation
- **CLI Autocomplete** (Task 35): Shell completion for node discovery
- **Performance Optimization** (Task 36): Profile and optimize hot paths
- **Example Workflows** (Tasks 37-39): Showcase common developer patterns
- **MVP Validation** (Task 40): End-to-end scenario testing

**Execution Trace Example**:
```
[1] github-get-issue (0.45s)
    Input: {issue_number: 1234}
    Output: {issue_data: {...}, issue_title: "Fix login bug"}
    Shared Store Δ: +issue_data, +issue_title

[2] claude-code (28.3s, 2150 tokens, ~$0.08)
    Input: {prompt: "Fix issue: {login bug details...}"}
    Output: {code_report: "Fixed authentication..."}
    Shared Store Δ: +code_report

[3] llm (0.8s, 120 tokens, ~$0.001)
    Input: {prompt: "Generate commit message for: Fixed auth..."}
    Output: {response: "Fix: Resolve login authentication bug"}
    Shared Store Δ: +response
```

### Parallelization Opportunities

**Immediate Start Tasks (No Dependencies)**:
- Task 1: Create package setup and CLI entry point
- Task 6: Implement shared store validation utilities
- Task 7: Define JSON IR schema
- Task 8: Implement node discovery via filesystem scanning
- Task 18: Implement LLM API client
- Task 29: Create prompt templates for planning

**Parallel Execution Strategy**:
- Phase 1 & 2: Can partially overlap (start node development while finishing infrastructure)
- Phase 2 & 3: Platform nodes and planning can be developed in parallel
- Cross-functional teams: Different developers can work on independent tracks
- Test-as-you-go: Each task includes its own testing, preventing test bottlenecks

**Timeline Optimization**:
- Sequential approach: 9 weeks
- Parallel approach: 6-7 weeks (25-30% faster)

---

## Success Metrics & Acceptance Criteria

### Primary Value Metrics
- **Efficiency Gain**: 10x improvement over slash commands (tokens + time)
- **Planning Success**: ≥95% of common development workflows generate valid CLI flows
- **User Adoption**: ≥90% approval rate for generated workflows
- **Execution Reliability**: ≥98% successful execution of valid workflows

### Technical Benchmarks
- **Planning Latency**: ≤800ms average for natural language → validated IR
- **Execution Speed**: ≤2s overhead vs raw Python for 3-node flows
- **Registry Scale**: Support 6-10 platform nodes efficiently
- **Flow Complexity**: Handle 10-node workflows without performance degradation

### Phase-by-Phase Success Criteria

**Phase 1: Foundation & Core Execution**
- [x] CLI collects arguments as natural language string (NOT parsing)
- [x] Task 3 "Hello World" workflow executes end-to-end
- [x] Shared store validation functions work correctly
- [x] Node discovery finds all pocketflow.Node subclasses
- [x] JSON IR converts to pocketflow.Flow objects
- [x] Each task includes comprehensive test coverage

**Phase 2: Node Ecosystem & CLI Polish**
- [x] All platform nodes implemented with test coverage
- [x] Two-tier AI approach works (Claude Code + general LLM)
- [x] Template variables resolve in planner (`$variable` → `shared["variable"]`)
- [x] Registry commands provide rich node details
- [x] Node proxy pattern handles basic key mapping

**Phase 3: Natural Language Planning**
- [x] Natural language generates valid workflows (≥95% success rate)
- [x] Users approve generated workflows (≥90% approval rate)
- [x] Planning completes quickly (≤800ms latency)
- [x] Workflow reuse reduces redundant planning
- [x] Template resolution works within planner

**Phase 4: Persistence, Usability & Optimization**
- [x] Workflows execute reliably with proper tracing
- [x] Lockfiles ensure deterministic execution
- [x] Performance meets targets (≤2s execution overhead)
- [x] MVP delivers 10x efficiency over slash commands
- [x] Comprehensive integration tests validate all features

### MVP Acceptance Criteria

**The MVP is complete when developers can successfully**:

1. **Generate workflows from natural language**:
   ```bash
   pflow "analyze this github issue and suggest a fix"
   # → Generates: github-get-issue >> claude-analyze >> claude-implement
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

4. **Achieve 10x efficiency improvement** over equivalent slash commands in:
   - Execution time (consistent 2-5s vs variable 30-90s)
   - Token usage (minimal overhead vs 1000-2000 tokens per run)
   - Reliability (deterministic vs variable approaches)

---

## Technical Implementation Details

### Development Principles
1. **Build on pocketflow directly** - No wrapper classes or reimplementation
2. **Simple functions over frameworks** - validation.py uses plain functions
3. **Natural language first** - Real CLI parsing is v2.0
4. **Template variables are planner-internal** - Not runtime feature
5. **Explicit over magic** - All behavior visible and debuggable
6. **Test-as-you-go** - Each task includes embedded test strategy

### Critical Dependencies

These 8 components must work together for MVP success:

1. **Natural Language Planner**: The core differentiator - transforms descriptions into CLI workflows
2. **Simple Node Registry**: Platform-specific nodes with clear single purposes
3. **CLI Workflow Engine**: Execute saved workflows with parameters
4. **JSON IR System**: Capture complete workflow definitions with provenance
5. **Validation Pipeline**: Ensure generated workflows are sound and executable
6. **Shared Store Runtime**: Natural key-based communication between nodes
7. **Execution Tracing**: Step-by-step debugging superior to conversation logs
8. **Workflow Storage**: Save/load named workflows for reuse

### Development Approach
1. **Test-as-you-go** - Each task includes its own test strategy
2. **Integration test early** - Task 3 validates foundation
3. **Linear before conditional** - No branching logic in MVP
4. **Real integration after mocking** - Start with mocked services
5. **User feedback from Week 3** - Test with developers early
6. **Documentation alongside code** - Keep docs current

### Risk Mitigation
- **LLM failures**: Robust validation and clear error messages
- **Performance issues**: Profile early, optimize hot paths
- **User adoption**: Focus on real developer workflows
- **Scope creep**: Explicitly defer v2.0 features

---

## Validation Strategy

### Technical Validation
- **Unit Tests**: Every node tested with realistic development scenarios
- **Integration Tests**: End-to-end workflow generation and execution
- **Performance Benchmarks**: Planning latency and execution speed metrics
- **Error Handling**: Comprehensive failure scenarios and recovery

### User Validation
- **Developer Workflows**: Test with real GitHub issues, code analysis, testing scenarios
- **Slash Command Comparison**: Side-by-side efficiency demonstrations
- **Workflow Reuse**: Verify saved workflows work across different contexts
- **Team Sharing**: Test workflow portability between developers

### Measuring Success

**Immediate Value Metrics**:
1. Time Savings: Developers save 30-90s per workflow execution
2. Cost Reduction: 10x reduction in LLM tokens for repeated workflows
3. Consistency: Same workflow produces same results across executions
4. Observability: Clear execution traces vs conversation logs

**Adoption Indicators**:
1. Workflow Creation: Developers successfully generate workflows from natural language
2. Workflow Reuse: Saved workflows used multiple times per week
3. Team Sharing: Workflows shared and adopted across development teams
4. Slash Command Replacement: Developers prefer pflow over existing slash commands

---

## Launch Readiness

The pflow MVP is ready when:

1. **Core Workflows Function**:
   ```bash
   # Natural language input creates workflow:
   pflow "fix github issue 1234"
   # → LLM generates workflow → User approves → Saved as 'fix-issue'

   # Named workflow executes instantly:
   pflow fix-issue --issue=1234  # 2-5s execution, minimal tokens

   # CLI-like syntax still goes through LLM:
   pflow read-file --path=error.log => analyze => write-file --path=report.md
   # → Entire string interpreted by LLM
   ```

2. **Performance Targets Met**:
   - Planning: ≤800ms for natural language → workflow
   - Execution: ≤2s overhead vs raw commands
   - Efficiency: 10x improvement over slash commands

3. **User Experience Validated**:
   - ≥90% workflow approval rate
   - Natural language interface intuitive
   - Clear execution traces aid debugging

4. **Quality Standards Achieved**:
   - Test-as-you-go strategy ensures reliability
   - All 40 MVP tasks completed with embedded tests
   - Documentation complete

**pflow delivers on its promise**: Transform inefficient AI-assisted development from heavy slash commands into lightweight, deterministic CLI workflows that run forever after planning once.

---

*This implementation guide combines the strategic roadmap with detailed scope definition, providing a comprehensive reference for building pflow from vision to reality. The guide reflects 40 MVP implementation tasks organized into 4 clear phases, with the Natural Language Planner (Task 17) as THE core feature that enables the "find or build" pattern.*
