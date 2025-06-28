# MVP Scope: AI-Assisted Development Workflow Compiler

## Navigation

**Related Documents:**
- **Architecture**: [PRD](../prd.md) | [Architecture](../architecture/architecture.md)
- **Patterns**: [Shared Store](../core-concepts/shared-store.md) | [Simple Nodes](./simple-nodes.md)
- **Components**: [Component Inventory](../architecture/components.md) | [Planner](./planner.md) | [Runtime](../core-concepts/runtime.md)
- **Implementation**: [PocketFlow Integration](../architecture/pflow-pocketflow-integration-guide.md)

## 🎯 Core Vision

**"Transform AI-assisted development workflows from inefficient slash commands into deterministic, reusable CLI workflows"**

pflow MVP solves the specific problem of slash command inefficiency by enabling developers to:

1. **Plan Once, Run Forever**: Capture AI workflow logic once, execute deterministically afterward
2. **Eliminate Token Waste**: Stop spending 1000-2000 tokens on orchestration logic every execution
3. **Enable Predictable Execution**: Replace variable 30-90s slash command runs with consistent 2-5s workflow execution
4. **Improve Observability**: Get step-by-step execution traces instead of conversation logs

The goal is a working MVP that can execute the core workflows:

**Start simple** (general text processing):
```bash
# Transform: Repeatedly asking AI "analyze these logs"
# Into: pflow analyze-logs --input=error.log (instant)
pflow read-file --path=error.log => llm --prompt="extract error patterns and suggest fixes" => write-file --path=analysis.md
```

**And move on to more complex workflows**:
LLM Agent like Claude Code executing all steps, reasoning between each step:

```markdown
# Transform: /project:fix-github-issue 1234 (Claude code slash command, 50-90s, heavy tokens)
# This is a Claude Code slash command (prompt shortcut) that was used as an example in an Anthropic blog post as a good example of how to efficiently use Claude Code.
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

Remember to use the GitHub CLI (`gh`) for all GitHub-related tasks.
```

```bash
# Into: pflow fix-issue --issue=1234 (20-50s, minimal tokens)
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
```

> Note that in this core example we are still needing to use the `claude-code` node to execute parts of the workflow. For many use cases, using LLM as Agents will not be necessary and in these cases the speedup will be much greater and can potentially reach 10x or more by reducing the intermittent reasoning between each step that needs to happen in Agentic workflows.

### Target Use Case Example

```bash
# Current inefficiency: Claude Code slash command
# Every run requires full reasoning and orchestration
/project:fix-github-issue 1234  # 30-90s, variable approach, token waste

# pflow solution: Natural language → deterministic workflow
pflow "get github issue, analyze it, implement fix, test, and create PR"
# Generates: github-get-issue --issue=1234 >> llm --prompt="analyze this issue and understand the problem" >> llm --prompt="implement fix for this issue" >> ci-run-tests >> git-commit --message="Fix issue 1234" >> github-create-pr --title="Fix for issue 1234"

# Subsequent runs: Instant, predictable, token-efficient
pflow fix-issue --issue=1234  # 2-5s, consistent execution, minimal tokens
```

---

## ✅ MVP Core Features (v0.1)

### 1. Natural Language Planning Engine (MVP - Built After Core Infrastructure)
**Purpose**: Transform natural language descriptions into deterministic CLI workflows

**Build Dependencies**: CLI runtime, node registry, metadata extraction system
**Implementation Order**: Core infrastructure first, then NL planning capabilities

**Requirements**:
- **Input**: `pflow "analyze github issue, search codebase, implement fix, test"`
- **Output**: Deterministic CLI workflow using developer-focused nodes
- **LLM Integration**: Use thinking models (o1-preview/Claude) for intelligent node selection
- **Metadata-Driven**: Select nodes based on extracted interface metadata, not code inspection
- **User Verification**: Show generated CLI workflow for approval before execution

### 2. Developer-Focused Node Registry
**Purpose**: Provide nodes specifically designed for AI-assisted development workflows

**Core Simple Nodes** (MVP essential):
- **GitHub**: `github-get-issue`, `github-create-issue`, `github-list-prs`, `github-create-pr`, `github-get-files`, `github-merge-pr`, `github-add-comment`
- **LLM**: `llm` (general-purpose text processing - smart exception to simple node philosophy)
- **CI**: `ci-run-tests`, `ci-get-status`, `ci-trigger-build`, `ci-get-logs`
- **Git**: `git-commit`, `git-push`, `git-create-branch`, `git-merge`, `git-status`
- **File**: `file-read`, `file-write`, `file-copy`, `file-move`, `file-delete`
- **Shell**: `shell-exec`, `shell-pipe`, `shell-background`

**Simple Node Architecture Benefits**:
- **Clear Purpose**: Each node has one specific, well-defined purpose
- **Predictable Interfaces**: Natural shared store patterns (`shared["issue"]`, `shared["code"]`, `shared["test_results"]`)
- **Easy Discovery**: `pflow registry list --filter github` shows all GitHub nodes
- **LLM Smart Exception**: General `llm` node prevents proliferation of specific prompt nodes
- **Testable**: Each node can be tested independently
- **Composable**: Simple nodes combine naturally into complex workflows
- **Future CLI Grouping**: v2.0 will add `pflow github get-issue` syntax sugar
- **Impure by default**: Realistic for development workflows

### 3. CLI Execution & Workflow Management
**Purpose**: Execute workflows with parameters and manage reusable definitions

**CLI Commands**:
- `pflow "natural language"` - Generate workflow from description
- `pflow <saved-workflow> --params` - Execute saved workflow with parameters
- `pflow registry list` - Show available nodes and capabilities
- `pflow trace <run-id>` - Detailed execution debugging

**Workflow Storage**:
- Save generated workflows with meaningful names (`fix-issue`, `deploy-staging`)
- Parameterized execution with CLI overrides
- Lockfile generation for reproducible execution

### 4. Foundation Infrastructure
**Purpose**: Core systems enabling the workflow compiler

**pocketflow Integration**:
- Use existing 100-line framework for execution
- Natural shared store pattern with intuitive keys
- `>>` operator for flow composition
- Built-in retry for appropriate nodes

**JSON IR & Validation**:
- Complete workflow definitions with full provenance
- Validation pipeline ensuring generated workflows are executable
- Schema governance for consistency and evolution

### 5. CLI Autocomplete (Post-MVP Enhancement)
**Purpose**: Enhance CLI usability through shell completion

**High-Value Features**:
- Node name completion: `pflow read-f[TAB]` → `read-file`
- Parameter discovery: `pflow read-file --[TAB]` → `--path, --encoding`
- Available nodes after pipe: `pflow read-file => [TAB]` → list of compatible nodes
- Works with LLM backend - shell parses unquoted syntax

**Benefits**:
- Immediate user value for node discovery
- Professional CLI experience
- Smooth path to v2.0 direct parsing
- Helps users learn available nodes and parameters

---

## ❌ Explicitly Excluded from MVP

### Deferred to v2.0 (Post-MVP)
- **Direct CLI parsing**: Parse CLI syntax without LLM (minor optimization only)
- **Conditional transitions**: `node - "fail" >> error_handler` (pocketflow supports this, but adds complexity)
- **Advanced autocomplete**: Type-aware suggestions and compatibility hints
- **CLI Autocomplete**: High-value feature for usability, deferred to prioritize core workflow engine.
- **Shadow store**: Real-time compatibility feedback during composition
- **Interactive prompts**: Asking for missing inputs during execution
- **MCP node integration**: MCP server tool wrapping and execution (moved to v2.0)
- **Lockfile system**: Deterministic execution guarantees
- **Complex error handling**: Advanced retry logic and recovery

### Deferred to v3.0 (Cloud Platform)
- **Multi-user authentication**: Team workflows and permissions
- **Web UI**: Visual flow builder and dashboard
- **Distributed execution**: Cloud job queues and scheduling
- **Advanced caching**: Distributed cache and warming strategies
- **Marketplace**: Flow sharing and discovery platform

---

## 🔑 Critical MVP Dependencies

**These 8 components must work together for MVP success**:

1. **Natural Language Planner**: The core differentiator - transforms descriptions into CLI workflows
2. **Simple Node Registry**: Platform-specific nodes (`github-get-issue`, `claude-implement`, `ci-run-tests`, etc.) with clear single purposes
3. **CLI Workflow Engine**: Execute saved workflows with parameters (`pflow fix-issue --issue=1234`)
4. **JSON IR System**: Capture complete workflow definitions with provenance
5. **Validation Pipeline**: Ensure generated workflows are sound and executable
6. **Shared Store Runtime**: Natural key-based communication between nodes
7. **Execution Tracing**: Step-by-step debugging superior to conversation logs
8. **Workflow Storage**: Save/load named workflows for reuse

---

## 📊 Success Criteria

### Primary Value Metrics
- **Efficiency Gain**: 10x improvement over slash commands (tokens + time)
- **Planning Success**: ≥95% of common development workflows generate valid CLI flows
- **User Adoption**: ≥90% approval rate for generated workflows
- **Execution Reliability**: ≥98% successful execution of valid workflows

### Technical Benchmarks
- **Planning Latency**: ≤800ms average for natural language → validated IR
- **Execution Speed**: ≤2s overhead vs raw Python for 3-node flows
- **Registry Scale**: Support 6-10 platform nodes with 5-10 actions each efficiently
- **Flow Complexity**: Handle 10-node workflows without performance degradation

### Capabilities Demonstrated
- **Natural Language Processing**: `pflow "fix this issue, test it, create PR"` → `github-get-issue => claude-implement => ci-run-tests => github-create-pr`
- **Workflow Reuse**: `pflow fix-issue --issue=1234 --severity=critical`
- **Developer Integration**: Works with existing GitHub/testing/linting workflows
- **Slash Command Migration**: Existing `.claude/commands/*.md` can be transformed naturally

---

## 🎯 End Goal Capability

By MVP completion, developers should be able to:

1. **Describe any common development workflow** in natural language
2. **Get a deterministic, reusable CLI tool** that executes consistently
3. **Replace inefficient slash commands** with fast, predictable workflows
4. **Debug execution issues** with clear step-by-step traces
5. **Share workflows** across team members via saved definitions

**The MVP enables this transformation**:
```bash
# From: Inefficient, variable, token-heavy slash commands
/project:fix-github-issue 1234

# To: Efficient, predictable, reusable workflows
pflow fix-issue --issue=1234
```

This focused scope delivers immediate value to developers frustrated with slash command inefficiencies while building the foundation for expanded workflow automation in future versions.

---

## 🛠 Implementation Phases

### Phase 1: Foundation (Weeks 1-2)
**Goal**: Core infrastructure supporting the AI-assisted development workflow vision

- **pocketflow Integration**: Leverage existing 100-line framework
- **Basic Shared Store**: Natural key-based communication (`shared["issue"]`, `shared["code"]`)
- **Simple CLI Parser**: Handle natural language input and basic workflow execution
- **Node Registry Structure**: Discovery system for developer-focused nodes

### Phase 2: Natural Language Planning (Weeks 3-4)
**Goal**: Core differentiator - transform descriptions into workflows

- **LLM Integration**: Connect to thinking models for intelligent node selection
- **Metadata-Driven Selection**: Extract and use node interface descriptions
- **Workflow Generation**: Natural language → CLI syntax transformation
- **User Verification**: Show generated workflows for approval

### Phase 3: Developer Nodes (Weeks 5-6)
**Goal**: Essential nodes for AI-assisted development workflows

- **GitHub Integration**: `gh-issue` node with view/create/comment actions
- **Claude Code Integration**: `claude-analyze` and `claude-implement` nodes
- **Development Tools**: `run-tests`, `lint`, `git-commit` nodes
- **Shell Integration**: Direct command execution capabilities

### Phase 4: Workflow Management (Weeks 7-8)
**Goal**: Save, reuse, and execute workflows efficiently

- **Workflow Storage**: Save generated workflows with meaningful names
- **Parameterized Execution**: `pflow fix-issue --issue=1234`
- **JSON IR System**: Complete workflow definitions with provenance
- **Execution Tracing**: Step-by-step debugging and observability

---

## 🧪 Validation Strategy

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

---

## 📈 Measuring Success

### Immediate Value Metrics
1. **Time Savings**: Developers save 30-90s per workflow execution
2. **Cost Reduction**: 10x reduction in LLM tokens for repeated workflows
3. **Consistency**: Same workflow produces same results across executions
4. **Observability**: Clear execution traces vs. conversation logs

### Adoption Indicators
1. **Workflow Creation**: Developers successfully generate workflows from natural language
2. **Workflow Reuse**: Saved workflows used multiple times per week
3. **Team Sharing**: Workflows shared and adopted across development teams
4. **Slash Command Replacement**: Developers prefer pflow over existing slash commands

### Technical Health
1. **Planning Success Rate**: ≥95% of reasonable requests generate valid workflows
2. **Execution Reliability**: ≥98% of valid workflows execute successfully
3. **Performance**: Sub-second planning, 2-5s execution for typical workflows
4. **Error Recovery**: Clear diagnostics when workflows fail

---

## 🎯 MVP Acceptance Criteria

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

4. **Achieve 10x efficiency improvement** over equivalent slash commands in terms of:
   - Execution time (consistent 2-5s vs variable 30-90s)
   - Token usage (minimal overhead vs 1000-2000 tokens per run)
   - Reliability (deterministic vs variable approaches)

**When these criteria are met, pflow MVP delivers transformational value to AI-assisted development workflows.**
