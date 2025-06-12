## Shared-Store & Proxy Model — CLI Runtime Specification

### 1 · Purpose

Define how **CLI arguments**, **IR mappings**, and the **flow-scoped shared store** interact, enabling a one-flag user model while preserving an immutable, hash-stable data-flow graph through standalone, simple nodes.

This specification details the implementation using the **pocketflow framework** and shows how generated flow code integrates with static node classes using an optional proxy layer for complex routing scenarios.

> **For conceptual understanding and architectural rationale**, see [Shared Store + Proxy Design Pattern](./shared-store-node-proxy-architecture.md)

---

### 2 · pocketflow Framework Integration

Our pattern leverages the lightweight **pocketflow framework** (100 lines of Python):

- **Static node classes**: Inherit from `pocketflow.Node` with `prep()`/`exec()`/`post()` methods
- **Params system**: Use `set_params()` to configure node behavior with flat params structure
- **Flow orchestration**: Use `>>` operator and `Flow` class for wiring
- **No modifications**: Pure pattern implementation using existing framework APIs

> **See also**: [pocketflow framework](../pocketflow/__init__.py) and [communication patterns](../pocketflow/docs/core_abstraction/communication.md)

**Framework vs Pattern**:

- **pocketflow**: The underlying 100-line framework
- **pflow pattern**: Our specific use of natural node interfaces with optional proxy mapping

---

### 3 · Proxy-Based Mapping Architecture

The **NodeAwareSharedStore** proxy enables simple node code while supporting complex flow routing:

- **Direct Access**: When no mappings defined, nodes access shared store directly (zero overhead)
- **Proxy Mapping**: When IR defines mappings, proxy transparently handles key translation
- **Performance**: Zero overhead for simple flows, mapping only when needed
- **Integration**: Helper class used by generated flow code, not a framework modification

---

### 4 · Concepts & Terminology

| Element | Role | Stored in lock-file | Part of DAG hash | Can change per run | Notes |
|---|---|---|---|---|---|
| `params` | Literal per-node tunables | Defaults stored; run-time overlays in derived snapshot | ❌ | ✅ via CLI | Flat structure in `self.params` |
| `mappings` | Key translation for complex flows | ✅ | ✅ (when defined) | ❌ | Optional, flow-level concern |
| Shared store | Flow-scoped key → value memory | Values never stored | Key names yes | Populated by CLI or pipe | Reserved key `stdin` (populated by shell pipe input) |

#### 4\.1 Quick-reference summary

| Field | Function | Affects DAG? | Overridable? | Stored? | Shared? |
|---|---|---|---|---|---|
| Node interface | Natural key access | ✅ | ❌ | ✅ | ✅ |
| `params` | Behaviour knobs | ❌ | ✅ (`--flag`) | ✅ | ❌ |
| `mappings` | Complex routing | ✅ | ❌ | ✅ | ✅ |

#### 4.2 Shared Store Lifecycle and Scope

**Transient Per-Run Nature:**
- Shared store exists only for single flow execution
- No persistence between flow runs
- Not a database, cache, or external storage layer
- All data cleared at flow completion

**Prohibited Uses:**
- Storing configuration that should persist between runs
- Using as application state database
- Expecting data to survive flow restarts
- Cross-flow data sharing

**Correct Patterns:**
- Use external storage nodes for persistence
- Pass persistent data via CLI flags or input files
- Use `params` for configuration that doesn't change per run

#### 4.3 Future Namespacing Support

**MVP Implementation**: Flat key structure for shared store simplicity

```python
shared = {
    "url": "https://youtu.be/abc123",
    "transcript": "Video content..."
}
```

**Future Feature**: Nested path-like keys for complex flows

```python
shared = {
    "inputs/video_url": "https://youtu.be/abc123",
    "outputs/transcript": "Video content..."
}
```

The proxy pattern will support nested key translation when this feature is implemented.

---

### 5 · Node Interface Integration

The simple node interface integrates with static node classes using pocketflow's `params` system:

```python
# Node class (static, pre-written) - SIMPLE AND STANDALONE
class YTTranscript(Node):  # Inherits from pocketflow.Node
    """Fetches YouTube transcript.

    Interface:
    - Reads: shared["url"] - YouTube video URL
    - Writes: shared["transcript"] - extracted transcript text
    - Params: language (default "en") - transcript language
    """
    def prep(self, shared):
        return shared["url"]  # Natural interface

    def exec(self, prep_res):  # prep_res contains the URL
        language = self.params.get("language", "en")  # Simple params
        return fetch_transcript(prep_res, language)

    def post(self, shared, prep_res, exec_res):
        shared["transcript"] = exec_res  # Direct write

# Generated flow code handles proxy when needed
def run_node_with_mapping(node, shared, mappings=None):
    if mappings:
        proxy = NodeAwareSharedStore(
            shared,
            input_mappings={"url": "video_source"},
            output_mappings={"transcript": "raw_transcript"}
        )
        node._run(proxy)
    else:
        node._run(shared)  # Direct access
```

#### 5\.1 CLI to Shared Store Flow

```
CLI Flag: --url=https://youtu.be/abc123
Result: shared["url"] = "https://youtu.be/abc123"
Node Access: shared["url"] (direct access)
```

or with mapping:

```
CLI Flag: --url=https://youtu.be/abc123
Flow Schema: shared["video_source"] = "https://youtu.be/abc123"
Proxy Mapping: "url" → "video_source"
Node Access: shared["url"] (proxy maps to "video_source")
```

The node uses natural interface names while the proxy handles any necessary translation.

---

### 6 · Canonical IR fragment

```json
{
  "nodes": [
    {
      "id": "yt-transcript",
      "version": "1.0.0",
      "params": { "language": "en" },
      "execution": { "max_retries": 3, "wait": 1.0 }
    },
    {
      "id": "summarise-text",
      "version": "2.1.0",
      "params": { "temperature": 0.7 }
    }
  ],
  "edges": [
    {"from": "yt-transcript", "to": "summarise-text"}
  ],
  "mappings": {
    "yt-transcript": {
      "input_mappings": {"url": "video_source"},
      "output_mappings": {"transcript": "raw_transcript"}
    },
    "summarise-text": {
      "input_mappings": {"text": "raw_transcript"},
      "output_mappings": {"summary": "article_summary"}
    }
  }
}
```

Graph: `yt-transcript` ➜ `summarise-text` (wired through transparent proxy mapping).

---

### 7 · Execution pipeline & CLI resolution

> **Single user rule** — *Type flags; engine decides.*\
> Flags that match any node's natural interface are **data injections**; all others are **params overrides**.

#### Updated resolution algorithm (emphasizing simplicity)

0. **Detect Piped Input**: If input is being piped to `pflow` via `stdin`, its content is read and placed into `shared["stdin"]`.
1. Parse CLI as flat `key=value`

2. For CLI flags matching natural shared store keys: inject directly

3. For CLI flags marked as params: update node params (flat structure)

4. For CLI flags marked as execution config: update node execution settings

5. Generate flow code that:
   - Creates proxy if IR defines mappings for node
   - Uses direct access if no mappings defined

6. Execute flow with appropriate access pattern per node

---

### 8 · CLI scenarios

| Scenario | Command | Shared-store after injection | Proxy needed? |
|---|---|---|---|
| Provide video URL | `pflow yt-transcript --url=`[`https://youtu.be/abc`](https://youtu.be/abc) | `{ "url": "`[`https://youtu.be/abc`](https://youtu.be/abc)`" }` | No |
| Override temperature | `pflow summarise-text --temperature=0.9` | – | No |
| Pipe text | `cat notes.txt | pflow summarise-text` | `{ "stdin": "<bytes>" }` | Maybe |
| Complex routing | Flow with marketplace compatibility | `{ "video_source": "...", "raw_transcript": "...", "article_summary": "..." }` | Yes |

---

### 9 · Integration Example: End-to-End Flow

#### 9.1 Simple Scenario (No Mappings)

**IR Definition**:

```json
{
  "nodes": [
    {
      "id": "yt-transcript",
      "version": "1.0.0",
      "params": {"language": "en"}
    },
    {
      "id": "summarise-text",
      "version": "2.1.0",
      "params": {"temperature": 0.7}
    }
  ],
  "edges": [{"from": "yt-transcript", "to": "summarise-text"}]
}
```

**CLI Command**:

```bash
pflow yt-transcript --url=https://youtu.be/abc123 >> summarise-text --temperature=0.9
```

**Shared Store Population**:

```python
shared = {
  "url": "https://youtu.be/abc123"  # Direct injection
}
```

**Generated Flow Code**:

```python
# Simple scenario - direct access
def create_flow():
    fetch_node = YTTranscript()
    summarize_node = SummarizeText()

    # Configure nodes with IR params
    fetch_node.set_params({"language": "en"})
    summarize_node.set_params({"temperature": 0.9})  # CLI override

    # Wire the flow using pocketflow operators
    fetch_node >> summarize_node
    return Flow(start=fetch_node)

# Direct execution
def run_with_cli():
    shared = {"url": "https://youtu.be/abc123"}  # CLI injection
    flow = create_flow()
    flow.run(shared)  # Nodes access shared store directly
```

#### 9.2 Complex Scenario (With Mappings)

**IR Definition**:

```json
{
  "nodes": [
    {
      "id": "yt-transcript",
      "version": "1.0.0",
      "params": {"language": "en"}
    },
    {
      "id": "summarise-text",
      "version": "2.1.0",
      "params": {"temperature": 0.7"}
    }
  ],
  "edges": [{"from": "yt-transcript", "to": "summarise-text"}],
  "mappings": {
    "yt-transcript": {
      "input_mappings": {"url": "video_source"},
      "output_mappings": {"transcript": "raw_transcript"}
    },
    "summarise-text": {
      "input_mappings": {"text": "raw_transcript"},
      "output_mappings": {"summary": "article_summary"}
    }
  }
}
```

**Shared Store Population**:

```python
shared = {
  "video_source": "https://youtu.be/abc123"  # Flow schema
}
```

**Generated Flow Code**:

```python
# Complex scenario - with proxy mapping
def create_flow():
    fetch_node = YTTranscript()
    summarize_node = SummarizeText()

    # Configure nodes
    fetch_node.set_params({"language": "en"})
    summarize_node.set_params({"temperature": 0.9})

    # Wire the flow
    fetch_node >> summarize_node
    return Flow(start=fetch_node)

def run_with_cli():
    shared = {"video_source": "https://youtu.be/abc123"}
    flow = create_flow()

    # Handle proxy mapping
    for node in flow.nodes:
        if node.id in ir.get("mappings", {}):
            mappings = ir["mappings"][node.id]
            proxy = NodeAwareSharedStore(
                shared,
                input_mappings={"url": "video_source"},
                output_mappings={"transcript": "raw_transcript"}
            )
            node._run(proxy)
        else:
            node._run(shared)
```

#### 9.3 Node Execution with Natural Interfaces

**Fetch Node**:

```python
# Node always uses natural interface
# prep() reads from shared["url"] (proxy maps to "video_source" if needed)
# exec() processes URL using self.params.get("language")
# post() writes to shared["transcript"] (proxy maps to "raw_transcript" if needed)
```

**Summarise Node**:

```python
# Node always uses natural interface
# prep() reads from shared["text"] (proxy maps to "raw_transcript" if needed)
# exec() uses self.params.get("temperature") = 0.9 (CLI override)
# post() writes to shared["summary"] (proxy maps to "article_summary" if needed)
```

#### 9.4 Final State

**Simple Scenario**:

```python
shared = {
  "url": "https://youtu.be/abc123",
  "transcript": "Video transcript content...",
  "summary": "Generated summary..."
}
```

**Complex Scenario**:

```python
shared = {
  "video_source": "https://youtu.be/abc123",
  "raw_transcript": "Video transcript content...",
  "article_summary": "Generated summary..."
}
```

Same node code, different shared store layouts.

---

### 10 · Flow identity, caching & purity

- **Flow-hash** = ordered nodes + mappings (when defined) + node ids/versions.

- **Node cache key** (`@flow_safe`) = node-hash ⊕ effective params ⊕ SHA-256(input data).

- `params` changes never alter graph hash; they just create a new node-level cache entry.

- If a `params` value changes side-effect surface, the node must declare itself **impure**.

---

### 11 · Validation rules

| \# | Rule | Failure action |
|---|---|---|
| 1 | IR immutability — CLI cannot alter mappings or node set | Abort |
| 2 | Unknown CLI flag | Abort |
| 3 | Missing required data in shared store | Abort |
| 4 | `params` always overrideable via `set_params()` | Derived snapshot |
| 5 | `stdin` key reserved; node must handle it naturally. (Note: "naturally" implies either the node is designed to directly consume `shared["stdin"]` if its primary input key is not otherwise populated, or it consumes it via an IR mapping from its input key to `shared["stdin"]` orchestrated by the planner or CLI parser.) | Abort |
| 6 | Mapping targets unique flow-wide | Abort |
| 7 | Natural interface names should be intuitive | Warning |
| 8 | Node classes must inherit from `pocketflow.Node` | Abort |

---

### 12 · Best practices & rationale

- Use intuitive CLI names (`url`, `text`) that match node natural interfaces.

- Use proxy mappings only when marketplace compatibility requires different schemas.

- All node interfaces treated as required unless node provides defaults.

- **One-rule CLI** keeps user mental model shallow while IR guarantees auditability.

- Immutable graph + mutable data enables planner reuse and deterministic replay.

- **Natural interfaces enable simplicity** — node writers focus on business logic.

- **Proxy enables compatibility** — same nodes work with different flow schemas.

- **Static nodes, dynamic flows** — node logic is reusable, flow wiring is generated.

### 12.2 CLI Usability Enhancement

**Interactive Autocomplete**: Autocompletion correctly distinguishes between shared store keys (for data injection) and node parameters (for behavior configuration), reinforcing the "Type flags; engine decides" resolution model. This contextual awareness helps users learn the distinction while reducing CLI composition errors.

### 12.1 Educational Design Rationale

The CLI design prioritizes **learning through transparency** over automation efficiency:

**Educational CLI Principles:**
- **Show Don't Hide**: Generated flows visible as CLI pipe syntax before execution
- **Edit Before Execute**: Users can modify generated flows to explore alternatives
- **Natural Progression**: Simple patterns scale to complex orchestration
- **Transferable Knowledge**: CLI skills translate to direct flow authoring

**Learning Facilitation:**
```bash
# Educational Flow: User sees and can modify each step
pflow "process this data"
# → Generated: load-csv --file data.csv >> clean-data >> analyze >> save-results
# → User can edit: load-csv --file data.csv >> clean-data --strict >> analyze --method=detailed >> save-results --format=json

# Knowledge Transfer: User eventually authors directly
pflow load-csv --file new_data.csv >> custom-analysis >> export-dashboard
```

**Progressive Complexity:**
- Start with natural language for immediate results
- Graduate to CLI pipe editing for customization
- Advance to direct flow authoring for full control
- Develop nodes for maximum reusability

---

### 13 · Edge cases

- Flow orchestration prevents collisions when multiple nodes use same natural interface names through proxy mapping.

- Derived snapshots capture every override for perfect replay.

- Store values are write-once unless a node explicitly overwrites; validator warns on double-write.

- **Params mutability**: `params` values are runtime overrideable because they are isolated to the node and don't affect shared store data flow.

- **Mapping immutability**: The mapping structure (when defined) cannot be changed without modifying the IR.

- **Framework compatibility**: All node classes must inherit from `pocketflow.Node` and use natural shared store access.

---

### 14 · Appendix — full flow walk-through

```bash
pflow yt-transcript \
  --url=https://youtu.be/abc123 \
  >> summarise-text \
  --temperature=0.9
```

#### Step 1: Engine populates shared store

**CLI Resolution**:

```python
# CLI flag --url=https://youtu.be/abc123 goes to shared["url"]
shared = {
    "url": "https://youtu.be/abc123"  # Direct injection
}
```

#### Step 2: `yt-transcript` node execution

**Node Setup**:

```python
yt_node = YTTranscript()
yt_node.set_params({
    "language": "en"  # Default from IR
})
```

**prep() execution**:

```python
def prep(self, shared):
    return shared["url"]  # Natural interface

# Result: prep_data = "https://youtu.be/abc123"
```

**exec() execution**:

```python
def exec(self, prep_res):  # prep_res contains the URL
    language = self.params.get("language", "en")  # "en"
    return fetch_transcript(prep_res, language)

# Result: exec_result = "This is the video transcript content..."
```

**post() execution**:

```python
def post(self, shared, prep_data, exec_result):
    shared["transcript"] = exec_result  # Natural interface

# Shared store after yt-transcript node:
shared = {
    "url": "https://youtu.be/abc123",
    "transcript": "This is the video transcript content..."
}
```

#### Step 3: `summarise-text` node execution

**Node Setup**:

```python
summarise_node = SummariseText()
summarise_node.set_params({
    "temperature": 0.9  # Overridden by CLI --temperature=0.9
})
```

**prep() execution**:

```python
def prep(self, shared):
    return shared["text"]  # Natural interface - but wait, where's "text"?

# This would fail in simple mode - node expects "text" but shared has "transcript"
# Solution: Either use consistent naming OR use proxy mapping
```

**Corrected Scenario**: Using consistent natural naming:

```python
# Node expects "text", so either:
# 1. Use consistent names: shared["text"] = transcript_content
# 2. OR define mapping in IR to translate "text" → "transcript"
```

**With proxy mapping**:

```python
# IR defines mapping for summarise node:
"mappings": {
  "summarise-text": {
    "input_mappings": {"text": "transcript"}
  }
}

# Generated code creates proxy:
proxy = NodeAwareSharedStore(
    shared,
    input_mappings={"text": "transcript"}
)
summarise_node._run(proxy)  # Node accesses shared["text"], proxy maps to shared["transcript"]
```

#### Step 4: Final shared store state

```python
shared = {
  "url": "https://youtu.be/abc123",
  "transcript": "This is the video transcript content...",
  "summary": "Summary: The video discusses..."
}
```

**Key insight**: Same node code works whether using direct natural naming or proxy mapping for compatibility.
