# Planner Responsibility & Functionality Spec

---

## 1 · Purpose

The **planner** converts a *natural-language prompt* issued through the `pflow` CLI into a *validated, deterministic JSON IR* ready for compilation and execution.\
Its primary goal is to give users an intuitive entry point **without sacrificing** pflow's guarantees of auditability, purity, caching, and reproducibility.

The planner integrates seamlessly with the **shared store pattern**, generating flows that use natural node interfaces with optional proxy mappings for complex orchestration scenarios.

---

## 2 · Architectural Position

```plain
             ┌─────────────┐
Prompt  ───▶ │   CLI shim  │
             └────┬────────┘
                  │ NL string
                  ▼
             ┌─────────────┐
             │   PLANNER   │  (pocketflow sub-DAG)
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
```

- The planner is implemented **as a normal pocketflow flow**—not hard-coded logic.
- It generates **JSON IR** containing node graphs, action-based transitions, and shared store mappings.
- The **compiler** converts IR to CLI syntax and executable flow code using the shared store pattern.
- The **runtime** executes flows using `NodeAwareSharedStore` proxy pattern when needed.

---

## 3 · Core Responsibilities

The planner operates through a **validation-first approach**, performing linting and verification at every step to catch errors as early as possible.

| Stage | Responsibility | Outcome | 
|---|---|---|
| **3\.1 Node/Flow Discovery** | Extract metadata JSON from available Python classes. | Registry of nodes/flows with natural language descriptions. | 
| **3\.2 LLM Selection** | Use thinking model to choose nodes/flows from metadata context. | Selected building blocks (nodes and/or sub-flows). | 
| **3\.3 Flow Structure Generation** | Create node graph with action-based transitions. | Structural IR with conditional flow control. | 
| **3\.4 Structural Validation** | Lint node compatibility, action paths, reachability. | Pass → continue, Fail → retry or abort. | 
| **3\.5 Shared Store Modeling** | Create shared store schema, generate mappings if needed. | Compatible shared store interface design. | 
| **3\.6 Type/Interface Validation** | Validate shared store key compatibility between nodes. | Pass → continue, Fail → repair or retry. | 
| **3\.7 IR Finalization** | Generate validated JSON IR with default params. | Complete, validated IR ready for compilation. | 
| **3\.8 Compilation Handoff** | Pass IR to compiler for CLI syntax generation. | CLI pipe syntax for user preview. | 
| **3\.9 User Verification** | Show compiled CLI pipe for user approval. | User-approved flow ready for execution. | 
| **3\.10 Execution Handoff** | Save lockfile, hand off to shared store runtime. | Lockfile + runtime execution. | 

---

## 4 · Node/Flow Discovery & Metadata

### 4.1 Metadata Extraction

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

### 4.2 Node Metadata Schema

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

### 4.3 Flow Metadata Schema

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

### 4.4 Registry Management

- **Discovery**: Automatic scanning of Python modules for `pocketflow.Node` subclasses
- **Caching**: Metadata cached for performance, invalidated on code changes
- **Versioning**: Semver tracking for compatibility validation
- **Updates**: Registry refreshed when new nodes/flows are added

---

## 5 · LLM Selection Process

### 5.1 Thinking Model Approach

The planner uses a **thinking model** (e.g., o1-preview) to reason about node/flow selection:

1. **Context Loading**: All available metadata JSON loaded into LLM context
2. **Intent Analysis**: LLM analyzes user prompt for goals and requirements
3. **Selection Strategy**: Choose between exact flow match, sub-flow reuse, or new composition
4. **Reasoning**: LLM provides structured reasoning for choices

### 5.2 Selection Criteria

| Priority | Strategy | Example |
|---|---|---|
| **Exact Match** | Existing flow satisfies prompt completely | "summarize video" → `video-summary-pipeline` |
| **Sub-flow Reuse** | Existing flow used as component | "transcribe and translate" → `yt-transcript` + new translation |
| **New Composition** | Combine individual nodes | "analyze sentiment" → `extract-text` + `sentiment-analysis` |

### 5.3 LLM Response Format

```json
{
  "reasoning": "User wants video summary. Exact match with existing pipeline.",
  "selection_type": "exact_match",
  "chosen_flow": "video-summary-pipeline",
  "modifications": []
}
```

### 5.4 Fallback Strategies

- **Unknown Nodes**: Suggest closest semantic matches, request clarification
- **Ambiguous Intent**: Present ranked options for user selection
- **Complex Requirements**: Break down into simpler sub-problems

---

## 6 · Flow Structure Generation

### 6.1 Action-Based Transition Syntax

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

### 6.2 IR Representation

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

### 6.3 Flow Graph Validation

- **Reachability**: All nodes reachable from start
- **Completeness**: All declared actions have defined transitions
- **Cycles**: Infinite loops detected and flagged
- **Termination**: At least one path leads to terminal node

---

## 7 · Validation Framework

### 7.1 Validation-First Principle

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