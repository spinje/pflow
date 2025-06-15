# Planner Responsibility & Functionality Spec

---

## 1 · Purpose

The **planner** serves as the central validation and IR generation engine for pflow, handling **two distinct entry points**:

1. **Natural Language Prompts** - Converts user intent into validated flows via LLM selection
2. **CLI Pipe Syntax** - Validates and compiles manually written flows into complete IR

Its primary goal is to ensure all flows (whether AI-generated or user-written) produce *validated, deterministic JSON IR* ready for execution **without sacrificing** pflow's guarantees of auditability, purity, caching, and reproducibility.

The planner integrates seamlessly with the **shared store pattern**, generating flows that use simple, single-purpose nodes with natural interfaces and optional proxy mappings for complex orchestration scenarios.

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
- It generates **JSON IR** containing node graphs, simple node sequencing, and shared store mappings.
- **Two entry points**: Natural language (full LLM selection) or CLI pipe syntax (validation only).
- The **compiler** converts IR to CLI syntax (NL path) or validates existing syntax (CLI path).
- The **runtime** executes flows using `NodeAwareSharedStore` proxy pattern when needed.

---

## 3 · Core Responsibilities

The planner operates through a **validation-first approach**, performing linting and verification at every step to catch errors as early as possible.

### 3.1 Natural Language Path (Sophisticated Planner)

| Stage | Responsibility | Outcome |
|---|---|---|
| **A. Node/Flow Discovery** | Extract metadata JSON from available Python classes. | Registry of nodes/flows with natural language descriptions. |
| **B. Intent Analysis & Template Design** | **Analyze user intent and design template-driven workflow structure.** | **Template variables and workflow architecture design.** |
| **C. Template String Composition** | **Generate template strings that populate all node inputs with static text and $variable references.** | **Complete input templates with proper variable dependencies.** |
| **D. Parameter Value Creation** | **Generate appropriate parameter values based on workflow context.** | **Context-specific parameter assignments and defaults.** |
| **E. LLM Selection & Template Mapping** | Use thinking model to choose nodes and **create template variable mappings**. | Selected building blocks with **template integration**. |
| **F. Flow Structure Generation** | Create node graph with **template-driven sequencing**. | Structural IR with **template variables and data flow**. |
| **G. Structural Validation** | Lint node compatibility, action paths, reachability, **template resolution**. | Pass → continue, Fail → retry or abort. |
| **H. Shared Store Modeling** | Create shared store schema, generate mappings, **template variable tracking**. | Compatible shared store interface with **template support**. |
| **I. Type/Interface Validation** | Validate shared store key compatibility and **template variable resolution**. | Pass → continue, Fail → repair or retry. |
| **J. IR Finalization** | Generate validated JSON IR with **template variables and generated parameters**. | Complete, validated IR with **template-driven execution plan**. |
| **K. Compilation Handoff** | Pass IR to compiler for **template-aware** CLI syntax generation. | CLI pipe syntax with **template variables** for user preview. |
| **L. User Verification** | Show compiled CLI pipe with **template variables** for user approval. | User-approved **template-driven** flow ready for execution. |
| **M. Execution Handoff** | Save lockfile, hand off to **template-aware** shared store runtime. | Lockfile + **template-driven** runtime execution. |

### 3.2 CLI Pipe Syntax Path (Enhanced Validation Planner)

| Stage | Responsibility | Outcome |
|---|---|---|
| **A. Syntax Parsing** | Parse CLI pipe syntax and **detect template variables**. | Node sequence + parameter extraction + **template analysis**. |
| **B. Template Variable Analysis** | **Identify and validate template variable patterns and dependencies.** | **Template variable dependency graph and resolution order.** |
| **C. Node Validation** | Verify all referenced nodes exist in registry. | Pass → continue, Fail → abort with suggestions. |
| **D. Template String Resolution** | **Resolve template strings for all node inputs, ensuring $variables map to available shared store values.** | **Fully populated node input templates with validated dependencies.** |
| **E. Structural Validation** | Lint action paths, reachability, parameter compatibility, **template resolution order**. | Pass → continue, Fail → abort with diagnostics. |
| **F. Shared Store Modeling** | Analyze node interfaces, create shared store schema, **template variable tracking**. | Compatible shared store interface with **template support**. |
| **G. Mapping Generation** | Detect interface mismatches, generate mappings, **template variable mappings**. | Optional mappings for node compatibility + **template resolution**. |
| **H. IR Finalization** | Generate validated JSON IR with CLI-specified params + **template metadata**. | Complete, validated IR with **template-driven execution plan**. |
| **I. Execution Handoff** | Save lockfile, execute directly via **template-aware** shared store runtime. | Direct execution with **template resolution** (no user verification needed). |

### 3.2.1 Type Shadow Store Prevalidation (CLI Path Enhancement)

During CLI pipe composition, the planner maintains an ephemeral **type shadow store** for real-time compatibility checking:

**Purpose:**
- Provide immediate type compatibility feedback during interactive composition
- Reduce planner retry cycles by catching obvious type mismatches early
- Enable intelligent autocomplete suggestions for valid next nodes

**Mechanism:**
1. **Type Accumulation**: As nodes are added to pipe syntax, their output types are accumulated in memory. If `stdin` is piped, `shared["stdin"]` (e.g., as type `str` or `bytes`) is considered available from the start.
2. **Compatibility Check**: Each candidate next node's input type requirements are validated against available types
3. **Advisory Feedback**: Invalid compositions flagged immediately, valid options highlighted

**Example Flow:**
```bash
yt-transcript          # Produces: transcript:str
>> summarize           # Requires: text:str → ✓ Compatible (str available)
>> plot-chart          # Requires: data:dataframe → ✗ Incompatible (no dataframe)
```

**Integration Points:**
- Uses existing node metadata type declarations (no schema changes)
- Operates before full IR compilation (lightweight validation)
- Discarded after pipe→IR compilation (ephemeral advisory tool)
- Complementary to full validation pipeline (not replacement)

**Limitations:**
- Type-only validation (no key name compatibility)
- No proxy mapping awareness
- No conditional flow logic
- Defers to full IR validation for definitive compatibility

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
| **Shared Store Modeling** | ✅ Full schema generation. If `stdin` was piped, `shared["stdin"]` is considered populated. The planner ensures the first relevant node consumes this, either by node design or by generating an IR mapping (e.g. `{"input_mappings": {"<node_input_key>": "stdin"}}`). | ✅ Interface analysis. If `stdin` was piped, `shared["stdin"]` is considered populated. The planner ensures the first relevant node consumes this, either by node design or by generating an IR mapping. | Compatibility detection |
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
class YTTranscriptNode(Node):
    """Fetches YouTube transcript.

    Interface:
    - Reads: shared["url"] - YouTube video URL
    - Writes: shared["transcript"] - extracted transcript text
    - Params: language (default "en") - transcript language
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
  "sub_nodes": ["yt-transcript", "llm"],
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

## 6 · Template String Composition & Variable Flow Management

### 6.1 Template String Composition & Shared Store Input Population

The planner leverages LLM capabilities for **template string composition, shared store input population, and variable dependency management**:

**Core Planning Process:**
1. **Node Input Analysis**: Examine each node's metadata to identify all required shared store inputs
2. **Template String Generation**: Create strings that populate node inputs, incorporating both static text and dynamic $variables
3. **Variable Dependency Tracking**: Map $variable references to their source nodes' outputs in the shared store
4. **Parameter Value Assignment**: Generate context-appropriate parameter values for node behavior
5. **Flow Validation**: Ensure all template variables can be resolved through the workflow execution order

**Template String Composition Examples:**
```bash
# For claude-code node expecting shared["prompt"]:
"<instructions>
1. Understand the problem described in the issue
2. Search the codebase for relevant files
3. Implement the necessary changes to fix the issue
4. Write and run tests to verify the fix
5. Return a report of what you have done as output
</instructions>
This is the issue: $issue"

# For llm node expecting shared["prompt"]:
"Write a descriptive commit message for these changes: $code_report"

# For git-commit node expecting shared["message"]:
"$commit_message"
```

**Variable Flow Management:**
- **Dependency Resolution**: `$issue` → `shared["issue"]` from github-get-issue output
- **Multi-Consumer Variables**: `$code_report` used by both llm and github-create-pr nodes
- **Runtime Substitution**: Template strings resolved to actual values during execution
- **Validation**: Ensure all $variables have corresponding sources in the workflow

**Discovery Enhancement:**
- LLM receives flow descriptions as context during node/flow selection
- Semantic matching supplements structural flow analysis
- Proven execution history combined with purpose alignment
- Reduces planning overhead through intelligent flow library utilization

This approach anchors stability by reusing proven flows rather than regenerating them.

### 6.2 Thinking Model Approach

When generation is required, the planner uses a **thinking model** (e.g., o1-preview):

1. **Context Loading**: All available metadata JSON loaded into LLM context
2. **Intent Analysis**: LLM analyzes user prompt for goals and requirements
3. **Selection Strategy**: Choose between exact flow match, sub-flow reuse, or new composition
4. **Reasoning**: LLM provides structured reasoning for choices

### 6.3 Selection Criteria

| Priority | Strategy | Example |
|---|---|---|
| **Exact Match** | Existing flow satisfies prompt completely | "summarize video" → `video-summary-pipeline` |
| **Sub-flow Reuse** | Existing flow used as component | "transcribe and translate" → `yt-transcript` + `llm --prompt="translate"` |
| **New Composition** | Combine individual simple nodes | "analyze sentiment" → `read-file` + `llm --prompt="analyze sentiment"` |
| **LLM Node Preference** | Use general LLM node for text tasks | "explain this code" → `read-file` + `llm --prompt="explain this code"` |

### 6.4 Template String Composition Response Format

```json
{
  "reasoning": "User wants GitHub issue resolution. Generating template strings to populate all node inputs with proper variable dependencies.",
  "workflow_type": "template_string_composition",
  "node_input_templates": {
    "claude-code": {
      "prompt": "<instructions>\n1. Understand the problem described in the issue\n2. Search the codebase for relevant files\n3. Implement the necessary changes to fix the issue\n4. Write and run tests to verify the fix\n5. Return a report of what you have done as output\n</instructions>\nThis is the issue: $issue",
      "dependencies": ["issue"]
    },
    "llm": {
      "prompt": "Write a descriptive commit message for these changes: $code_report",
      "dependencies": ["code_report"]
    },
    "git-commit": {
      "message": "$commit_message",
      "dependencies": ["commit_message"]
    },
    "github-create-pr": {
      "title": "Fix: $issue_title",
      "body": "$code_report",
      "dependencies": ["issue_title", "code_report"]
    }
  },
  "variable_flow": {
    "issue": "github-get-issue.outputs.issue_data",
    "issue_title": "github-get-issue.outputs.title",
    "code_report": "claude-code.outputs.code_report",
    "commit_message": "llm.outputs.response"
  },
  "selected_nodes": ["github-get-issue", "claude-code", "llm", "git-commit", "git-push", "github-create-pr"],
  "parameter_values": {
    "claude-code": {"temperature": 0.2, "max_tokens": 8192},
    "llm": {"temperature": 0.1, "model": "gpt-4"}
  }
}
```

### 6.5 Fallback Strategies

- **Unknown Nodes**: Suggest closest semantic matches, request clarification
- **Ambiguous Intent**: Present ranked options for user selection
- **Complex Requirements**: Break down into simpler sub-problems using LLM node
- **Text Processing Tasks**: Default to LLM node with appropriate prompts

---

## 7 · Flow Structure Generation

### 7.1 Simple Node Sequencing

The planner generates flows using simple node-to-node sequencing for clear data flow:

**Basic Sequencing**:

```python
node_a >> node_b >> node_c          # Sequential data flow
```

**Simple Flow Patterns**:

```python
# Text processing pipeline
read_file >> llm >> write_file      # Read → Process → Write

# API data flow
github_get_issue >> llm >> github_add_comment  # Get → Analyze → Respond

# Multi-step analysis
yt_transcript >> llm >> llm >> write_file      # Get → Summarize → Expand → Save
```

### 7.2 IR Representation

```json
{
  "nodes": [
    {"id": "read-file", "version": "1.0.0", "params": {"path": "data.txt"}},
    {"id": "llm", "version": "1.0.0", "params": {"model": "gpt-4", "temperature": 0.7}},
    {"id": "write-file", "version": "1.0.0", "params": {"path": "summary.md"}}
  ],
  "edges": [
    {"from": "read-file", "to": "llm"},
    {"from": "llm", "to": "write-file"}
  ]
}
```

*Note: Simple sequential flows use direct node-to-node connections without complex action logic.*

### 7.3 Flow Graph Validation

- **Reachability**: All nodes reachable from start
- **Sequencing**: Clear data flow from input to output
- **Interface Compatibility**: Node inputs match previous node outputs
- **Termination**: Flow has clear start and end points

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
| **Structural** | Node existence, graph connectivity | Retry with repair |
| **Interface** | Shared store key compatibility, type consistency | Generate mappings or retry |
| **Semantic** | Node purpose alignment, flow logic soundness | LLM re-selection |
| **Syntactic** | JSON schema compliance, IR format validity | Abort with diagnostic |

### 7.3 Error Recovery

- **Retry Budget**: Maximum 4 attempts per validation failure
- **Purity Constraints**: Retries only allowed on `@flow_safe` nodes; abort otherwise
- **Incremental Repair**: Fix specific issues rather than full regeneration
- **Graceful Degradation**: Fall back to simpler flows, prefer LLM node for text tasks
- **User Intervention**: Escalate to user when automated repair fails

### 7.4 Failure Artifacts

When planner exhausts retries, it produces comprehensive failure documentation:

- **`.failed.lock.json`**: Partial IR with failure context for debugging
- **`planner_log.json`**: Complete retry history and error details
- **Error Recovery**: User can inspect failures and retry manually with modifications

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
    "llm": {
      "input_mappings": {"prompt": "formatted_prompt"},
      "output_mappings": {"response": "article_summary"}
    }
  }
}
```

**Mapping Triggers**:

- Node A outputs `"transcript"` but LLM node expects `"prompt"`
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
- **Reserved Keys**: `"stdin"` for piped input from the shell. This key will be populated by the runtime if data is piped to `pflow`.
- **Type Consistency**: String/bytes/JSON validation

---

## 9 · Parameter and CLI Integration

### 9.1 Default Parameters in IR

The planner embeds **default parameters** from node metadata into IR:

```json
{
  "nodes": [
    {"id": "llm", "version": "1.0.0", "params": {"model": "gpt-4", "temperature": 0.7}}
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

### 9.4 Interactive vs Batch Mode

**Missing Required Data Resolution**:

| Mode | Missing shared store key | Action |
|---|---|---|
| **Interactive** | Prompt user for input value | Inject into shared store |
| **Batch/CI** | Abort with `MISSING_INPUT` error | Fail fast with clear diagnostic |

**Ambiguity Handling**:

- Multiple candidate flows → Choose most recently validated
- Still ambiguous → Interactive: ask user; Batch: abort with options

### 9.5 Separation of Concerns

| Concern | Owner | Responsibility |
|---|---|---|
| **Default params** | Planner | Embed node defaults in IR |
| **CLI flag parsing** | Runtime | Parse and categorize flags |
| **Data injection** | Runtime | Populate shared store from flags |
| **Param overrides** | Runtime | Apply flag overrides via `set_params()` |

---

## 10 · IR Schema and Compilation

### 10.1 Template-Driven JSON IR Schema

```json
{
  "metadata": {
    "planner_version": "1.0.0",
    "created_at": "2024-01-01T12:00:00Z",
    "prompt": "fix github issue 1234",
    "llm_model": "o1-preview"
  },
  "nodes": [
    {
      "id": "github-get-issue",
      "version": "1.0.0",
      "params": {"issue": 1234},
      "input_templates": {},
      "outputs": ["issue", "issue_title", "issue_body"]
    },
    {
      "id": "claude-code",
      "version": "1.0.0",
      "params": {"temperature": 0.2, "max_tokens": 8192},
      "input_templates": {
        "prompt": "<instructions>\n1. Understand the problem described in the issue\n2. Search the codebase for relevant files\n3. Implement the necessary changes to fix the issue\n4. Write and run tests to verify the fix\n5. Return a report of what you have done as output\n</instructions>\nThis is the issue: $issue"
      },
      "template_dependencies": ["issue"],
      "outputs": ["code_report"]
    },
    {
      "id": "llm",
      "version": "1.0.0",
      "params": {"model": "gpt-4", "temperature": 0.1},
      "input_templates": {
        "prompt": "Write a descriptive commit message for these changes: $code_report"
      },
      "template_dependencies": ["code_report"],
      "outputs": ["commit_message"]
    },
    {
      "id": "git-commit",
      "version": "1.0.0",
      "input_templates": {
        "message": "$commit_message"
      },
      "template_dependencies": ["commit_message"]
    },
    {
      "id": "github-create-pr",
      "version": "1.0.0",
      "input_templates": {
        "title": "Fix: $issue_title",
        "body": "$code_report"
      },
      "template_dependencies": ["issue_title", "code_report"]
    }
  ],
  "edges": [
    {"from": "github-get-issue", "to": "claude-code"},
    {"from": "claude-code", "to": "llm"},
    {"from": "llm", "to": "git-commit"},
    {"from": "git-commit", "to": "git-push"},
    {"from": "git-push", "to": "github-create-pr"}
  ],
  "variable_resolution": {
    "issue": "github-get-issue.outputs.issue",
    "issue_title": "github-get-issue.outputs.issue_title",
    "code_report": "claude-code.outputs.code_report",
    "commit_message": "llm.outputs.commit_message"
  }
}
```

### 10.2 Compiler Integration

**Handoff Process**:

1. Planner generates validated JSON IR
2. Compiler converts IR → CLI syntax + executable Python code
3. User sees CLI preview: `yt-transcript --url=X >> llm --prompt="Summarize this transcript"`
4. User approval triggers execution

### 10.3 Lockfile Signature System

```json
{
  "ir_hash": "sha256:abc123...",
  "node_versions": {"yt-transcript": "1.0.0", "llm": "1.0.0"},
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
pflow yt-transcript --url=https://youtu.be/abc123 >> llm --prompt="Summarize this transcript" --temperature=0.9
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
├─ Suggestion: Use 'llm' node with prompt "analyze sentiment of this text"
├─ Available: llm, text-sentiment, emotion-detection
│
└─ Retry with LLM node? [Y/n]
```

### 11.4 Future Enhancements

- **Mermaid Diagrams**: Visual flow representation in CLI
- **Web Interface**: Drag-and-drop flow builder
- **Interactive Debugging**: Step-through validation failures
- **Parameter Wizards**: Guided param customization

### 11.5 Progressive Learning Through Transparency

The planner's transparent generation process serves as an **educational scaffold** for user empowerment:

**Learning Stages:**
1. **Intent Declaration**: User expresses goals in natural language
2. **Structure Revelation**: System shows how intent translates to concrete steps
3. **Interactive Refinement**: User can inspect, modify, and learn from generated flows
4. **Progressive Authorship**: Users evolve from consumers to co-authors over time

**Educational Mechanisms:**
- **Visible Planning**: CLI pipe syntax shown before execution reveals planning logic
- **Modification Capability**: Users can edit generated flows to understand cause-effect
- **Incremental Complexity**: Simple flows build understanding for complex compositions
- **Pattern Recognition**: Repeated exposure builds intuition for flow design

**Transparency Benefits:**
```bash
# User Input (Intent)
pflow "summarize this youtube video"

# Generated Output (Structure Revealed)
yt-transcript --url $VIDEO >> llm --prompt="Summarize this transcript" --temperature=0.7

# User Learning Opportunity
# ✓ Sees video → transcript → summary decomposition
# ✓ Understands LLM node with clear prompt
# ✓ Can modify prompt and parameters before execution
# ✓ Builds intuition for similar text processing tasks
```

**Long-term Empowerment:**
- Users gradually transition from intent declarers to flow architects
- Natural language becomes entry point, not permanent dependency
- System knowledge transfers to users through visible structure

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
        execution_config = node_spec.get("execution", {})
        node = NodeRegistry.get(node_spec["id"], **execution_config)
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

- **Caching Eligibility**: Node must be `@flow_safe` AND trust level ≠ `mixed`
- **Safety Constraint**: Impure nodes never cached, regardless of other factors
- **Param Changes**: Create new cache entries without affecting graph hash
- **Mapping Changes**: Affect input data hash, ensuring cache correctness
- **Trust Integration**: Cache only consulted for trusted flow origins

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
  "planner_run_id": "run_abc123def456",
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

| Origin | Trust Level | Cache Eligible | Validation Required | Notes |
|---|---|---|---|---|
| **Planner (reused flow)** | `trusted` | Yes | Already validated | Proven flow, structurally identical |
| **Planner (new flow)** | `trusted` | Yes, after first run | IR validation only | Planner provenance recorded |
| **User Modified IR** | `mixed` | No | Full re-validation required | Requires manual `--force-cache` |
| **Manual Python Code** | `untrusted` | No | Complete validation + signature check | Treated as untrusted until validated |

### 16.2 Cache Safety Rules

**Caching Prerequisites** (ALL must be true):

1. Node marked `@flow_safe` (pure, no side effects)
2. Flow origin trust level ≠ `mixed`
3. All input data hashes match cache entry
4. Node version and params match cache entry

### 16.3 Node Registry Security

**Validation Requirements**:

- Nodes must inherit from `pocketflow.Node`
- Metadata extraction from trusted sources only
- Version pinning for production environments
- Signature verification for distributed registries

### 16.4 LLM Selection Guardrails

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
| **JSON IR** | Intermediate Representation in JSON format containing complete flow specification |
| **LLM Node** | General-purpose text processing node that prevents proliferation of specific prompt nodes |
| **Metadata JSON** | Structured descriptions of nodes/flows extracted from Python classes |
| **Natural interface** | Intuitive shared store key names nodes use (`shared["prompt"]` vs complex bindings) |
| **NodeAwareSharedStore** | Proxy class enabling transparent key mapping for flow compatibility |
| **Params** | Node behavior settings accessed via `self.params.get()` (flat structure) |
| **Shared store** | Per-run key-value memory for node inputs/outputs using natural key names |
| **Simple nodes** | Single-purpose nodes with clear interfaces and natural composition |
| **Thinking model** | Advanced LLM capable of complex reasoning (e.g., o1-preview) |

---

### End of Spec
