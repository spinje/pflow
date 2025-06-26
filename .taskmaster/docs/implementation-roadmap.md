# pflow Implementation Roadmap: From Vision to Reality

This document provides a strategic roadmap for implementing pflow, the AI workflow compiler that transforms natural language and CLI pipe syntax into permanent, deterministic CLI commands.

**Scope**: 40 MVP tasks across 4 phases (8 tasks deferred to v2.0)

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

## 🗺 Development Roadmap: 4 Phases, 40 MVP Tasks

📌 **MVP Natural Language Approach**: In the MVP, pflow does NOT parse CLI syntax directly. Everything after the 'pflow' command is treated as a natural language string and sent to the LLM for interpretation. Real CLI parsing (understanding >> operators, routing --flags) is deferred to v2.0. This simplification allows faster MVP delivery while still providing full functionality through LLM interpretation.

🧪 **Test-as-You-Go Strategy**: Instead of a separate testing phase, each task includes its own test strategy. This ensures functionality is validated immediately and helps catch regressions when implementing future tasks.

### Phase 1: Foundation & Core Execution (Tasks 1-11)
**Goal**: Build essential infrastructure and validate with an integration test
**Timeline**: Weeks 1-3

**Key Deliverables**:
- **Package Setup** (Task 1): Create package structure with CLI entry point
- **CLI Framework** (Task 2): Basic click framework for argument collection (NOT parsing)
- **Integration Test** (Task 3): Execute a hardcoded "Hello World" workflow to validate pipeline
- **IR-to-Flow Converter** (Task 4): Convert JSON IR to pocketflow.Flow objects
- **Template Substitution** (Task 5): Planner-internal `$variable` replacement utility
- **Shared Store Validation** (Task 6): Simple validation functions for the dict pattern
- **JSON IR Schema** (Task 7): Minimal workflow representation format
- **Node Discovery** (Task 8): Filesystem scanning to find pocketflow.Node subclasses
- **Metadata Extraction** (Task 9): Parse docstrings to understand node interfaces
- **NodeAwareSharedStore Proxy** (Task 10): Transparent key mapping with basic validation
- **Node Registry** (Task 11): System for tracking and querying available nodes

**Success Criteria**:
```bash
# Task 3 validates the entire pipeline with a hardcoded workflow:
echo "Hello from pflow" > /tmp/test.txt
pflow run hello_workflow.json
cat /tmp/output.txt  # Shows: "HELLO FROM PFLOW"
# ✓ IR loaded, Flow created, Nodes executed, Shared store worked
```

### Phase 2: Node Ecosystem & CLI Polish (Tasks 12-28)
**Goal**: Implement platform nodes and enhance CLI usability
**Timeline**: Weeks 4-5

**Priority 1 Platform Nodes**:
- **General LLM node** (Task 12): Fast text processing without project context
- **GitHub nodes** (Tasks 13): `github-get-issue`, `github-create-pr`
- **File nodes** (Task 14): `read-file`, `write-file`
- **Git nodes** (Tasks 15-16): `git-commit`, `git-push`
- **Shell node** (Task 17): `shell-exec` for command execution

**Two-Tier AI Architecture**:
1. **Claude Code Super Node** (Task 25): Comprehensive AI agent with project context
   - Receives complex instructions with template variables
   - Returns detailed development reports: `shared["code_report"]`
   - Handles multi-step development tasks with file system access

2. **General LLM Node** (Task 12): Fast text processing without context
   - Simple prompts for commit messages, summaries
   - Quick responses without file system access: `shared["response"]`
   - Lightweight alternative to claude-code

**Additional Components**:
- **LLM API Client** (Task 18): Simple client for Claude/OpenAI integration
- **Registry CLI Commands** (Task 28): `pflow registry list` and `describe`

### Phase 3: Natural Language Planning (Tasks 18-21, 29-31)
**Goal**: Enable workflow generation from natural language input
**Timeline**: Weeks 6-7

**Key Deliverables**:
- **Workflow Generation Engine** (Task 19): Transform natural language → template-driven workflows
- **Template Resolution** (Task 20): Planner-internal variable substitution (`$var` → `shared["var"]`)
- **Planning Context Builder** (Task 21): Format node metadata for LLM understanding
- **Prompt Templates** (Task 29): Well-crafted prompts for reliable generation
- **Approval & Storage System** (Task 30): User verification and workflow persistence
- **Named Workflow Execution** (Task 31): Execute saved workflows by name with parameters

**Critical MVP Approach**:
```bash
# In MVP, everything after 'pflow' is natural language:
pflow "fix github issue 1234"
# → Entire string sent to LLM for interpretation

# Even with CLI-like syntax, it's still interpreted as natural language:
pflow read-file --path=data.txt >> analyze >> write report
# → LLM interprets this string and generates the workflow
```

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

### Phase 4: Persistence, Usability & Optimization (Tasks 22-40)
**Goal**: Build execution engine, enhance UX, and validate MVP readiness
**Timeline**: Weeks 8-9

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
- **Example Workflows** (Task 37-39): Showcase common developer patterns
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

---

## 🔄 Parallelization Opportunities

One of the key insights from task dependency analysis is that **several tasks can start immediately** without waiting for others:

**Immediate Start Tasks (No Dependencies)**:
- **Task 1**: Create package setup and CLI entry point
- **Task 6**: Implement shared store validation utilities
- **Task 7**: Define JSON IR schema
- **Task 8**: Implement node discovery via filesystem scanning
- **Task 18**: Implement LLM API client
- **Task 29**: Create prompt templates for planning

This enables significant timeline compression:
- **Phase 1 & 2**: Can partially overlap (start node development while finishing infrastructure)
- **Phase 2 & 3**: Platform nodes and planning can be developed in parallel
- **Cross-functional teams**: Different developers can work on independent tracks
- **Test-as-you-go**: Each task includes its own testing, preventing test bottlenecks

**Potential Timeline Optimization**:
- Sequential approach: 9 weeks
- Parallel approach: 6-7 weeks (25-30% faster)

---

## 🚦 Explicitly Deferred to v2.0

Based on tasks.json, these 8 features are NOT part of MVP:

1. **Trace Persistence and Retrieval** (Task 44): Save and retrieve execution traces for debugging
2. **Node Version Tracking** (Task 45): Track node versions for lockfile generation
3. **Interface Compatibility System** (Task 46): Advanced marketplace node compatibility
4. **Success Metrics Instrumentation** (Task 47): Detailed performance tracking
5. **Direct CLI Parsing** (Task 48): Minor optimization to bypass LLM for complete commands
6. **CLI Autocomplete** (Task 49): Shell completion for node discovery
7. **Nested Proxy Mappings** (Task 50): Complex key mapping patterns for advanced compatibility
8. **CLI Parameter Resolution** (Task 51): Parse and route --flags to appropriate destinations

**Important**: Task 51 is what enables real CLI parsing. In MVP, the entire user input after 'pflow' is sent as a natural language string to the LLM for interpretation.

These represent valuable enhancements but aren't required for core MVP value delivery.

---

## 📊 Success Metrics by Phase

### Phase 1: Foundation & Core Execution
- [x] CLI collects arguments as natural language string (NOT parsing)
- [x] Task 3 "Hello World" workflow executes end-to-end
- [x] Shared store validation functions work correctly
- [x] Node discovery finds all pocketflow.Node subclasses
- [x] JSON IR converts to pocketflow.Flow objects
- [x] Each task includes comprehensive test coverage

### Phase 2: Node Ecosystem & CLI Polish
- [x] All platform nodes implemented with test coverage
- [x] Two-tier AI approach works (Claude Code + general LLM)
- [x] Template variables resolve in planner (`$variable` → `shared["variable"]`)
- [x] Registry commands provide rich node details
- [x] Node proxy pattern handles basic key mapping

### Phase 3: Natural Language Planning
- [x] Natural language generates valid workflows (≥95% success rate)
- [x] Users approve generated workflows (≥90% approval rate)
- [x] Planning completes quickly (≤800ms latency)
- [x] Workflow reuse reduces redundant planning
- [x] Template resolution works within planner

### Phase 4: Persistence, Usability & Optimization
- [x] Workflows execute reliably with proper tracing
- [x] Lockfiles ensure deterministic execution
- [x] Performance meets targets (≤2s execution overhead)
- [x] MVP delivers 10x efficiency over slash commands
- [x] Comprehensive integration tests validate all features

---

## 🏗 Implementation Strategy

### Technical Principles
1. **Build on pocketflow directly** - No wrapper classes or reimplementation
2. **Simple functions over frameworks** - validation.py uses plain functions
3. **Natural language first** - Real CLI parsing is v2.0
4. **Template variables are planner-internal** - Not runtime feature
5. **Explicit over magic** - All behavior visible and debuggable

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

## 🎉 Launch Readiness Criteria

The pflow MVP is ready when:

1. **Core Workflows Function**:
   ```bash
   # Natural language input creates workflow:
   pflow "fix github issue 1234"
   # → LLM generates workflow → User approves → Saved as 'fix-issue'

   # Named workflow executes instantly:
   pflow fix-issue --issue=1234  # 2-5s execution, minimal tokens

   # CLI-like syntax still goes through LLM:
   pflow read-file --path=error.log >> analyze >> write-file --path=report.md
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

*This roadmap reflects 40 MVP implementation tasks organized into 4 clear phases, building from core infrastructure through natural language planning to a polished MVP that demonstrates real value to developers. An additional 8 tasks are deferred to v2.0 for future enhancements. The MVP focuses on natural language interpretation, with real CLI parsing deferred to enable faster delivery.*
