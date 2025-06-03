# Planner Responsibility & Functionality Spec

---

## 1 · Purpose

The **planner** serves as the central validation and IR generation engine for pflow, handling **two distinct entry points**:

1. **Natural Language Prompts** - Converts user intent into validated flows via LLM selection
2. **CLI Pipe Syntax** - Validates and compiles manually written flows into complete IR

Its primary goal is to ensure all flows (whether AI-generated or user-written) produce *validated, deterministic JSON IR* ready for execution **without sacrificing** pflow's guarantees of auditability, purity, caching, and reproducibility.

The planner integrates seamlessly with the **shared store pattern**, generating flows that use natural node interfaces with optional proxy mappings for complex orchestration scenarios.

---

## 2 · Architectural Position

```plain
    Natural Language Path:
             ┌─────────────┐
Prompt  ───▶ │   CLI shim  │
             └────┬────────┘
                  │ NL string
                  ▼
             ┌─────────────┐
             │   PLANNER   │  (LLM Selection + Validation)
             └────┬────────┘
                  │ JSON IR
                  ▼
             ┌─────────────┐
             │  COMPILER   │  (IR → CLI syntax + code)
             └────┬────────┘
                  │ CLI syntax + Flow code
                  ▼
           User Verification
                  │
                  ▼
             ┌─────────────┐
             │   RUNTIME   │  (Shared Store execution)
             └─────────────┘

    CLI Pipe Syntax Path:
             ┌─────────────┐
CLI Pipe ──▶ │   CLI shim  │
             └────┬────────┘
                  │ Parsed syntax
                  ▼
             ┌─────────────┐
             │   PLANNER   │  (Schema + Validation only)
             └────┬────────┘
                  │ JSON IR
                  ▼
             ┌─────────────┐
             │   RUNTIME   │  (Direct execution)
             └─────────────┘
```

- The planner is implemented **as a normal pocketflow flow**—not hard-coded logic.
- It generates **JSON IR** containing node graphs, action-based transitions, and shared store mappings.
- **Two entry points**: Natural language (full LLM selection) or CLI pipe syntax (validation only).
- The **compiler** converts IR to CLI syntax (NL path) or validates existing syntax (CLI path).
- The **runtime** executes flows using `NodeAwareSharedStore` proxy pattern when needed.

---

## 3 · Core Responsibilities

The planner operates through a **validation-first approach**, performing linting and verification at every step to catch errors as early as possible.

### 3.1 Natural Language Path (Full Planner)

| Stage | Responsibility | Outcome | 
|---|---|---|
| **A. Node/Flow Discovery** | Extract metadata JSON from available Python classes. | Registry of nodes/flows with natural language descriptions. | 
| **B. LLM Selection** | Use thinking model to choose nodes/flows from metadata context. | Selected building blocks (nodes and/or sub-flows). | 
| **C. Flow Structure Generation** | Create node graph with action-based transitions. | Structural IR with conditional flow control. | 
| **D. Structural Validation** | Lint node compatibility, action paths, reachability. | Pass → continue, Fail → retry or abort. | 
| **E. Shared Store Modeling** | Create shared store schema, generate mappings if needed. | Compatible shared store interface design. | 
| **F. Type/Interface Validation** | Validate shared store key compatibility between nodes. | Pass → continue, Fail → repair or retry. | 
| **G. IR Finalization** | Generate validated JSON IR with default params. | Complete, validated IR ready for compilation. | 
| **H. Compilation Handoff** | Pass IR to compiler for CLI syntax generation. | CLI pipe syntax for user preview. | 
| **I. User Verification** | Show compiled CLI pipe for user approval. | User-approved flow ready for execution. | 
| **J. Execution Handoff** | Save lockfile, hand off to shared store runtime. | Lockfile + runtime execution. |

### 3.2 CLI Pipe Syntax Path (Validation Planner)

| Stage | Responsibility | Outcome | 
|---|---|---|
| **A. Syntax Parsing** | Parse CLI pipe syntax into basic node graph structure. | Node sequence + parameter extraction. | 
| **B. Node Validation** | Verify all referenced nodes exist in registry. | Pass → continue, Fail → abort with suggestions. | 
| **C. Structural Validation** | Lint action paths, reachability, parameter compatibility. | Pass → continue, Fail → abort with diagnostics. | 
| **D. Shared Store Modeling** | Analyze node interfaces, create shared store schema. | Compatible shared store interface design. | 
| **E. Mapping Generation** | Detect interface mismatches, generate mappings if needed. | Optional mappings for node compatibility. | 
| **F. IR Finalization** | Generate validated JSON IR with CLI-specified params. | Complete, validated IR ready for execution. | 
| **G. Execution Handoff** | Save lockfile, execute directly via shared store runtime. | Direct execution (no user verification needed). | 

---

## 4 · Dual-Mode Operation

### 4.1 Entry Point Detection

The planner automatically detects the input type and routes to the appropriate processing path:

```bash
# Natural Language → Full Planner
pflow "summarize this youtube video"

# CLI Pipe Syntax → Validation Planner  
pflow yt-transcript --url=X >> summarize-text --temperature=0.9
```

### 4.2 Shared Components

Both paths utilize the same core planner infrastructure:

| Component | Natural Language Path | CLI Pipe Path | Purpose |
|---|---|---|---|
| **Node Registry** | ✅ Used for LLM selection | ✅ Used for node validation | Metadata discovery |
| **Shared Store Modeling** | ✅ Full schema generation | ✅ Interface analysis | Compatibility detection |
| **Mapping Generation** | ✅ When LLM selects incompatible nodes | ✅ When CLI specifies incompatible nodes | Proxy pattern setup |
| **Validation Framework** | ✅ Full validation suite | ✅ Structural/interface validation | Error prevention |
| **IR Generation** | ✅ Complete JSON IR | ✅ Complete JSON IR | Execution preparation |

### 4.3 Key Differences

| Aspect | Natural Language Path | CLI Pipe Path |
|---|---|---|
| **User Input** | Free-form natural language | Structured CLI syntax |
| **LLM Usage** | Required for node selection | Not used |
| **User Verification** | Required (shows generated CLI) | Optional (direct execution) |
| **Error Recovery** | LLM retry with feedback | Abort with suggestions |
| **Compilation** | IR → CLI syntax → execution | CLI syntax → IR → execution |

### 4.4 Implementation Architecture

```python
# Simplified planner entry point
def plan_flow(user_input: str) -> JsonIR:
    if is_natural_language(user_input):
        return natural_language_planner(user_input)
    elif is_cli_pipe_syntax(user_input):
        return cli_validation_planner(user_input)
    else:
        raise InvalidInputError("Unknown input format")
```

**Critical Insight**: The CLI pipe path still requires the planner's validation and schema generation capabilities—it's not just deterministic compilation. Interface mismatches, mapping requirements, and shared store schema generation are essential regardless of entry point.

---

## 5 · Node/Flow Discovery & Metadata

### 5.1 Metadata Extraction

The planner discovers available building blocks by extracting metadata from Python class docstrings and annotations:

```python
class YTTranscript(Node):
    """Fetches YouTube transcript.
    
    Interface:
    - Reads: shared["url"] - YouTube video URL
    - Writes: shared["transcript"] - extracted transcript text
    - Params: language (default "en") - transcript language
    - Actions: "default", "video_unavailable"
    """
```

### 5.2 Node Metadata Schema

```json
{
  "id": "yt-transcript",
  "description": "Fetches YouTube transcript from video URL",
  "inputs": ["url"],
  "outputs": ["transcript"], 
  "params": {"language": "en"},
  "actions": ["default", "video_unavailable"],
  "purity": "flow_safe",
  "version": "1.0.0"
}
```

### 5.3 Flow Metadata Schema

```json
{
  "id": "video-summary-pipeline",
  "description": "Downloads video, extracts transcript, and creates summary",
  "inputs": ["url"],
  "outputs": ["summary"],
  "sub_nodes": ["yt-transcript", "summarize-text"],
  "complexity": "simple",
  "version": "1.2.0"
}
```

### 5.4 Registry Management

- **Discovery**: Automatic scanning of Python modules for `pocketflow.Node` subclasses
- **Caching**: Metadata cached for performance, invalidated on code changes
- **Versioning**: Semver tracking for compatibility validation
- **Updates**: Registry refreshed when new nodes/flows are added

---

## 6 · LLM Selection Process

### 6.1 Thinking Model Approach

The planner uses a **thinking model** (e.g., o1-preview) to reason about node/flow selection:

1. **Context Loading**: All available metadata JSON loaded into LLM context
2. **Intent Analysis**: LLM analyzes user prompt for goals and requirements
3. **Selection Strategy**: Choose between exact flow match, sub-flow reuse, or new composition
4. **Reasoning**: LLM provides structured reasoning for choices

### 6.2 Selection Criteria

| Priority | Strategy | Example |
|---|---|---|
| **Exact Match** | Existing flow satisfies prompt completely | "summarize video" → `video-summary-pipeline` |
| **Sub-flow Reuse** | Existing flow used as component | "transcribe and translate" → `yt-transcript` + new translation |
| **New Composition** | Combine individual nodes | "analyze sentiment" → `extract-text` + `sentiment-analysis` |

### 6.3 LLM Response Format

```json
{
  "reasoning": "User wants video summary. Exact match with existing pipeline.",
  "selection_type": "exact_match",
  "chosen_flow": "video-summary-pipeline",
  "modifications": []
}
```

### 6.4 Fallback Strategies

- **Unknown Nodes**: Suggest closest semantic matches, request clarification
- **Ambiguous Intent**: Present ranked options for user selection
- **Complex Requirements**: Break down into simpler sub-problems

---

## 7 · Flow Structure Generation

### 7.1 Action-Based Transition Syntax

The planner generates flows using action-based transitions for conditional flow control:

**Basic Transitions**:
```python
node_a >> node_b                    # Default action
node_a - "error" >> error_handler   # Named action
```

**Complex Flow Patterns**:
```python
# Branching
validator - "pass" >> processor
validator - "fail" >> error_handler

# Loops  
processor - "continue" >> validator
processor - "done" >> finalizer
```

### 7.2 IR Representation

```json
{
  "nodes": [
    {"id": "validator", "params": {"strict": true}},
    {"id": "processor", "params": {"batch_size": 100}},
    {"id": "error_handler", "params": {}},
    {"id": "finalizer", "params": {}}
  ],
  "edges": [
    {"from": "validator", "to": "processor", "action": "pass"},
    {"from": "validator", "to": "error_handler", "action": "fail"},
    {"from": "processor", "to": "validator", "action": "continue"},
    {"from": "processor", "to": "finalizer"}
  ]
}
```

*Note: Default actions omit the `"action"` field for cleaner IR.*

### 7.3 Flow Graph Validation

- **Reachability**: All nodes reachable from start
- **Completeness**: All declared actions have defined transitions
- **Cycles**: Infinite loops detected and flagged
- **Termination**: At least one path leads to terminal node

---

## 8 · Validation Framework

### 8.1 Validation-First Principle

**"Early and often"** - validation occurs at every planner stage to catch errors immediately:

1. **Metadata Validation** - Node/flow schemas well-formed
2. **Selection Validation** - Chosen nodes exist and are compatible
3. **Structure Validation** - Flow graph is sound and reachable
4. **Interface Validation** - Shared store keys compatible between nodes
5. **Mapping Validation** - Proxy mappings resolve correctly
6. **IR Validation** - Final JSON IR passes schema checks

### 7.2 Validation Types

| Type | Checks | Failure Action |
|---|---|---|
| **Structural** | Node existence, action definitions, graph connectivity | Retry with repair |
| **Interface** | Shared store key compatibility, type consistency | Generate mappings or retry |
| **Semantic** | Node purpose alignment, flow logic soundness | LLM re-selection |
| **Syntactic** | JSON schema compliance, IR format validity | Abort with diagnostic |

### 7.3 Error Recovery

- **Retry Budget**: Maximum 4 attempts per validation failure
- **Incremental Repair**: Fix specific issues rather than full regeneration
- **Graceful Degradation**: Fall back to simpler flows when complex ones fail
- **User Intervention**: Escalate to user when automated repair fails

---

## 8 · Shared Store Integration

### 8.1 Natural Interface Detection

The planner analyzes node metadata to understand natural shared store interfaces:

```python
# Node expects shared["text"], outputs shared["summary"]
"inputs": ["text"],
"outputs": ["summary"]
```

### 8.2 Mapping Generation Rules

**Mappings generated only when necessary** for node compatibility:

```json
{
  "mappings": {
    "summarize-text": {
      "input_mappings": {"text": "raw_transcript"},
      "output_mappings": {"summary": "article_summary"}
    }
  }
}
```

**Mapping Triggers**:
- Node A outputs `"transcript"` but Node B expects `"text"`
- Marketplace compatibility requires specific key names
- Namespace organization needed for complex flows

### 8.3 Proxy Pattern Integration

Generated flow code handles proxy setup when mappings defined:

```python
# Generated by compiler from IR
if node.id in ir.get("mappings", {}):
    mappings = ir["mappings"][node.id]
    proxy = NodeAwareSharedStore(shared, **mappings)
    node._run(proxy)
else:
    node._run(shared)  # Direct access
```

### 8.4 Shared Store Schema Design

- **Flat Structure (MVP)**: `{"url": "...", "transcript": "...", "summary": "..."}`
- **Future Nested**: `{"inputs/url": "...", "outputs/summary": "..."}`
- **Reserved Keys**: `"stdin"` for piped input
- **Type Consistency**: String/bytes/JSON validation

---

## 9 · Parameter and CLI Integration

### 9.1 Default Parameters in IR

The planner embeds **default parameters** from node metadata into IR:

```json
{
  "nodes": [
    {"id": "summarize-text", "params": {"temperature": 0.7, "max_tokens": 150}}
  ]
}
```

### 9.2 Runtime CLI Resolution

**No parameter resolution during planning** - all CLI flag handling deferred to runtime:

- CLI flags matching shared store keys → data injection
- CLI flags matching param names → param overrides  
- Single-rule resolution: "Type flags; engine decides"

### 9.3 Future: Planning-Time Customization

**Post-MVP feature**: Allow planner to customize params based on context:

```python
# Future: context-aware param adjustment
if user_intent == "creative_writing":
    params["temperature"] = 0.9
elif user_intent == "technical_summary":  
    params["temperature"] = 0.3
```

### 9.4 Separation of Concerns

| Concern | Owner | Responsibility |
|---|---|---|
| **Default params** | Planner | Embed node defaults in IR |
| **CLI flag parsing** | Runtime | Parse and categorize flags |
| **Data injection** | Runtime | Populate shared store from flags |
| **Param overrides** | Runtime | Apply flag overrides via `set_params()` |

---

## 10 · IR Schema and Compilation

### 10.1 Complete JSON IR Schema

```json
{
  "metadata": {
    "planner_version": "1.0.0",
    "created_at": "2024-01-01T12:00:00Z",
    "prompt": "summarize this youtube video",
    "llm_model": "o1-preview"
  },
  "nodes": [
    {
      "id": "yt-transcript",
      "params": {"language": "en"}
    },
    {
      "id": "summarize-text", 
      "params": {"temperature": 0.7}
    }
  ],
  "edges": [
    {"from": "yt-transcript", "to": "summarize-text"}
  ],
  "mappings": {
    "summarize-text": {
      "input_mappings": {"text": "transcript"}
    }
  },
  "shared_store_schema": {
    "inputs": ["url"],
    "outputs": ["summary"],
    "intermediate": ["transcript"]
  }
}
```

### 10.2 Compiler Integration

**Handoff Process**:
1. Planner generates validated JSON IR
2. Compiler converts IR → CLI syntax + executable Python code
3. User sees CLI preview: `yt-transcript --url=X >> summarize-text`
4. User approval triggers execution

### 10.3 Lockfile Signature System

```json
{
  "ir_hash": "sha256:abc123...",
  "node_versions": {"yt-transcript": "1.0.0", "summarize-text": "2.1.0"},
  "signature": "valid",
  "created_by": "planner-v1.0.0"
}
```

**Version Consistency**:
- IR hash changes if structure modified
- Node version mismatches trigger re-validation
- Manual Python edits break signature → re-validation required

---

## 11 · User Experience Flow

### 11.1 CLI Pipe Syntax Display

**User sees compiled output**, not raw JSON IR:

```bash
# Generated by compiler, shown to user
pflow yt-transcript --url=https://youtu.be/abc123 >> summarize-text --temperature=0.9
```

### 11.2 User Approval Process

1. **Preview**: Show CLI syntax with natural parameter names
2. **Explanation**: Brief description of what each node does
3. **Options**: Run, modify, save, or abort
4. **Modifications**: User can adjust parameters before execution

### 11.3 Error Reporting

```
❌ Flow Generation Failed
│
├─ Issue: Node 'sentiment-analysis' not found
├─ Suggestion: Did you mean 'text-sentiment'?
├─ Available: text-sentiment, emotion-detection, mood-analysis
│
└─ Retry with corrected selection? [Y/n]
```

### 11.4 Future Enhancements

- **Mermaid Diagrams**: Visual flow representation in CLI
- **Web Interface**: Drag-and-drop flow builder
- **Interactive Debugging**: Step-through validation failures
- **Parameter Wizards**: Guided param customization

---

## 12 · Integration with Runtime

### 12.1 Shared Store Runtime Handoff

**Process**:
1. Planner saves validated IR to lockfile
2. Compiler generates execution code using pocketflow patterns
3. Runtime loads lockfile, validates signature
4. Runtime executes using shared store + proxy pattern

### 12.2 pocketflow Framework Integration

**Node Execution**:
```python
# Generated runtime code
class GeneratedFlow(Flow):
    def __init__(self, ir):
        self.nodes = [self.create_node(n) for n in ir["nodes"]]
        self.setup_transitions(ir["edges"])
        
    def create_node(self, node_spec):
        node = NodeRegistry.get(node_spec["id"])
        node.set_params(node_spec["params"])
        return node
```

### 12.3 NodeAwareSharedStore Proxy Usage

**Automatic Proxy Setup**:
```python
# Generated when mappings defined in IR
for node in flow.nodes:
    if node.id in ir.get("mappings", {}):
        proxy = NodeAwareSharedStore(shared, **ir["mappings"][node.id])
        node._run(proxy)
    else:
        node._run(shared)  # Direct access
```

### 12.4 CLI Flag Resolution at Execution

**Runtime Resolution**:
- Parse CLI flags into data vs. param categories
- Inject data flags into shared store
- Apply param flags via `set_params()` overrides
- Execute flow with resolved configuration

---

## 13 · Error Handling and Codes

### 13.1 Planner Error Taxonomy

| Code | Description | Planner Output | Recovery |
|---|---|---|---|
| `METADATA_ERROR` | Node/flow metadata invalid or missing | Schema validation errors | Refresh registry |
| `SELECTION_FAILED` | LLM unable to choose appropriate nodes | Selection reasoning + suggestions | Retry with clarification |
| `STRUCTURE_INVALID` | Flow graph has logical errors | Graph analysis + specific issues | Automated repair attempt |
| `INTERFACE_MISMATCH` | Shared store keys incompatible | Key compatibility report | Generate mappings |
| `ACTION_UNDEFINED` | Node action has no defined transition | Missing action + available actions | Add transition or retry |
| `VALIDATION_TIMEOUT` | Validation exceeded retry budget | Last error + suggestion | Escalate to user |

### 13.2 Integration with Runtime Errors

**Error Code Compatibility**:
- Planner errors in `PLAN_*` namespace
- Compiler errors in `COMPILE_*` namespace  
- Runtime errors in `EXEC_*` namespace
- Consistent error format across all stages

### 13.3 User-Friendly Error Messages

```
🔍 Planning Failed: Interface Mismatch

The 'yt-transcript' node outputs 'transcript' but 'summarize-text' 
expects 'text'. 

✅ Auto-fix: Generated mapping to connect these nodes
⚡ Retry: Attempting flow generation with mapping...
```

---

## 14 · Caching and Performance

### 14.1 Flow Hash Calculation

**Components**:
- Ordered node IDs + versions
- Action-based transitions (edges)  
- Mapping definitions (when present)
- Shared store schema

```python
flow_hash = sha256(
    nodes + edges + mappings + schema
).hexdigest()[:16]
```

### 14.2 Node-Level Caching Integration

**Cache Key**: `node_hash ⊕ effective_params ⊕ input_data_sha256`

- Node execution cached when `@flow_safe`
- Param changes create new cache entries
- Mapping changes affect input data hash
- Cache hits accelerate repeated flows

### 14.3 Metadata Caching

**Performance Optimizations**:
- Node metadata cached until source files change
- LLM selection responses cached by prompt similarity
- Validation results cached by IR hash
- Registry updates invalidate dependent caches

### 14.4 LLM Response Caching

**Strategies**:
- Semantic similarity matching for prompt reuse
- Selection decision caching with confidence scores
- Invalidation on registry updates
- User-specific cache namespacing

---

## 15 · Logging and Provenance

### 15.1 Planner Log Structure

```json
{
  "session_id": "plan_2024-01-01_12:00:00_abc123",
  "prompt": "summarize this youtube video",
  "metadata": {
    "planner_version": "1.0.0",
    "llm_model": "o1-preview",
    "timestamp": "2024-01-01T12:00:00Z"
  },
  "stages": [
    {
      "stage": "node_discovery",
      "duration_ms": 50,
      "nodes_found": 42,
      "flows_found": 8
    },
    {
      "stage": "llm_selection", 
      "duration_ms": 1200,
      "reasoning": "Exact match with video-summary-pipeline",
      "selected": ["yt-transcript", "summarize-text"]
    }
  ],
  "outcome": {
    "status": "success",
    "ir_hash": "abc123...",
    "retry_count": 0
  }
}
```

### 15.2 Integration with Runtime Logging

**Linked Provenance**:
- Runtime logs reference planner session ID
- Complete audit trail from prompt to execution
- Error correlation across planner/compiler/runtime
- Performance analysis across all stages

### 15.3 Metadata Version Tracking

**Change Detection**:
- Node metadata version history
- Flow definition change tracking
- Registry update timestamps
- Dependency impact analysis

---

## 16 · Trust Model & Security

### 16.1 Flow Origin Trust Levels

| Origin | Trust Level | Cache Eligible | Validation Required |
|---|---|---|---|
| **Planner Generated** | `trusted` | Yes (if nodes `@flow_safe`) | IR validation only |
| **User Modified IR** | `mixed` | No | Full re-validation required |
| **Manual Python Code** | `untrusted` | No | Complete validation + signature check |

### 16.2 Node Registry Security

**Validation Requirements**:
- Nodes must inherit from `pocketflow.Node`
- Metadata extraction from trusted sources only
- Version pinning for production environments
- Signature verification for distributed registries

### 16.3 LLM Selection Guardrails

**Safety Measures**:
- Node selection limited to trusted registry
- No arbitrary code generation by LLM
- Structural validation catches malformed selections
- User approval required before execution

---

## 17 · Metrics and Success Criteria

### 17.1 MVP Targets

| Metric | Target | Measurement |
|---|---|---|
| **Selection Accuracy** | ≥ 95% | LLM selects appropriate nodes for intent |
| **Validation Success** | ≥ 98% | Generated IR passes all validation stages |
| **Planning Latency** | ≤ 2 seconds | End-to-end prompt → validated IR |
| **User Approval Rate** | ≥ 90% | Users approve generated CLI previews |
| **Error Recovery** | ≥ 80% | Failed validations recover within retry budget |

### 17.2 Performance Benchmarks

**Caching Effectiveness**:
- Metadata cache hit rate ≥ 95%
- LLM response cache hit rate ≥ 60% (similar prompts)
- Validation cache hit rate ≥ 85%

**Scale Targets**:
- Support ≥ 100 nodes in registry
- Handle ≥ 20 node flows efficiently
- Maintain performance with ≥ 10 concurrent planners

### 17.3 Quality Metrics

**Generated Flow Quality**:
- Zero compilation errors from valid IR
- Runtime execution success ≥ 98%
- User satisfaction with CLI syntax ≥ 85%
- Documentation/help text clarity ≥ 90%

---

## 18 · Future Extensibility

### 18.1 Advanced Selection Algorithms

**Semantic Vector Index**:
- Embedding-based node similarity matching
- Cross-domain node relationship discovery
- Intent clustering for common patterns
- Multi-modal selection (text + examples)

### 18.2 Enhanced User Interfaces

**Visual Flow Builder**:
- Web-based drag-and-drop interface
- Real-time validation feedback
- Collaborative flow editing
- Visual debugging and profiling

### 18.3 Distributed Planning

**Remote Planner Services**:
- Cloud-based planning for complex flows
- Shared registry across organizations
- Collaborative flow libraries
- Enterprise governance and compliance

### 18.4 Advanced Validation

**Constraint-Driven Generation**:
- Resource usage prediction and limits
- Security policy compliance checking
- Performance constraint satisfaction
- Cost optimization guidance

---

## 19 · Glossary

| Term | Definition |
|---|---|
| **Action-based transitions** | Conditional flow control using return values from node `post()` methods |
| **JSON IR** | Intermediate Representation in JSON format containing complete flow specification |
| **Metadata JSON** | Structured descriptions of nodes/flows extracted from Python classes |
| **Natural interface** | Intuitive shared store key names nodes use (`shared["text"]` vs complex bindings) |
| **NodeAwareSharedStore** | Proxy class enabling transparent key mapping for flow compatibility |
| **Params** | Node behavior settings accessed via `self.params.get()` (flat structure) |
| **Shared store** | Per-run key-value memory for node inputs/outputs using natural key names |
| **Thinking model** | Advanced LLM capable of complex reasoning (e.g., o1-preview) |

---

### End of Spec