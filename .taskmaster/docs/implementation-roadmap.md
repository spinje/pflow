# pflow Implementation Roadmap: From Vision to Reality

This document provides a strategic roadmap for implementing pflow, the AI workflow compiler that transforms natural language and CLI pipe syntax into permanent, deterministic CLI commands.

**Scope**: 35 MVP tasks across 5 phases (8 additional tasks deferred to v2.0)

## 🎯 Vision: "Plan Once, Run Forever"

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

**Value Proposition**: 10x efficiency improvement through workflow compilation and reuse.

---

## 🗺 Development Roadmap: 5 Phases, 35 MVP Tasks

### Phase 1: Core Infrastructure Foundation (Tasks 1-9)
**Goal**: Build the essential foundation systems that all other features depend on
**Timeline**: Weeks 1-2

**Key Deliverables**:
- **Package Setup** (Task 1): Create package structure with CLI entry point
- **CLI Framework** (Task 2): Basic click framework with `--key=value` flag parsing
- **Shell Pipe Integration** (Task 3): Full Unix pipe support with stdin/stdout handling
- **Shared Store Validation** (Task 4): Simple validation functions for the dict pattern
- **NodeAwareSharedStore Proxy** (Task 5): Transparent key mapping between incompatible nodes
- **CLI Parameter Resolution** (Task 6): Route flags to shared store or node params based on context
- **Template Variable System** (Task 7): Simple `$variable` replacement for shared store access
- **Node Discovery** (Task 8): Filesystem scanning to find pocketflow.Node subclasses
- **JSON IR Schema** (Task 9): Minimal workflow representation format

**Success Criteria**:
```bash
# CLI accepts and parses workflow syntax
pflow read-file --path=data.txt >> llm --prompt="analyze this" >> write-file --path=output.md
# Nodes discovered, IR generated, shared store validated
```

### Phase 2: Metadata & Registry Systems (Tasks 10-11)
**Goal**: Extract rich metadata from nodes to enable intelligent planning
**Timeline**: Week 3

**Key Deliverables**:
- **Metadata Extraction** (Task 10): Parse docstrings to understand node interfaces
- **Registry CLI Commands** (Task 11): `pflow registry list` and `pflow registry describe`

**Success Criteria**:
```bash
pflow registry list
# Shows all available simple nodes: github-get-issue, llm, read-file, etc.

pflow registry describe github-get-issue
# Displays:
# - Description: Retrieves GitHub issue details
# - Inputs: issue_number, repo (from shared store)
# - Outputs: issue_data, issue_title (to shared store)
```

### Phase 3: Simple Platform Nodes (Tasks 12-18, 34)
**Goal**: Implement single-purpose developer workflow nodes
**Timeline**: Weeks 4-5

**Priority 1 Platform Nodes**:
- **GitHub nodes** (Tasks 12, 17): Individual nodes like `github-get-issue`, `github-create-pr`
- **Claude Code super node** (Task 13): `claude-code` - comprehensive AI development agent
- **General LLM node** (Task 14): `llm` - API-based text processing
- **Git nodes** (Tasks 15, 34): `git-commit`, `git-push`, `git-create-branch`
- **File nodes** (Task 16): `read-file`, `write-file`, `copy-file`

**Priority 2 Platform Nodes**:
- **CI nodes** (Task 18): `ci-run-tests`, `ci-get-status`
- **Shell nodes** (Task 18): `shell-exec`, `shell-pipe`

**Two-Tier AI Architecture**:
1. **Claude Code Super Node**: Receives complex instructions with template variables
   ```bash
   claude-code --prompt="Fix the issue described in: $issue_data"
   # Returns: shared["code_report"] with comprehensive changes
   ```

2. **General LLM Node**: Fast text processing without project context
   ```bash
   llm --prompt="Write a commit message for: $code_report"
   # Returns: shared["response"] with generated text
   ```

**Success Criteria**:
```bash
# Complex workflow executes with template variables
pflow github-get-issue --issue=1234 >> \
  claude-code --prompt="Fix issue: $issue_data" >> \
  llm --prompt="Generate commit message for: $code_report" >> \
  git-commit --message="$response" >> \
  github-create-pr --title="Fix: $issue_title" --body="$code_report"
```

### Phase 4: Natural Language Planning & Workflow Execution (Tasks 19-24, 33)
**Goal**: Enable workflow generation from natural language and persistent execution
**Timeline**: Weeks 6-7

**Key Deliverables**:
- **LLM API Client** (Task 19): Simple client for Claude/OpenAI integration (consider Simon Willison's llm package)
- **Planning Context Builder** (Task 20): Format node metadata for LLM understanding
- **Workflow Generation Engine** (Task 21): Transform natural language → template-driven workflows
- **Approval & Storage System** (Task 22): User verification and workflow persistence
- **Workflow Lockfile System** (Task 23): Generate lockfiles for deterministic execution
- **Named Workflow Execution** (Task 24): Execute saved workflows by name with parameters
- **Prompt Templates** (Task 33): Well-crafted prompts for reliable generation

**Critical Feature**: Pattern recognition for workflow reuse
```bash
# First time: generates workflow
pflow "analyze error logs and create report"
# → User approves → Saves as 'analyze-logs'

# Similar request: reuses existing workflow
pflow "analyze server.log and create analysis"
# → Recognizes pattern → Suggests: "Use 'analyze-logs' workflow?"
```

**Success Criteria**:
- ≥95% planning success rate for reasonable requests
- ≥90% user approval rate for generated workflows
- ≤800ms planning latency
- Effective workflow reuse for similar requests

### Phase 5: Runtime, Polish & Validation (Tasks 25-30, 35, 37-38)
**Goal**: Build execution engine, enhance UX, and validate MVP readiness
**Timeline**: Weeks 8-9

**Core Runtime** (Week 8):
- **IR Compiler** (Task 25): Convert JSON IR → pocketflow.Flow objects
- **Shared Store Lifecycle** (Task 26): Ensure isolation between workflow executions
- **Validation System** (Task 27): Validate IR structure and node compatibility
- **CLI Autocomplete** (Task 35): Shell completion for node discovery
- **Execution Tracing** (Task 37): Comprehensive visibility into workflow execution

**Polish & Testing** (Week 9):
- **Caching System** (Task 28): Optional optimization for @flow_safe nodes
- **Comprehensive Tests** (Task 29): Unit and integration test coverage
- **CLI Experience** (Task 30): Error messages, help text, documentation
- **MVP Validation** (Task 38): End-to-end scenario testing

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

---

## 🔄 Parallelization Opportunities

One of the key insights from task dependency analysis is that **6 tasks can start immediately** without waiting for others:

**Immediate Start Tasks (No Dependencies)**:
- **Task 1**: Create package setup and CLI entry point
- **Task 4**: Implement shared store validation utilities
- **Task 8**: Implement node discovery via filesystem scanning
- **Task 9**: Define JSON IR schema
- **Task 19**: Implement LLM API client
- **Task 33**: Create prompt templates for planning

This enables significant timeline compression:
- **Phase 1 & 2**: Can partially overlap (start registry work while finishing infrastructure)
- **Phase 3 & 4**: Platform nodes and planning can be developed in parallel
- **Cross-functional teams**: Different developers can work on independent tracks

**Potential Timeline Optimization**:
- Sequential approach: 9 weeks
- Parallel approach: 6-7 weeks (25-30% faster)

---

## 🚦 Explicitly Deferred to v2.0

Based on tasks.json, these 8 features are NOT part of MVP:

1. **Execution Configuration Handling** (Task 44): Node-level retry configuration in runtime
2. **Trace Persistence and Retrieval** (Task 45): Save and retrieve execution traces for debugging
3. **Node Version Tracking** (Task 46): Track node versions for lockfile generation
4. **Interface Compatibility System** (Task 47): Advanced marketplace node compatibility
5. **Success Metrics Instrumentation** (Task 48): Detailed performance tracking
6. **Direct CLI Parsing** (Task 49): Minor optimization to bypass LLM for complete commands
7. **Nested Proxy Mappings** (Task 50): Complex key mapping patterns for advanced compatibility
8. **CLI Pipe Operator Parsing** (Task 51): Parse >> operator directly (MVP uses LLM for all input)

These represent valuable enhancements but aren't required for core MVP value delivery.

---

## 📊 Success Metrics by Phase

### Phase 1: Infrastructure Foundation
- [x] CLI parses `--key=value` flags and pipe syntax
- [x] Shared store validation functions work correctly
- [x] Node discovery finds all pocketflow.Node subclasses
- [x] JSON IR represents workflows accurately

### Phase 2: Metadata & Registry
- [x] Docstring parsing extracts interface information
- [x] Registry commands provide rich node details
- [x] Metadata enables intelligent node selection

### Phase 3: Platform Nodes
- [x] All 7 node categories implemented (GitHub, Claude, LLM, Git, File, CI, Shell)
- [x] Template variables resolve correctly (`$variable` → `shared[variable]`)
- [x] Two-tier AI approach works (Claude Code + general LLM)
- [x] Complex workflows execute end-to-end

### Phase 4: Natural Language Planning
- [x] Natural language generates valid workflows (≥95% success rate)
- [x] Users approve generated workflows (≥90% approval rate)
- [x] Planning completes quickly (≤800ms latency)
- [x] Workflow reuse reduces redundant planning

### Phase 5: Runtime & Polish
- [x] Workflows execute reliably with proper tracing
- [x] Shell pipes and autocomplete enhance usability
- [x] Performance meets targets (≤2s execution overhead)
- [x] MVP delivers 10x efficiency over slash commands

---

## 🏗 Implementation Strategy

### Technical Principles
1. **Build on pocketflow directly** - No wrapper classes or reimplementation
2. **Simple functions over frameworks** - validation.py uses plain functions
3. **Template-driven workflows** - `$variable` syntax throughout
4. **Natural interfaces** - Intuitive shared store keys
5. **Explicit over magic** - All behavior visible and debuggable

### Development Approach
1. **Linear before conditional** - No branching logic in MVP
2. **Real integration after mocking** - Start with mocked services
3. **User feedback from Week 3** - Test with developers early
4. **Documentation alongside code** - Keep docs current

### Risk Mitigation
- **LLM failures**: Robust validation and clear error messages
- **Performance issues**: Profile early, optimize hot paths
- **User adoption**: Focus on real developer workflows
- **Scope creep**: Explicitly defer v2.0 features

---

## 🎉 Launch Readiness Criteria

The pflow MVP is ready when:

1. **Core Workflows Function**:
   ```bash
   # Primary: GitHub issue resolution
   pflow fix-issue --issue=1234  # 2-5s execution, minimal tokens

   # Secondary: Log analysis
   pflow analyze-logs --path=error.log  # Instant analysis
   ```

2. **Performance Targets Met**:
   - Planning: ≤800ms for natural language → workflow
   - Execution: ≤2s overhead vs raw commands
   - Efficiency: 10x improvement over slash commands

3. **User Experience Validated**:
   - ≥90% workflow approval rate
   - CLI autocomplete helps discovery
   - Clear execution traces aid debugging

4. **Quality Standards Achieved**:
   - Comprehensive test coverage (Task 29)
   - All 35 MVP tasks completed and tested
   - Documentation complete

**pflow delivers on its promise**: Transform inefficient AI-assisted development from heavy slash commands into lightweight, deterministic CLI workflows that run forever after planning once.

---

*This roadmap reflects 35 MVP implementation tasks organized into 5 clear phases, building from core infrastructure through natural language planning to a polished MVP that demonstrates real value to developers. An additional 8 tasks are deferred to v2.0 for future enhancements.*
