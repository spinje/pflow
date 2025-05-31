## Shared-Store & Parameter Model — Canonical Spec

### 1 · Purpose

Define how **CLI arguments**, **IR bindings**, and the **flow-scoped shared store** interact, enabling a one-flag user model while preserving an immutable, hash-stable data-flow graph.

> **For conceptual understanding and architectural rationale**, see [Shared Store + Bindings Design Pattern](./Shared%20Store%20+%20Params%20Design%20Pattern%20in%20pflow.md)

---

### 2 · Concepts & Terminology

| Element | Role | Stored in lock-file | Part of DAG hash | Can change per run | Notes | 
|---|---|---|---|---|---|
| `input_bindings` | Map **CLI-facing names** (`url`, `text`, `stdin`) → **shared-store keys** | ✅ | ✅ (key names) | Values injected at runtime | Declares required data | 
| `output_bindings` | Map node outputs → store keys | ✅ | ✅ (key names) | Never | Enables downstream wiring | 
| `config` | Literal per-node tunables | Defaults stored; run-time overlays in derived snapshot | ❌ | ✅ via CLI | Does **not** create DAG edges | 
| Shared store | Flow-scoped key → value memory | Values never stored | Key names yes | Populated by CLI or pipe | Reserved key `stdin` | 

#### 2\.1 Quick-reference summary

| Field | Function | Affects DAG? | Overridable? | Stored? | Shared? | 
|---|---|---|---|---|---|
| `input_bindings` | External data wires | ✅ | ✅ (`--flag`) | ✅ | ✅ | 
| `config` | Behaviour knobs | ❌ | ✅ (`--flag`) | ✅ | ❌ | 
| `output_bindings` | Declared outputs | ✅ | ❌ | ✅ | ✅ | 

---

### 3 · Node Interface Integration

The bindings defined in IR map to the node's `prep()`/`exec()`/`post()` execution model:

```python
class YTTranscript(Node):
    def __init__(self):
        self.input_bindings = {}  # Set by IR: {"url": "video_url"}
        self.output_bindings = {} # Set by IR: {"transcript": "raw_transcript"}
        self.config = {}          # Set by IR: {"language": "en"}
    
    def prep(self, shared):
        # Read from shared store using bound key
        url_key = self.input_bindings["url"]  # "video_url"
        return shared[url_key]
    
    def exec(self, url):
        language = self.config.get("language", "en")
        return fetch_transcript(url, language)
    
    def post(self, shared, _, transcript):
        # Write to shared store using bound key  
        output_key = self.output_bindings["transcript"]  # "raw_transcript"
        shared[output_key] = transcript
```

#### 3\.1 CLI to Shared Store Flow

```
CLI Flag: --url=https://youtu.be/abc123
Input Binding: {"url": "video_url"}
Result: shared["video_url"] = "https://youtu.be/abc123"
Node Access: self.input_bindings["url"] → "video_url" → shared["video_url"]
```

The CLI interface name (`url`) is separate from the internal shared store key (`video_url`), enabling consistent external interfaces while allowing flexible internal naming.

---

### 4 · Canonical IR fragment

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

### 5 · Execution pipeline & CLI resolution

> **Single user rule** — *Type flags; engine decides.*\
> Flags that match any node's `input_bindings` are **data injections**; all others are **config overrides**. A Unix pipe populates key `stdin`.

#### Formal resolution algorithm

1. Parse CLI as flat `key=value`.

2. For each node (topological):

   - if `key ∈ input_bindings` → `shared_store[store_key] = value`

   - else if `key ∈ config` → override literal for this run.

3. Pipe content → `shared_store["stdin"]`.

4. Record all injections/overrides in run-log + derived snapshot.

---

### 6 · CLI scenarios

| Scenario | Command | Shared-store after injection | Derived snapshot? | 
|---|---|---|---|
| Provide video URL | `pflow yt-transcript --url=`[`https://youtu.be/abc`](https://youtu.be/abc) | `{ "video_url": "`[`https://youtu.be/abc`](https://youtu.be/abc)`" }` | No | 
| Override temperature | `pflow summarise-text --temperature=0.9` | – | Yes | 
| Pipe text | `cat notes.txt | pflow summarise-text` | `{ "stdin": "<bytes>" }` | Yes | 
| Chain fetch + summarise | `pflow yt-transcript --url=`[`https://youtu.be/abc`](https://youtu.be/abc)` >> summarise-text --temperature=0.9` | `{ "video_url": ..., "raw_transcript": ..., "article_summary": ... }` | Yes | 

---

### 7 · Integration Example: End-to-End Flow

#### 7.1 IR Definition
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

#### 7.2 CLI Command
```bash
pflow yt-transcript --url=https://youtu.be/abc123 >> summarise-text --temperature=0.9
```

#### 7.3 Shared Store Population
```python
shared = {
  "video_url": "https://youtu.be/abc123"  # From CLI injection
}
```

#### 7.4 Node Execution with Bindings

**Fetch Node**:
```python
# prep() reads from shared["video_url"] via input_bindings["url"]
# exec() processes the URL
# post() writes result to shared["raw_transcript"] via output_bindings["transcript"]
```

**Summarise Node**:
```python
# prep() reads from shared["raw_transcript"] via input_bindings["text"] 
# exec() uses config temperature=0.9 (CLI override)
# post() writes result to shared["article_summary"] via output_bindings["summary"]
```

#### 7.5 Final Shared Store State
```python
shared = {
  "video_url": "https://youtu.be/abc123",
  "raw_transcript": "Video transcript content...",
  "article_summary": "Generated summary..."
}
```

---

### 8 · Flow identity, caching & purity

- **Flow-hash** = ordered nodes + `input_bindings`/`output_bindings` key names + node ids/versions.

- **Node cache key** (`@flow_safe`) = node-hash ⊕ upstream key names ⊕ SHA-256(data) ⊕ effective `config`.

- `config` changes never alter graph hash; they just create a new node-level cache entry.

- If a `config` value changes side-effect surface, the node must declare itself **impure**.

---

### 9 · Validation rules

| \# | Rule | Failure action | 
|---|---|---|
| 1 | IR immutability — CLI cannot alter bindings or node set | Abort | 
| 2 | Unknown CLI flag | Abort | 
| 3 | Missing required binding value | Abort | 
| 4 | `config` always overrideable | Derived snapshot | 
| 5 | `stdin` key reserved; node must bind to it | Abort | 
| 6 | `output_bindings` keys unique flow-wide | Abort |
| 7 | `input_bindings` values can be populated from CLI for first nodes only | Abort |
| 8 | `output_bindings` structure immutable (cannot be changed outside IR) | Abort |

---

### 10 · Best practices & rationale

- Use generic CLI names (`url`, `text`) → disambiguate internally (`video_url`).

- Store injection for data; `config` for knobs.

- All `input_bindings` treated as required unless node sets default.

- **One-rule CLI** keeps user mental model shallow while IR guarantees auditability.

- Immutable graph + mutable data enables planner reuse and deterministic replay.

- **Bindings enable reusability** — same node, different flows, different shared store layouts.

- **Planner as compiler** — sets up shared schema and wires nodes via bindings without users micromanaging.

---

### 11 · Edge cases

- Planner prevents collisions when multiple nodes expose same CLI name.

- Derived snapshots capture every override for perfect replay.

- Store values are write-once unless a node explicitly overwrites; validator warns on double-write.

- **Config mutability**: `config` values are runtime overrideable because they are isolated to the node and don't affect shared store data flow.

- **Binding immutability**: The binding structure itself (which CLI names map to which store keys) cannot be changed without modifying the IR.

---

### 12 · Appendix — full flow walk-through

```bash
pflow yt-transcript \
  --url=https://youtu.be/abc123 \
  >> summarise-text \
  --temperature=0.9
```

1. Engine injects `video_url` via input binding.

2. `yt-transcript` node:
   - `prep()` reads `shared["video_url"]` via `input_bindings["url"]`
   - `exec()` fetches transcript
   - `post()` writes to `shared["raw_transcript"]` via `output_bindings["transcript"]`

3. `summarise-text` node:
   - `prep()` reads `shared["raw_transcript"]` via `input_bindings["text"]`
   - `exec()` summarizes with temperature 0.9 (CLI override)
   - `post()` writes to `shared["article_summary"]` via `output_bindings["summary"]`

4. Run-log + derived snapshot saved; caches updated.