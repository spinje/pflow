# Braindump: Task 107 Implementation Context

> **Context**: This braindump captures critical context from a 3-hour conversation about whether/how to implement Task 107 (Markdown Workflow Format) before launch. The user is shipping pflow in 3 days. This implementation is happening NOW.

## Where I Am

The user decided to implement Task 107 + Task 104 (Python Code Node) before launch. Ship in 3 days with markdown format, not JSON. This decision came after deep exploration of:
- Whether markdown is actually valuable (yes, for specific reasons)
- Whether to ship JSON now and iterate (no - "faster horse" problem)
- What the core value of pflow actually is (uncertain, but markdown enables non-dev market)

**Critical timeline**: User has delayed launch multiple times (last time: batch feature, bug fixes). This is the final push. 3 days, then ship. No more delays.

## User's Mental Model

### How They Think About the Problem

**"JSON was a mistake"** - User's exact words. Not "JSON has issues" - it was a MISTAKE. The escaping is "HELL for AI agents right now."

**"Faster horse problem"** - User's framing: "people wont know they want markdown until they try it. Its like a car when people are driving horses. Of course they are going to say they want code."

This is critical: if you ship JSON and ask "would markdown be better?", people say "no, just code." But if you ship markdown, they try it and realize it's better. Don't ask - show.

**"Documentation is code"** - User's insight: "for non devs, seeing the markdown as rendered markdown or even a node visualization would be better for non devs right? the 'code' is essentially documentation. the documentation is code, they are the same thing."

This is the key differentiation for market expansion (Claude Cowork, non-developer agents).

**"All codebases in the future will contain markdown"** - CLAUDE.md, AGENT.md in every subdirectory, Skills are markdown, slash commands are markdown. 1 year ago: 20% of devs wrote markdown for AI. Now: 80-90%. In 1 year: 100%.

Markdown for AI is already the pattern. This isn't introducing new paradigm - it's applying existing pattern to workflows.

**How they prioritize**:
1. Ship in 3 days (absolute requirement)
2. Show the vision (markdown + code node, not painful JSON)
3. Get feedback on what actually matters
4. Iterate based on reality, not speculation

### Terminology (use their words)

- "Building blocks" - the nodes (LLM, MCP, HTTP, shell) that agents compose
- "Documentation drift" - when JSON + README → LLM loses context when editing
- "Faster horse" - asking people what they want vs. showing them something better
- "HELL" - the JSON escaping experience for agents (strong word, intentional)
- "Documentation as code" - implementation IS documentation, can't drift
- "Market expansion" - non-developers using AI agents (Claude Cowork)

## Key Insights That Shaped This

### 1. Validation Already Exists - Just Reuse It

**CRITICAL**: pflow has 6-layer validation for JSON workflows:
1. Structural (required fields, valid node types)
2. Data Flow (template dependencies resolved)
3. Template (${var} syntax valid)
4. Node Type (nodes exist in registry)
5. Output (declared outputs available)
6. JSON anti-pattern

**Your job**: Parse markdown → IR, then ALL existing validation applies automatically.

The work is:
- Markdown → IR parser (new)
- Markdown-specific validation (code fences, YAML syntax)
- Hook up existing IR validation (should just work)

Don't reimplement validation. Reuse what exists.

**Location**: Check `src/pflow/runtime/` for existing validation. The IR validation is format-agnostic.

### 2. AI Agents Don't Use Debuggers

We explored "debugging markdown is harder than Python" concern.

**Reality**: AI agents don't use:
- Breakpoints
- Step-through debugging
- pdb or IDE debuggers

AI agents debug by:
- Reading error messages (pflow provides structured errors)
- Inspecting traces (`pflow read-fields exec-id node.output`)
- Reading the workflow
- Modifying and retrying

Markdown is NOT harder to debug. Might be easier (clearer structure, documentation right there).

The "can't use Python debugger" argument is irrelevant for AI agents.

### 3. Template Variables Won't Clash with Markdown Libraries

**Question explored**: Will `${fetch.response}` clash with markdown parsing?

**Answer**: No. Markdown libraries parse structure (headings, code fences). They treat `${...}` as literal text. You extract the text, then parse templates yourself.

**How it works**:
```
Raw markdown
    ↓
Markdown library (parses structure: headings, code blocks, YAML)
    ↓
Structured data (headings, code content, parameters)
    ↓
Your validation (parse ${...}, check node references, validate IR)
```

Library: syntax layer (what's a heading, what's a code block)
You: semantic layer (what nodes are valid, what templates reference)

No clash. Different layers.

**Recommendation**: Use `mistune` or `markdown-it-py` for parsing. They're mature, handle edge cases (nested fences, etc.).

### 4. Code Fence Validation (Four Backticks Example)

User asked: "what if agent writes ```` instead of ```?"

**Answer**: Markdown library catches this. It parses ```` as fence with language marker "`python" (wrong). You validate: "expected language tag, found '`python'" and give clear error.

**Your job**: After markdown library parses, validate:
- Code fences have valid language tags (python, shell, prompt, etc.)
- No extra backticks
- Properly closed

The library handles syntax. You handle semantic validation.

### 5. The Ecosystem Shift Is Real

**Context**: 1 year ago, literate programming failed (documentation + code in one file). Why would markdown workflows succeed?

**Answer**: The landscape already shifted. Developers are ALREADY writing markdown for AI:
- CLAUDE.md (project instructions)
- SKILL.md (skills are markdown)
- Slash commands (markdown format)
- .cursorrules, .clinerules

Markdown-for-AI is mainstream. pflow workflows fit this existing pattern.

This isn't "learn new paradigm" (like literate programming was). This is "use the same pattern you already know."

Lower adoption barrier than I initially thought.

## Assumptions & Uncertainties

**ASSUMPTION**: The existing IR structure can represent everything markdown workflows need.
- User says it can (they designed Task 107 with this in mind)
- But verify: does IR support inline documentation? Node-level docs?
- Check: `src/pflow/models/` or wherever IR is defined

**ASSUMPTION**: Existing validation code can be called on markdown-parsed IR without modification.
- User confirmed validation is format-agnostic
- But verify the integration points
- Check: how is validation called for JSON workflows? Same entry point should work.

**UNCLEAR**: Exact format for inline documentation in markdown.
- Task 107 shows examples but might not be final
- User might want flexibility (docs before node? after? both?)
- Clarify before implementing parsing

**UNCLEAR**: How to handle code node (Task 104) inputs.
- User said 4 hours to implement
- But markdown format for code node isn't fully specified
- Check Task 104 description, might need to coordinate

**NEEDS VERIFICATION**: Line number tracking for errors.
- Markdown library provides line numbers
- But after parsing → IR, do line numbers get preserved?
- Error messages should reference markdown lines, not IR structure
- Verify how to track source locations through the pipeline

**NEEDS VERIFICATION**: Export to Python still works.
- User has task for "export to no dependency Python"
- Markdown → IR → Python export should work
- But verify the export logic doesn't assume JSON source
- Location: check for export functionality in codebase

## Unexplored Territory

**UNEXPLORED**: How to handle workflow versioning.
- If markdown format evolves, how do old workflows parse?
- Might need version marker in frontmatter
- Consider: `version: 1.0` in YAML frontmatter

**UNEXPLORED**: Visualization generation from markdown.
- User mentioned "render as flowchart for non-developers"
- Is there existing visualization code for JSON workflows?
- If yes, should work with IR → same visualization
- If no, this is future work (not blocking launch)

**IMPLEMENT**: Linting integration for code blocks.
- **This is required for feature-complete implementation**
- Extract Python blocks → run `ruff check`
- Extract shell blocks → run `shellcheck`
- Handle template variables: replace `${...}` with placeholders before linting
- Map errors back to markdown line numbers
- Integrate with validation pipeline
- 6-8 hours while you have context vs. 2-3 days later (cold start)
- User wants complete implementation, not MVP iteration

**Why implement linting when VSCode provides it for free?**
- **VSCode linting is free for human users** - workflow.md files get automatic linting in editors
- **But pflow linting is for agents** - agents don't use VSCode, they generate workflows programmatically
- **Template variable handling** - VSCode shows false errors on `${fetch.response}` (invalid Python), pflow handles correctly
- **Runtime validation** - catch errors before execution (CI/CD, command-line, automation)
- **Two levels**: Editor linting (human authors, free) + pflow linting (agent authors + runtime, implement)

User quote: "agents are writing the workflows" - this is the primary use case. Editor linting is convenience for humans, pflow linting is essential for agents.

**MIGHT MATTER**: Workflow composition (workflows calling workflows).
- How does this work in markdown format?
- Is there a `type: workflow` node that references another markdown file?
- Check existing JSON workflows for this pattern
- Ensure markdown format supports it

**MIGHT MATTER**: MCP server integration.
- User has MCP server mode where agents use pflow via MCP
- Does this work with markdown workflows?
- Check: `src/pflow/mcp_server/` - how are workflows loaded?
- Ensure markdown workflows can be discovered/executed via MCP

**MIGHT MATTER**: Batch workflows.
- User implemented batch feature recently (one of the delays)
- How does batch work in markdown format?
- Check Task 107 for batch syntax
- Ensure IR mapping preserves batch semantics

**MIGHT MATTER**: Template variable type inference.
- Current validation checks if `${node.field}` references valid node
- Does it check if field exists on that node's output?
- This might require running nodes to know output structure
- OR might require declared output schemas
- Check existing validation depth

## What I'd Tell Myself

### If I Were Implementing This

**Start here**:
1. Read Task 107 fully (you have it)
2. Read existing IR definition (`src/pflow/models/` or similar)
3. Read existing JSON workflow parsing (`src/pflow/runtime/compiler.py` or similar)
4. Understand: JSON → IR → validation → execution pipeline

**Then**:
1. Implement markdown parser (use `mistune`)
2. Map markdown structure → same IR as JSON
3. Run existing validation on the IR (should just work)
4. Add markdown-specific errors (YAML syntax, code fence issues)
5. Test against example workflows

**Don't**:
- Reimplement validation from scratch
- Try to make perfect before testing
- Implement visualization (future work)
- Implement linting integration unless trivial
- Spend time on features not needed for launch

**The user wants**:
- Good enough to ship in 3 days
- Better than JSON (definitely achievable)
- Validates structure and catches errors
- Clear error messages for agents

Not:
- Perfect validation of every edge case
- Comprehensive error recovery
- Advanced type checking
- Feature completeness beyond MVP

### Testing Strategy

**Must test**:
- All example workflows from `examples/` (convert JSON → markdown, verify same execution)
- Template variables work (`${node.field}` resolves correctly)
- Error messages are clear (make intentional errors, verify messages)
- Validation catches errors before execution (try invalid workflows)

**Key test cases**:
- Workflow with LLM node (prompts as text, no escaping)
- Workflow with shell/Python code node (code blocks work)
- Workflow with MCP node (parameters as YAML)
- Workflow with template variables (data flow works)
- Workflow with documentation (inline prose preserved or ignored appropriately)
- Invalid workflow (missing required field, unknown node type, bad template reference)

### Error Message Quality

**Critical**: Error messages are designed for AI agents, not humans.

**Good error**:
```json
{
  "error": "Node 'fetch' does not output 'msg'",
  "available_fields": ["response.body", "response.status", "response.headers"],
  "fixable": true,
  "location": "line 15: prompt: ${fetch.msg}"
}
```

**Bad error**:
```
ParseError: Invalid syntax at line 15
```

Include:
- What's wrong (specific)
- What's available (alternatives)
- Where (line number, context)
- How to fix (if obvious)

Check existing JSON workflow error messages for format/structure. Match that quality.

## Open Threads

### User's Uncertainty About Core Value

We explored: "Is markdown the core value of pflow?"

**Answer**: Probably not. More likely core values:
- Building blocks (80% confidence) - unified LLM + MCP + shell + HTTP
- CLI composability (70%) - workflows as Unix commands
- Traces (60%) - structured debugging for agents
- Markdown documentation-as-code (40%) - valuable but unclear if differentiating

**Implication**: Don't position markdown as THE innovation. Position as:
- "Workflows are readable for non-developers (rendered markdown + flowchart)"
- "Documentation integrated (solves drift problem for AI editing)"
- Enabler for market expansion, not the core value itself

But ship it because:
- Better than JSON (definitely)
- Fits ecosystem (Skills, CLAUDE.md pattern)
- Shows vision (not painful prototype)
- Low risk, potential upside

### The README Will Come After

User wants to write README after markdown + code node are implemented. They want to show examples in the new format.

**Don't worry about README in this task.** Just implement markdown format well enough to:
- Parse workflows
- Execute them
- Validate them
- Give good errors

User will handle positioning/communication after seeing it work.

### Export to Python (Future Consideration)

User has task for "export to no dependency Python."

This means:
- Markdown workflow → Python code (standalone, no pflow runtime required)
- pflow is creation tool, not execution infrastructure

**Don't implement export in this task.** But ensure:
- IR structure supports export (probably already does)
- Markdown → IR doesn't lose information needed for export
- When export task comes, it can work from IR

## Relevant Files & References

**Task 107 Specification**:
- `/Users/andfal/projects/pflow/.taskmaster/tasks/task_107/task-107.md`
- Read this fully - has examples, design decisions, implementation notes

**Existing Architecture**:
- `/Users/andfal/projects/pflow/architecture/overview.md` - Conceptual foundation
- `/Users/andfal/projects/pflow/architecture/architecture.md` - Implementation details
- These explain IR, validation layers, execution pipeline

**PocketFlow (underlying framework)**:
- `/Users/andfal/projects/pflow/pocketflow/__init__.py` - ~200 lines, workflow orchestration
- Understand: Node, Flow, prep/exec/post lifecycle

**Progress Log** (this conversation documented):
- `/Users/andfal/projects/mainframe/projects/pflow/writing/readme/progress-log.md`
- Session 3 has architectural exploration, decision-making process

**Example Workflows**:
- Check `/Users/andfal/projects/pflow/examples/` or similar
- Convert these to markdown as test cases

**Existing Validation** (reuse this):
- Look for: `src/pflow/runtime/`, `src/pflow/validation/`, `src/pflow/compiler/`
- 6-layer validation system exists
- Error message format exists
- Template variable validation exists

**Node Registry**:
- Node types: LLM, HTTP, shell, MCP, file, claude-code
- Registry likely in: `src/pflow/registry/` or `src/pflow/nodes/`
- Need to validate node types against registry

## For the Next Agent

### Start By

1. **Read Task 107 fully** - it has examples and design decisions
2. **Explore the codebase**:
   - How are JSON workflows currently parsed?
   - Where is the IR defined?
   - How is validation called?
   - Where are error messages generated?
3. **Find an example JSON workflow** - you'll convert this to markdown as your test case
4. **Choose markdown library** - `mistune` recommended, but verify it handles code fences correctly
5. **Write a minimal parser** - single workflow, no validation, just markdown → IR
6. **Test execution** - can the IR execute via existing pipeline?
7. **Add validation** - hook up existing validation, add markdown-specific checks
8. **Iterate on errors** - make error messages clear and actionable

### Implement Feature-Complete (Don't Ship Half-Baked)

**CRITICAL UPDATE**: User wants feature-complete implementation, not MVP.

**The momentum argument**: Adding features while you're deep in the codebase is 6-8 hours. Coming back later (cold start) is 2-3 days. Use your momentum.

**Must implement**:
- ✅ Markdown parsing → IR
- ✅ All validation (reuse existing + markdown-specific)
- ✅ **Linting** (Python + shell code blocks) - include this
- ✅ Template variable handling (in code AND in linting)
- ✅ Code node integration (Task 104)
- ✅ Comprehensive error messages (line numbers, context, suggestions)
- ✅ Edge case handling (nested fences, YAML errors, invalid templates)
- ✅ All node types working (LLM, MCP, HTTP, shell, file, claude-code)

**Don't implement** (separate concerns):
- Visualization generation (future work, separate task)
- Export to Python (separate task exists)
- README or documentation (user handles after)

**Linting implementation** (since you're building validation anyway):
1. Extract code blocks (you're already doing this)
2. Replace template variables with placeholders: `${node.field}` → `__TEMPLATE_VAR_1__`
3. Run linters: `ruff check` for Python, `shellcheck` for shell
4. Parse linter output (structured format available)
5. Map errors back to markdown line numbers (you're tracking these)
6. Add to validation pipeline (you're building this)

Estimated: 6-8 hours while you have context. Worth it.

### The User Cares Most About

1. **Shipping in 3 days** - absolute priority, no more delays
2. **Better than JSON** - agents can write without escaping hell
3. **Validates correctly** - catches errors before execution
4. **Clear error messages** - agents can fix issues
5. **Documentation integrated** - solves drift problem

Not:
- Perfect feature completeness
- Advanced capabilities
- Polished UX
- Comprehensive edge case handling

### Red Flags to Watch For

**If you find**: JSON workflows have features markdown can't represent
**Then**: Ask user how to handle (don't guess)

**If you find**: Existing validation assumes JSON structure
**Then**: Refactor to work with IR (should be format-agnostic but verify)

**If you find**: IR doesn't preserve source location (line numbers)
**Then**: Add source location tracking (needed for error messages)

**If you find**: Template variable parsing is JSON-specific
**Then**: Extract it to work with any source format

**If you find**: Implementing this will take >3 days
**Then**: Clarify with user what's MVP vs. nice-to-have

### Implementation Confidence

**High confidence this works**:
- Markdown → IR parsing (straightforward)
- Reusing existing validation (should just work)
- Template variables preserved (markdown libraries handle this)

**Medium confidence**:
- Error message quality (need to test and iterate)
- Edge case handling (might discover issues during testing)
- Integration with existing tooling (MCP server, CLI, etc.)

**Low confidence / needs verification**:
- Inline documentation preservation (is this needed? where stored?)
- Source location tracking through pipeline (for error messages)
- Batch workflow syntax in markdown (check Task 107 for this)

### Success Criteria

**You've succeeded if**:
1. Agent can write markdown workflow and execute it
2. Same execution as equivalent JSON workflow
3. Validation catches errors with clear messages
4. Template variables work (`${node.field}` resolves)
5. Code blocks work (Python code node integration)
6. All example workflows can be converted and run
7. User can ship in 3 days

**You can iterate on**:
- Perfect error messages
- Comprehensive edge cases
- Advanced validation
- Linting integration
- Visualization

Ship good enough, iterate based on real usage.

---

> **Note to next agent**: Read this document fully before taking any action. Verify assumptions by exploring the codebase using subagents. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
