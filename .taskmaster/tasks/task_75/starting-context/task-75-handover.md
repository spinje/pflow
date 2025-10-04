# Task 75: Execution Preview - Handoff Memo

**From**: Context-rich agent (Task 71 completion)
**To**: Implementation agent (Task 75)
**Date**: 2025-10-03
**Context Window Reset**: This memo captures tacit knowledge that won't survive the reset

---

## 🎯 Why This Task Exists (The Real Story)

This task emerged from **actual agent pain** during Task 71 implementation and testing. I (the previous agent) built two real workflows as an AI agent:
1. Simple file analyzer (3 nodes)
2. Complex Slack QA workflow (8 nodes: shell → Slack → LLM → Slack → Sheets)

When validating the 8-node workflow with `--validate-only`, I got:
```
✓ Schema validation passed
✓ Data flow validation passed
✓ Template structure validation passed
✓ Node types validation passed

Workflow is valid and ready to execute!
```

**My reaction**: "Great, it's valid... but what will actually happen?"

I couldn't answer:
- What order will the 8 nodes execute?
- How does data flow from Slack → LLM → Slack?
- Do I have the right API keys configured?
- Will this cost me $5 or $0.05?

This forced me to **execute blindly**, hit runtime errors, discover I was missing ANTHROPIC_API_KEY, fix it, try again. Classic trial-and-error.

**The insight**: `--validate-only` tells me the workflow is *structurally sound* but gives zero visibility into *what will actually happen*.

This task fixes that.

---

## 📊 What Agents Actually Need (Based on Real Experience)

After documenting my pain in `scratchpads/task-71-agent-experience/AGENT_FEEDBACK_AND_IMPROVEMENTS.md`, I identified **exactly** what execution preview should show:

### The 4 Critical Questions

**1. What will execute?**
- All 8 nodes in execution order
- Node types (shell, mcp-slack, llm, mcp-sheets)
- What each node outputs

**2. How does data flow?**
- `get-date.stdout` → `fetch-messages.params.since`
- `fetch-messages.result` → `analyze.params.prompt`
- `analyze.response` → `send-response.params.markdown_text`
- `analyze.response` → `log.params.values`

**3. What credentials are needed?**
- ✗ ANTHROPIC_API_KEY (missing! Will fail at node 3)
- ✓ COMPOSIO_API_KEY (present, covers nodes 2, 4, 5)

**4. What's it going to cost?**
- Duration: ~8-12 seconds (rough estimate)
- Cost: ~$0.05 (LLM tokens)
- API calls: 4 external requests

### The Exact Output Format (From Real Testing)

This is **NOT theoretical**. This is the output I wrote after manually tracing my 8-node workflow:

```
✓ Workflow is valid and ready to execute!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 Execution Preview
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Node Execution Order:
  1. get-date (shell) → stdout, stderr
  2. fetch-messages (mcp-slack-composio-SLACK_LIST_MESSAGES) → result
  3. analyze (llm) → response, llm_usage
  4. send-response (mcp-slack-composio-SLACK_SEND_MESSAGE) → result
  5. log (mcp-sheets-composio-GOOGLESHEETS_BATCH_UPDATE) → result

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔗 Data Flow
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

get-date.stdout → fetch-messages.params.since
fetch-messages.result → analyze.params.prompt
analyze.response → send-response.params.markdown_text
analyze.response → log.params.values

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔐 Required Credentials
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✗ ANTHROPIC_API_KEY (for: analyze)
✓ COMPOSIO_API_KEY (for: fetch-messages, send-response, log)

⚠️  Missing credentials will cause runtime failures

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⏱️  Estimates
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Duration: ~8-12 seconds
Cost: ~$0.05 (LLM tokens)
API Calls: 4 external requests
```

**This is the gold standard**. Implement this output, you solve the problem.

---

## 💎 The Hidden Gems (What You Won't Find in Docs)

### Gem 1: WorkflowValidator Already Has Execution Order

**Location**: `src/pflow/runtime/workflow_validator.py`

The `validate_data_flow()` function already computes **topological sort** of nodes to check for cycles. This IS the execution order you need.

**Key insight**: Don't re-implement topological sort. Extract it from validation results.

**What to investigate**: How does `validate_data_flow()` return its results? Can you access the sorted node list?

### Gem 2: TemplateValidator Already Parses Templates

**Location**: `src/pflow/runtime/template_validator.py`

This validator already:
- Parses all `${...}` templates in node parameters
- Validates that source nodes exist
- Validates that output fields exist

**Key insight**: It knows which templates reference which nodes. You just need to extract the mapping.

**Pattern to look for**: Template `${fetch.result}` → knows it references node "fetch", field "result"

### Gem 3: Credential Detection is Simple Pattern Matching

You don't need a complex system. Just pattern match on node types:

```python
def detect_credentials(node_type: str) -> list[str]:
    if node_type == "llm":
        return ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]  # OR relationship

    if node_type.startswith("mcp-"):
        # Extract server name: "mcp-slack-composio-TOOL" → "slack"
        parts = node_type.split("-")
        if len(parts) >= 3:
            server = parts[1]  # e.g., "slack"
            return [
                "COMPOSIO_API_KEY",  # Universal MCP key
                f"{server.upper()}_API_KEY"  # Service-specific
            ]

    if node_type == "shell":
        return []  # No creds needed, but show command

    return []
```

**Key insight**: OR relationship matters. COMPOSIO_API_KEY works for ALL MCP tools. Service-specific keys are alternatives, not requirements.

### Gem 4: Don't Overthink Estimates

Heuristics are **good enough**:

```python
# Duration
if node_type == "shell": duration = 1  # <1 second
if node_type.startswith("mcp-"): duration = 3  # API call ~2-3s
if node_type == "llm": duration = 5  # LLM call ~3-5s
total = sum(durations)

# Cost
if node_type == "llm":
    # Rough estimate: 1000 input tokens, 500 output tokens
    cost = (1000 * 3 / 1_000_000) + (500 * 15 / 1_000_000)  # Sonnet 4 rates
```

**Key insight**: Precision doesn't matter. Agents just need rough idea. "~$0.05" is infinitely better than no info.

---

## 🏗️ Integration Points (Where to Hook In)

### Primary Integration: CLI Main

**File**: `src/pflow/cli/main.py`
**Location**: Around line 2950 (search for `--validate-only` handler)

**Current code** (approximately):
```python
validate_only = ctx.obj.get("validate_only", False)
if validate_only:
    # Current: Just validate and show basic results
    _validate_and_handle_workflow_errors(ir_data, ctx, output_format, verbose, metrics_collector)

    if output_format == "json":
        click.echo(json.dumps({"success": True, "message": "Workflow is valid"}))
    else:
        click.echo("✅ Workflow is valid")
    ctx.exit(0)
```

**Your enhancement**:
```python
validate_only = ctx.obj.get("validate_only", False)
if validate_only:
    # Validate (existing)
    _validate_and_handle_workflow_errors(ir_data, ...)

    # NEW: Generate preview
    from pflow.runtime.execution_preview import generate_execution_preview
    preview = generate_execution_preview(
        ir_data=ir_data,
        registry=Registry(),
        execution_params=enhanced_params
    )

    # Display preview
    _display_execution_preview(preview, output_format)
    ctx.exit(0)
```

### Data Source 1: WorkflowValidator

**File**: `src/pflow/runtime/workflow_validator.py`

**What you need from it**:
- Execution order (topological sort result)
- Validated edges (for data flow)

**How to get it**: Read the code. See if `validate()` returns structured data you can use.

### Data Source 2: TemplateValidator

**File**: `src/pflow/runtime/template_validator.py`

**What you need from it**:
- Template → node mapping
- Template → field mapping

**Pattern**: `${fetch.result.messages[0]}` → node="fetch", path="result.messages[0]"

### Data Source 3: Registry

**File**: `src/pflow/registry/registry.py`

**What you need from it**:
- Node metadata (for output field names)
- Node types (for credential detection)

**Usage**: `registry.load()` gives you all node metadata

---

## ⚠️ Critical Design Constraints (What NOT to Do)

### DON'T Execute Anything

Execution preview must be **pure static analysis**. Never:
- Instantiate nodes
- Call `compile_ir_to_flow()`
- Run `flow.run()`
- Make API calls
- Execute shell commands

**Why**: Preview should be instant (<100ms) and have zero side effects.

### DON'T Aim for Precision

**Wrong mindset**: "Let me calculate exact token counts for accurate cost"
**Right mindset**: "Rough estimate: small prompt = $0.01, medium = $0.05, large = $0.20"

**Why**: Precision requires loading models, analyzing prompts, etc. Overkill for preview.

### DON'T Add ASCII Graphs

I know it's tempting:
```
     ┌──────────┐
     │ get-date │
     └────┬─────┘
          │
     ┌────▼────────┐
     │   fetch     │
```

**Don't do it**. Complexity explosion:
- Graph layout algorithms
- Terminal width detection
- Unicode compatibility
- Handling parallel branches

**Keep it simple**: Text list of data flows is enough.

### DON'T Use Actual Compilation

**Wrong approach**: Compile to Flow, inspect Flow object structure
**Right approach**: Parse IR directly, use validator results

**Why**: Compilation is slow and requires node instantiation (side effects).

---

## 🎨 The Implementation Strategy (What Actually Works)

### Create New Module

**File**: `src/pflow/runtime/execution_preview.py`

**Core function**:
```python
def generate_execution_preview(
    ir_data: dict,
    registry: Registry,
    execution_params: dict
) -> dict:
    """Generate execution preview from validated workflow IR.

    Returns:
        {
            "execution_order": [
                {"node_id": "get-date", "type": "shell", "outputs": ["stdout", "stderr"]},
                {"node_id": "fetch", "type": "mcp-slack", "outputs": ["result"]},
                ...
            ],
            "data_flow": [
                {"source": "get-date.stdout", "destination": "fetch.params.since"},
                ...
            ],
            "required_credentials": {
                "ANTHROPIC_API_KEY": {"present": False, "nodes": ["analyze"]},
                "COMPOSIO_API_KEY": {"present": True, "nodes": ["fetch", "send", "log"]},
            },
            "estimates": {
                "duration_seconds": 10,
                "cost_usd": 0.05,
                "api_calls": 4
            }
        }
    """
    # 1. Extract execution order from IR edges (topological sort)
    # 2. Parse templates to build data flow map
    # 3. Detect credentials from node types
    # 4. Calculate rough estimates
    # 5. Return structured dict
```

### Helper Functions You'll Need

```python
def _extract_execution_order(ir_data: dict) -> list[dict]:
    """Topological sort of nodes based on edges."""
    # Hint: WorkflowValidator might already do this

def _build_data_flow_map(ir_data: dict) -> list[dict]:
    """Parse templates and map data flow."""
    # Hint: Look for ${...} patterns in node params

def _detect_required_credentials(nodes: list[dict]) -> dict:
    """Pattern match on node types to detect creds."""
    # Hint: Check os.environ to see if present

def _estimate_execution(nodes: list[dict]) -> dict:
    """Rough heuristics for duration and cost."""
    # Hint: Count node types, use fixed estimates
```

---

## 🧪 Testing Strategy (What Actually Matters)

### Test with Real Task 71 Workflows

**The 8-node Slack QA workflow is your gold standard**. It's in `.pflow/workflows/` (if saved) or you can recreate it:

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "get-date", "type": "shell", "params": {"command": "date +%Y-%m-%d"}},
    {"id": "fetch-messages", "type": "mcp-slack-composio-SLACK_LIST_MESSAGES", "params": {...}},
    {"id": "analyze", "type": "llm", "params": {...}},
    {"id": "send-response", "type": "mcp-slack-composio-SLACK_SEND_MESSAGE", "params": {...}},
    {"id": "log", "type": "mcp-sheets-composio-GOOGLESHEETS_BATCH_UPDATE", "params": {...}}
  ],
  "edges": [...]
}
```

**Why this matters**: This is a REAL workflow that exposed the pain point. If preview works here, it works.

### Edge Cases from Real Experience

1. **Empty workflow** (0 nodes) - Should show "No nodes to execute"
2. **Single node** - Should show simple execution (no data flow)
3. **No templates** - Data flow section should say "No template dependencies"
4. **Missing credentials** - Should warn loudly
5. **Complex templates** - `${node.result.messages[0].text}` should parse correctly

### Manual Testing is Critical

**You MUST manually test** with different workflow types:
- Simple: read → write
- Medium: read → llm → write
- Complex: 8-node Slack workflow
- With missing creds (unset ANTHROPIC_API_KEY)
- With all creds present

**Verify the output LOOKS right**. This is UX, not just correctness.

---

## 📚 Files to Read First (Priority Order)

### 1. Agent Feedback Document (THE SOURCE OF TRUTH)
**File**: `scratchpads/task-71-agent-experience/AGENT_FEEDBACK_AND_IMPROVEMENTS.md`

**Why read**: This has:
- The exact pain point (#5)
- The exact output format (copy it!)
- The exact workflow tested (8-node Slack)
- Design rationale for all decisions

**Time investment**: 15 minutes to read section #5 thoroughly

### 2. WorkflowValidator (HAS THE ORDER)
**File**: `src/pflow/runtime/workflow_validator.py`

**What to find**:
- How `validate_data_flow()` works
- Where topological sort happens
- What data structure it returns

**Time investment**: 10 minutes to understand flow

### 3. TemplateValidator (HAS THE TEMPLATES)
**File**: `src/pflow/runtime/template_validator.py`

**What to find**:
- How templates are parsed (regex pattern)
- How template→node mapping is built
- What validation data is available

**Time investment**: 10 minutes to understand parsing

### 4. CLI Main (WHERE TO INTEGRATE)
**File**: `src/pflow/cli/main.py`

**What to find**:
- Line ~2950: `--validate-only` handler
- How validation is called
- How to add preview display

**Time investment**: 5 minutes to find integration point

### 5. Registry (NODE METADATA)
**File**: `src/pflow/registry/registry.py`

**What to find**:
- How to load registry
- What metadata is available per node
- How to get output field names

**Time investment**: 5 minutes to understand structure

---

## 🔥 The Gotchas (Learned the Hard Way)

### Gotcha 1: Template Paths Are Complex

Templates aren't just `${node.output}`. They're:
- `${node.result.messages[0].text}` (array indexing)
- `${node.data.user.email}` (nested objects)
- `${workflow.inputs.repo}` (workflow-level inputs)

**Solution**: Don't try to parse the full path. Just extract node name and show the full template.

**Example**: `${fetch.result.messages[0]}` → "fetch.result.messages[0]" (keep as string)

### Gotcha 2: MCP Nodes Have Multiple Credential Options

For `mcp-slack-composio-TOOL`:
- Option 1: COMPOSIO_API_KEY (universal)
- Option 2: SLACK_API_KEY (service-specific)

These are **OR**, not AND. If either is present, node works.

**Solution**: Show both options, mark as "(OR)" relationship.

### Gotcha 3: Shell Nodes Are Special

For shell nodes:
- Don't show credentials (none needed)
- DO show the command that will execute
- Security: Don't expand templates in command preview

**Example**:
```
1. get-date (shell)
   Command: date +%Y-%m-%d
   Outputs: stdout, stderr
```

### Gotcha 4: Cost Estimates Need Model Defaults

LLM nodes can use different models:
- claude-sonnet-4: $3/M input, $15/M output
- claude-opus-4: $15/M input, $75/M output
- gpt-4: Different rates

**Solution**: Use Sonnet 4 rates as default (most common). Note it's an estimate.

### Gotcha 5: Parallel Branches Are Tricky

Some workflows have parallel execution:
```
     A
    / \
   B   C
    \ /
     D
```

Execution order for B and C is non-deterministic (both depend only on A).

**Solution**: Show execution order as computed (one valid ordering), note "parallel nodes may execute in any order".

---

## 🎓 Final Wisdom (Things I Wish I Knew)

### 1. The Feedback Document is GOLD

Everything you need is in `AGENT_FEEDBACK_AND_IMPROVEMENTS.md`. The output format, the rationale, the edge cases. **Read it first**.

### 2. This Is About UX, Not Technical Complexity

The technical implementation is straightforward (pattern matching, text formatting). The hard part is making the output **readable and useful**.

**Test your output on the 8-node workflow**. If it's not immediately clear what will execute, redesign.

### 3. Agents Need to See, Not Infer

Bad: "Templates are valid"
Good: "get-date.stdout → fetch-messages.params.since"

Bad: "Credentials may be required"
Good: "✗ ANTHROPIC_API_KEY (missing! Node 'analyze' will fail)"

**Show, don't tell.**

### 4. Simple Heuristics > Complex Precision

An estimate of "~$0.05" with 50% accuracy is **infinitely better** than no estimate.

Don't spend 4 hours building precise token counting. Spend 30 minutes on rough heuristics.

### 5. Text Output is Sufficient

Unicode box characters (━━━) are fine. ASCII art graphs are not needed.

**Keep it simple**. Text list of data flows is clear and works everywhere.

### 6. The MVP Philosophy

We have ZERO users. This means:
- Output format can change anytime
- No backwards compatibility
- Simple > elegant
- Working > perfect

**Ship it working, refine later.**

### 7. Integration is the Risky Part

The preview generation logic is low risk (pure function, no side effects).

The CLI integration is higher risk (existing code, validation flow, output formatting).

**Test the integration thoroughly**. Make sure preview only shows when validation succeeds.

---

## 🚦 When You're Ready

**Before you start implementing**, make sure you've:

1. ✅ Read the agent feedback document (section #5 specifically)
2. ✅ Looked at WorkflowValidator to understand execution order
3. ✅ Looked at TemplateValidator to understand template parsing
4. ✅ Found the --validate-only handler in CLI main.py
5. ✅ Understood the output format from the feedback example

**Then**:
- Create `src/pflow/runtime/execution_preview.py`
- Implement `generate_execution_preview()` function
- Add CLI integration in main.py
- Test with the 8-node Slack workflow
- Write tests

**Don't start until you've read those files**. Trust me, it'll save you hours of backtracking.

---

## 📝 Questions to Investigate During Implementation

Things I don't know from my context window that you'll need to figure out:

1. **WorkflowValidator**: What exactly does `validate_data_flow()` return? Can you extract execution order from it?

2. **TemplateValidator**: Does it return a mapping of templates→nodes, or do you need to parse IR yourself?

3. **Registry metadata**: Do node specs include credential requirements, or do you need to infer from node type?

4. **Output fields**: How do you get the list of output fields for MCP nodes? Registry metadata? Node docstrings?

5. **CLI integration**: Is there a helper for formatting validation results, or do you build from scratch?

---

## ✋ STOP - Read First, Then Say You're Ready

**DO NOT start implementing yet.**

Your next message should be: "I've read the handoff memo and I'm ready to begin Task 75 implementation."

Then I (or the user) will confirm you should proceed.

**Why this matters**: Jumping straight to implementation without reading the referenced files will cause you to miss critical insights (like WorkflowValidator already having execution order).

Take 30 minutes to read:
1. Agent feedback document (section #5)
2. WorkflowValidator code
3. TemplateValidator code
4. CLI main.py --validate-only handler

**Then** you'll be ready to build this quickly and correctly.

Good luck! This feature will transform the agent experience. 🚀

---

**Handoff complete. Context window reset imminent.**
