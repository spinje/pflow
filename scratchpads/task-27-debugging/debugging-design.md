# Task 27: Planner Debugging Capabilities Design

## Executive Summary

The planner currently provides minimal visibility into its operation, making debugging nearly impossible. We need a comprehensive debugging system that shows developers exactly what's happening at each step without overwhelming them with raw LLM output.

## Current Problems

1. **No Progress Indication**: Users wait 10-30+ seconds with no feedback
2. **Raw LLM Output**: Unstructured JSON dumps that clutter the output
3. **No Flow Visualization**: Can't see which path (A or B) was taken
4. **Hidden Failures**: Errors buried in nested structures
5. **No Timing Information**: Can't identify performance bottlenecks
6. **Missing Context**: Don't know what the LLM "sees" when making decisions

## Proposed Solution: Multi-Level Debug System

### 1. Three Debug Levels

#### **Level 1: Progress Mode (--verbose)**
Shows high-level progress with minimal clutter:
```
🔍 Discovering existing workflows...
  ✓ Found 3 potential matches
📦 Browsing available components...
  ✓ Selected 5 relevant nodes
🤖 Generating workflow...
  ✓ Created workflow with 3 nodes
✅ Validation passed
📝 Extracting parameters...
  ✓ Found: input_file=data.csv, output_format=json
```

#### **Level 2: Debug Mode (--debug-planner)**
Shows detailed decision-making without raw JSON:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔍 DISCOVERY NODE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Input: "analyze the issues in my repo and create a report"
Context: 15 workflows available, 3 relevant

Decision: NOT_FOUND (confidence: 0.3)
Reason: No existing workflow handles both issue analysis AND report generation
Best match: "issue-triage-report" (60% match)

Time: 2.3s | Tokens: 450 in / 120 out
Next: ComponentBrowsingNode
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

#### **Level 3: Trace Mode (--trace-planner)**
Full execution trace with shared store snapshots:
```
[TRACE] Flow execution started
[TRACE] Shared store initialized with 2 keys: user_input, workflow_manager

[TRACE] >>> Entering WorkflowDiscoveryNode.prep()
[TRACE] Building discovery context...
[TRACE] Context size: 4.2KB, 15 workflows loaded
[TRACE] <<< Exiting WorkflowDiscoveryNode.prep() [120ms]

[TRACE] >>> Entering WorkflowDiscoveryNode.exec()
[TRACE] LLM Request:
  Model: anthropic/claude-3-sonnet
  Prompt length: 4500 chars
  Schema: WorkflowDecision
[TRACE] LLM Response received [2100ms]
[TRACE] Parsed result: {found: false, confidence: 0.3, ...}
[TRACE] <<< Exiting WorkflowDiscoveryNode.exec() [2100ms]

[TRACE] Shared store after discovery:
  + discovery_result: {found: false, workflow: null}
  + discovery_reasoning: "No exact match found"
```

### 2. Debug Information Architecture

#### **DebugContext Class**
```python
@dataclass
class DebugContext:
    level: DebugLevel  # PROGRESS, DEBUG, TRACE
    start_time: float
    current_node: Optional[str] = None
    node_timings: Dict[str, float] = field(default_factory=dict)
    llm_calls: List[LLMCall] = field(default_factory=list)
    shared_snapshots: List[SharedSnapshot] = field(default_factory=list)
    flow_path: List[str] = field(default_factory=list)

@dataclass
class LLMCall:
    node: str
    model: str
    prompt_length: int
    response_time: float
    tokens_in: Optional[int]
    tokens_out: Optional[int]
    success: bool
    error: Optional[str]
```

#### **Node Instrumentation**
Each node gets a debug wrapper:
```python
class DebuggedNode(Node):
    def __init__(self, wrapped_node, debug_context):
        self.wrapped = wrapped_node
        self.debug = debug_context

    def prep(self, shared):
        self.debug.enter_phase("prep")
        result = self.wrapped.prep(shared)
        self.debug.exit_phase("prep", shared)
        return result
```

### 3. Output Formats

#### **Progress Icons** (Level 1)
- 🔍 Discovery
- 📦 Component browsing
- 🤖 Generation
- ✅ Validation success
- ❌ Validation failure
- 🔄 Retry attempt
- 📝 Parameter extraction
- 💾 Metadata generation
- ⚡ Direct execution (Path A)
- 🚀 Generation (Path B)

#### **Structured Output** (Level 2)
```
┌─────────────────────────────────────┐
│ PARAMETER MAPPING NODE              │
├─────────────────────────────────────┤
│ Input: "analyze data.csv"           │
│ Workflow needs: input_file, format  │
│                                     │
│ Extracted:                          │
│   ✓ input_file: "data.csv"         │
│   ✗ format: <missing>              │
│                                     │
│ Action: params_incomplete           │
└─────────────────────────────────────┘
```

#### **Flow Diagram** (Level 2)
```
Discovery ──❌──> Browse ──> Generate ──> Validate ──✅──> Metadata
                                            ↑_____|
                                          (retry 2x)
```

### 4. Error Reporting

#### **Structured Errors**
Instead of raw exceptions, show:
```
❌ VALIDATION FAILED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Problem: Template variable not found
Details: Node 'analyzer' references $config.api_key but 'config' is not in inputs
Location: nodes[1].params.api_key
Suggestion: Add 'config' to workflow inputs or use a different variable
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

#### **LLM Failure Reporting**
```
⚠️ LLM CALL FAILED
Node: WorkflowGeneratorNode
Model: anthropic/claude-3-sonnet
Error: Rate limit exceeded
Retry: 2/3 attempts
Next retry in: 5 seconds...
```

### 5. Performance Metrics

#### **Summary Statistics** (shown at end)
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PLANNER EXECUTION SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total time: 12.4s
Path taken: B (Generation)
LLM calls: 5
  - Discovery: 2.1s (450/120 tokens)
  - Browse: 1.8s (380/95 tokens)
  - Generate: 3.2s (1200/450 tokens)
  - Validate: 0.1s (local only)
  - Metadata: 1.5s (220/180 tokens)
Total tokens: 2350 in / 845 out
Estimated cost: $0.023
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 6. Interactive Features (Future)

#### **Breakpoint Mode** (--break-on-node)
```bash
pflow "analyze data" --debug-planner --break-on-node=generator
```
Pauses execution before specified node for inspection.

#### **Shared Store Inspector**
```
[BREAK] Paused before WorkflowGeneratorNode
Commands:
  (s)tep - Execute node and continue
  (i)nspect <key> - Show shared store value
  (d)ump - Show entire shared store
  (c)ontinue - Resume normal execution

> inspect discovered_params
{
  "input_file": "data.csv",
  "format": "json"
}
```

### 7. Implementation Strategy

#### **Phase 1: Basic Progress (Level 1)**
- Add progress messages to CLI
- Simple icons and status updates
- No structural changes to nodes

#### **Phase 2: Debug Mode (Level 2)**
- Create DebugContext class
- Wrap nodes with debug instrumentation
- Structured output formatting
- Timing and metrics collection

#### **Phase 3: Full Trace (Level 3)**
- Shared store snapshots
- Complete execution trace
- LLM request/response logging
- Performance profiling

#### **Phase 4: Interactive (Future)**
- Breakpoint support
- Step-through debugging
- Store inspection commands

### 8. CLI Integration

#### **New Flags**
```bash
# Progress indicators only
pflow "analyze data" --verbose

# Detailed debugging
pflow "analyze data" --debug-planner

# Full execution trace
pflow "analyze data" --trace-planner

# Save debug output
pflow "analyze data" --debug-planner --debug-output debug.log

# Filter debug output
pflow "analyze data" --debug-planner --debug-nodes=discovery,generator
```

#### **Environment Variables**
```bash
# Default debug level
export PFLOW_DEBUG=debug

# Always save debug logs
export PFLOW_DEBUG_DIR=/tmp/pflow-debug

# Disable LLM response truncation
export PFLOW_DEBUG_FULL_RESPONSES=1
```

### 9. Benefits for Different Users

#### **For Developers**
- Understand exact failure points
- See LLM reasoning process
- Identify performance bottlenecks
- Debug template resolution

#### **For AI Agents**
- Structured, parseable output
- Clear success/failure indicators
- Predictable format for automation
- Error messages with solutions

#### **For End Users**
- Progress indicators reduce anxiety
- Clear error messages
- Performance transparency
- Cost visibility

### 10. Example Debug Session

```bash
$ pflow "create a changelog from recent commits" --debug-planner

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔍 DISCOVERY NODE [2.1s]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Input: "create a changelog from recent commits"
Found: ✅ generate-changelog (confidence: 0.95)
Path: A (Reuse existing workflow)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📝 PARAMETER MAPPING NODE [1.8s]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Workflow needs: since_date, output_file
Extracted:
  ✗ since_date: <missing - will use default>
  ✗ output_file: <missing - will use default>
Action: params_complete

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ WORKFLOW READY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Workflow: generate-changelog
Parameters: (using defaults)
Execution time: 3.9s
Cost: $0.008

Executing workflow...
```

## Conclusion

This debugging system provides:
1. **Progressive disclosure** - Simple progress → Detailed debug → Full trace
2. **Structured output** - No more raw JSON dumps
3. **Clear flow visualization** - See exactly what path was taken
4. **Performance transparency** - Identify bottlenecks
5. **Actionable errors** - Problems with solutions

The key is showing developers what they need to know at each level without overwhelming them with unnecessary details.