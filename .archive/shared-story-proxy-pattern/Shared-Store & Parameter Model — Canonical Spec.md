## Shared-Store & Parameter Model — Canonical Spec

### 1 · Purpose

Define how **CLI arguments**, **IR bindings**, and the **flow-scoped shared store** interact, enabling a one-flag user model while preserving an immutable, hash-stable data-flow graph.

This specification details the implementation using the **pocketflow framework** and shows how generated flow code integrates with static node classes.

> **For conceptual understanding and architectural rationale**, see [Shared Store + Bindings Design Pattern](./Shared%20Store%20+%20Params%20Design%20Pattern%20in%20pflow.md)

---

### 2 · pocketflow Framework Integration

Our pattern leverages the lightweight **pocketflow framework** (100 lines of Python):

- **Static node classes**: Inherit from `pocketflow.Node` with `prep()`/`exec()`/`post()` methods
- **Params system**: Use `set_params()` to configure bindings and config
- **Flow orchestration**: Use `>>` operator and `Flow` class for wiring
- **No modifications**: Pure pattern implementation using existing framework APIs

> **See also**: [pocketflow framework](../pocketflow/__init__.py) and [communication patterns](../pocketflow/docs/core_abstraction/communication.md)

**Framework vs Pattern**:
- **pocketflow**: The underlying 100-line framework
- **pflow pattern**: Our specific use of input_bindings/output_bindings/config within pocketflow's params system

---

### 3 · Concepts & Terminology

| Element | Role | Stored in lock-file | Part of DAG hash | Can change per run | Notes | 
|---|---|---|---|---|---|
| `input_bindings` | Map **CLI-facing names** (`url`, `text`, `stdin`) → **shared-store keys** | ✅ | ✅ (key names) | Values injected at runtime | Declares required data | 
| `output_bindings` | Map node outputs → store keys | ✅ | ✅ (key names) | Never | Enables downstream wiring | 
| `config` | Literal per-node tunables | Defaults stored; run-time overlays in derived snapshot | ❌ | ✅ via CLI | Does **not** create DAG edges | 
| Shared store | Flow-scoped key → value memory | Values never stored | Key names yes | Populated by CLI or pipe | Reserved key `stdin` | 

#### 3\.1 Quick-reference summary

| Field | Function | Affects DAG? | Overridable? | Stored? | Shared? | 
|---|---|---|---|---|---|
| `input_bindings` | External data wires | ✅ | ✅ (`--flag`) | ✅ | ✅ | 
| `config` | Behaviour knobs | ❌ | ✅ (`--flag`) | ✅ | ❌ | 
| `output_bindings` | Declared outputs | ✅ | ❌ | ✅ | ✅ | 

---

### 4 · Node Interface Integration

The bindings defined in IR map to static node classes using pocketflow's `params` system:

```python
# Node class (static, pre-written)
class YTTranscript(Node):  # Inherits from pocketflow.Node
    def prep(self, shared):
        # Access input binding through existing params system
        url_key = self.params["input_bindings"]["url"]  # "video_url"
        return shared[url_key]
    
    def exec(self, url):
        # Access config through existing params system
        language = self.params["config"].get("language", "en")
        return fetch_transcript(url, language)
    
    def post(self, shared, prep_res, exec_res):
        # Access output binding through existing params system
        output_key = self.params["output_bindings"]["transcript"]  # "raw_transcript"
        shared[output_key] = exec_res

# Generated flow code (from IR)
node = YTTranscript()
node.set_params({
    "input_bindings": {"url": "video_url"},
    "output_bindings": {"transcript": "raw_transcript"},
    "config": {"language": "en"}
})
```

#### 4\.1 CLI to Shared Store Flow

```
CLI Flag: --url=https://youtu.be/abc123
Input Binding: {"url": "video_url"}
Result: shared["video_url"] = "https://youtu.be/abc123"
Node Access: self.params["input_bindings"]["url"] → "video_url" → shared["video_url"]
```

The CLI interface name (`url`) is separate from the internal shared store key (`video_url`), enabling consistent external interfaces while allowing flexible internal naming.

---

### 5 · Canonical IR fragment

```json
{
  "nodes": [
    {
      "id": "fetch",
      "name": "yt-transcript",
      "input_bindings": { "url": "video_url" },
      "output_bindings": { "transcript": "raw_transcript" },
      "config": { "language": "en" }
    },
    {
      "id": "summarise",
      "name": "summarise-text",
      "input_bindings": { "text": "raw_transcript" },
      "output_bindings": { "summary": "article_summary" },
      "config": { "temperature": 0.7 }
    }
  ],
  "edges": [
    {"from": "fetch", "to": "summarise"}
  ]
}
```

Graph: `yt-transcript` ➜ `summarise-text` (wired through `raw_transcript`).

---

### 6 · Execution pipeline & CLI resolution

> **Single user rule** — *Type flags; engine decides.*\
> Flags that match any node's `input_bindings` are **data injections**; all others are **config overrides**. A Unix pipe populates key `stdin`.

#### Updated resolution algorithm

1. Parse CLI as flat `key=value`.

2. For CLI flags matching `input_bindings`: inject into `shared_store[store_key] = value`

3. For CLI flags matching `config`: update the corresponding node's params via `set_params()`

4. Generate flow code with updated configurations using pocketflow APIs

5. Execute flow with populated shared store

---

### 7 · CLI scenarios

| Scenario | Command | Shared-store after injection | Derived snapshot? | 
|---|---|---|---|
| Provide video URL | `pflow yt-transcript --url=`[`https://youtu.be/abc`](https://youtu.be/abc) | `{ "video_url": "`[`https://youtu.be/abc`](https://youtu.be/abc)`" }` | No | 
| Override temperature | `pflow summarise-text --temperature=0.9` | – | Yes | 
| Pipe text | `cat notes.txt | pflow summarise-text` | `{ "stdin": "<bytes>" }` | Yes | 
| Chain fetch + summarise | `pflow yt-transcript --url=`[`https://youtu.be/abc`](https://youtu.be/abc)` >> summarise-text --temperature=0.9` | `{ "video_url": ..., "raw_transcript": ..., "article_summary": ... }` | Yes | 

---

### 8 · Integration Example: End-to-End Flow

#### 8.1 IR Definition
```json
{
  "nodes": [
    {
      "id": "fetch",
      "name": "yt-transcript", 
      "input_bindings": {"url": "video_url"},
      "output_bindings": {"transcript": "raw_transcript"},
      "config": {"language": "en"}
    },
    {
      "id": "summarise",
      "name": "summarise-text",
      "input_bindings": {"text": "raw_transcript"}, 
      "output_bindings": {"summary": "article_summary"},
      "config": {"temperature": 0.7}
    }
  ],
  "edges": [{"from": "fetch", "to": "summarise"}]
}
```

#### 8.2 CLI Command
```bash
pflow yt-transcript --url=https://youtu.be/abc123 >> summarise-text --temperature=0.9
```

#### 8.3 Shared Store Population
```python
shared = {
  "video_url": "https://youtu.be/abc123"  # From CLI injection
}
```

#### 8.4 Generated Flow Code
```python
# This code is generated from IR
def create_flow():
    # Instantiate static node classes
    fetch_node = YTTranscript()
    summarize_node = SummarizeText()
    
    # Configure nodes with IR bindings
    fetch_node.set_params({
        "input_bindings": {"url": "video_url"},
        "output_bindings": {"transcript": "raw_transcript"},
        "config": {"language": "en"}
    })
    
    summarize_node.set_params({
        "input_bindings": {"text": "raw_transcript"},
        "output_bindings": {"summary": "article_summary"},
        "config": {"temperature": 0.9}  # Overridden by CLI
    })
    
    # Wire the flow using pocketflow operators
    fetch_node >> summarize_node
    
    return Flow(start=fetch_node)

# CLI execution
def run_with_cli():
    shared = {"video_url": "https://youtu.be/abc123"}  # CLI injection
    flow = create_flow()
    flow.run(shared)
```

#### 8.5 Node Execution with Bindings

**Fetch Node**:
```python
# prep() reads from shared["video_url"] via self.params["input_bindings"]["url"]
# exec() processes the URL using self.params["config"]["language"]
# post() writes result to shared["raw_transcript"] via self.params["output_bindings"]["transcript"]
```

**Summarise Node**:
```python
# prep() reads from shared["raw_transcript"] via self.params["input_bindings"]["text"] 
# exec() uses self.params["config"]["temperature"] = 0.9 (CLI override)
# post() writes result to shared["article_summary"] via self.params["output_bindings"]["summary"]
```

#### 8.6 Final Shared Store State
```python
shared = {
  "video_url": "https://youtu.be/abc123",
  "raw_transcript": "Video transcript content...",
  "article_summary": "Generated summary..."
}
```

---

### 9 · Flow identity, caching & purity

- **Flow-hash** = ordered nodes + `input_bindings`/`output_bindings` key names + node ids/versions.

- **Node cache key** (`@flow_safe`) = node-hash ⊕ upstream key names ⊕ SHA-256(data) ⊕ effective `config`.

- `config` changes never alter graph hash; they just create a new node-level cache entry.

- If a `config` value changes side-effect surface, the node must declare itself **impure**.

---

### 10 · Validation rules

| \# | Rule | Failure action | 
|---|---|---|
| 1 | IR immutability — CLI cannot alter bindings or node set | Abort | 
| 2 | Unknown CLI flag | Abort | 
| 3 | Missing required binding value | Abort | 
| 4 | `config` always overrideable via `set_params()` | Derived snapshot | 
| 5 | `stdin` key reserved; node must bind to it | Abort | 
| 6 | `output_bindings` keys unique flow-wide | Abort | 
| 7 | `input_bindings` values can be populated from CLI for first nodes only | Abort |
| 8 | `output_bindings` structure immutable (cannot be changed outside IR) | Abort |
| 9 | Node classes must inherit from `pocketflow.Node` | Abort |

---

### 11 · Best practices & rationale

- Use generic CLI names (`url`, `text`) → disambiguate internally (`video_url`).

- Store injection for data; `config` for knobs.

- All `input_bindings` treated as required unless node sets default.

- **One-rule CLI** keeps user mental model shallow while IR guarantees auditability.

- Immutable graph + mutable data enables planner reuse and deterministic replay.

- **Bindings enable reusability** — same node, different flows, different shared store layouts.

- **Planner as compiler** — sets up shared schema and wires nodes via bindings without users micromanaging.

- **Static nodes, dynamic flows** — node logic is reusable, flow wiring is generated.

---

### 12 · Edge cases

- Planner prevents collisions when multiple nodes expose same CLI name.

- Derived snapshots capture every override for perfect replay.

- Store values are write-once unless a node explicitly overwrites; validator warns on double-write.

- **Config mutability**: `config` values are runtime overrideable because they are isolated to the node and don't affect shared store data flow.

- **Binding immutability**: The binding structure itself (which CLI names map to which store keys) cannot be changed without modifying the IR.

- **Framework compatibility**: All node classes must inherit from `pocketflow.Node` and use the params system.

---

### 13 · Appendix — full flow walk-through

```bash
pflow yt-transcript \
  --url=https://youtu.be/abc123 \
  >> summarise-text \
  --temperature=0.9
```

#### Step 1: Engine injects `video_url` via input binding

**CLI Resolution**:
```python
# CLI flag --url=https://youtu.be/abc123 matches input_bindings["url"] -> "video_url"
shared = {
    "video_url": "https://youtu.be/abc123"  # Injected from CLI
}
```

#### Step 2: `yt-transcript` node execution

**Overview**:
- `prep()` reads `shared["video_url"]` via `self.params["input_bindings"]["url"]`
- `exec()` fetches transcript using `self.params["config"]["language"]`
- `post()` writes to `shared["raw_transcript"]` via `self.params["output_bindings"]["transcript"]`

**Node Setup**:
```python
yt_node = YTTranscript()
yt_node.set_params({
    "input_bindings": {"url": "video_url"},
    "output_bindings": {"transcript": "raw_transcript"},
    "config": {"language": "en"}  # Default from IR
})
```

**prep() execution**:
```python
def prep(self, shared):
    url_key = self.params["input_bindings"]["url"]  # "video_url"
    return shared[url_key]  # Returns "https://youtu.be/abc123"

# Result: prep_data = "https://youtu.be/abc123"
```

**exec() execution**:
```python
def exec(self, url):
    language = self.params["config"].get("language", "en")  # "en"
    return fetch_transcript(url, language)

# Result: exec_result = "This is the video transcript content..."
```

**post() execution**:
```python
def post(self, shared, prep_data, exec_result):
    output_key = self.params["output_bindings"]["transcript"]  # "raw_transcript"
    shared[output_key] = exec_result

# Shared store after yt-transcript node:
shared = {
    "video_url": "https://youtu.be/abc123",
    "raw_transcript": "This is the video transcript content..."
}
```

#### Step 3: `summarise-text` node execution

**Overview**:
- `prep()` reads `shared["raw_transcript"]` via `self.params["input_bindings"]["text"]`
- `exec()` summarizes with temperature 0.9 (CLI override in `self.params["config"]`)
- `post()` writes to `shared["article_summary"]` via `self.params["output_bindings"]["summary"]`

**Node Setup**:
```python
summarise_node = SummariseText()
summarise_node.set_params({
    "input_bindings": {"text": "raw_transcript"},
    "output_bindings": {"summary": "article_summary"},
    "config": {"temperature": 0.9}  # Overridden from CLI --temperature=0.9
})
```

**prep() execution**:
```python
def prep(self, shared):
    text_key = self.params["input_bindings"]["text"]  # "raw_transcript"
    return shared[text_key]  # Returns "This is the video transcript content..."

# Result: prep_data = "This is the video transcript content..."
```

**exec() execution**:
```python
def exec(self, text):
    temperature = self.params["config"].get("temperature", 0.7)  # 0.9 (CLI override)
    return call_llm(text, temperature=temperature)

# Result: exec_result = "Summary: The video discusses..."
```

**post() execution**:
```python
def post(self, shared, prep_data, exec_result):
    output_key = self.params["output_bindings"]["summary"]  # "article_summary"
    shared[output_key] = exec_result

# Final shared store state:
shared = {
    "video_url": "https://youtu.be/abc123",
    "raw_transcript": "This is the video transcript content...",
    "article_summary": "Summary: The video discusses..."
}
```

#### Step 4: Run-log + derived snapshot saved; caches updated

**Derived Snapshot** (captures runtime overrides):
```python
derived_snapshot = {
    "config_overrides": {
        "summarise": {"temperature": 0.9}  # CLI override recorded
    },
    "cli_injections": {
        "video_url": "https://youtu.be/abc123"  # CLI injection recorded
    }
}
```

**Complete Flow State**:
```python
flow_execution = {
    "shared_store": {
        "video_url": "https://youtu.be/abc123",
        "raw_transcript": "This is the video transcript content...",
        "article_summary": "Summary: The video discusses..."
    },
    "derived_snapshot": derived_snapshot,
    "execution_trace": [
        {"node": "yt-transcript", "read_keys": ["video_url"], "write_keys": ["raw_transcript"]},
        {"node": "summarise-text", "read_keys": ["raw_transcript"], "write_keys": ["article_summary"]}
    ]
}
```