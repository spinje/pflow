## Shared-Store & Parameter Model — Canonical Spec

### 1 · Purpose

Define how **CLI arguments**, **IR bindings**, and the **flow-scoped shared store** interact, enabling a one-flag user model while preserving an immutable, hash-stable data-flow graph.

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

### 3 · Canonical IR fragment

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
  ]
}

```

Graph: `yt-transcript` ➜ `summarise-text` (wired through `raw_transcript`).

---

### 4 · Execution pipeline & CLI resolution

> **Single user rule** — *Type flags; engine decides.*\
> Flags that match the first node’s `input_bindings` are **data injections**; all others are **config overrides**. A Unix pipe populates key `stdin`.

#### Formal resolution algorithm

1. Parse CLI as flat `key=value`.

2. For each node (topological):

   - if `key ∈ input_bindings` → `shared_store[store_key] = value`

   - else if `key ∈ config` → override literal for this run.

3. Pipe content → `shared_store["stdin"]`.

4. Record all injections/overrides in run-log + derived snapshot.

---

### 5 · CLI scenarios

| Scenario | Command | Shared-store after injection | Derived snapshot? | 
|---|---|---|---|
| Provide video URL | `pflow yt-transcript --url=`[`https://youtu.be/abc`](https://youtu.be/abc) | `{ "video_url": "`[`https://youtu.be/abc`](https://youtu.be/abc)`" }` | No | 
| Override temperature | `pflow summarise-text --temperature=0.9` | – | Yes | 
| Pipe text | `cat notes.txt | pflow summarise-text` | `{ "stdin": "<bytes>" }` | Yes | 
| Chain fetch + summarise | `pflow yt-transcript --url=`[`https://youtu.be/abc`](https://youtu.be/abc)` >> summarise-text --temperature=0.9` | `{ "video_url": ..., "raw_transcript": ..., "article_summary": ... }` | Yes | 

---

### 6 · Flow identity, caching & purity

- **Flow-hash** = ordered nodes + `input_bindings`/`output_bindings` key names + node ids/versions.

- **Node cache key** (`@flow_safe`) = node-hash ⊕ upstream key names ⊕ SHA-256(data) ⊕ effective `config`.

- `config` changes never alter graph hash; they just create a new node-level cache entry.

- If a `config` value changes side-effect surface, the node must declare itself **impure**.

---

### 7 · Validation rules

| \# | Rule | Failure action | 
|---|---|---|
| 1 | IR immutability — CLI cannot alter bindings or node set | Abort | 
| 2 | Unknown CLI flag | Abort | 
| 3 | Missing required binding value | Abort | 
| 4 | `config` always overrideable | Derived snapshot | 
| 5 | `stdin` key reserved; node must bind to it | Abort | 
| 6 | `output_bindings` keys unique flow-wide | Abort | 

---

### 8 · Best practices & rationale

- Use generic CLI names (`url`, `text`) → disambiguate internally (`video_url`).

- Store injection for data; `config` for knobs.

- All `input_bindings` treated as required unless node sets default.

- **One-rule CLI** keeps user mental model shallow while IR guarantees auditability.

- Immutable graph + mutable data enables planner reuse and deterministic replay.

---

### 9 · Edge cases

- Planner prevents collisions when multiple nodes expose same CLI name.

- Derived snapshots capture every override for perfect replay.

- Store values are write-once unless a node explicitly overwrites; validator warns on double-write.

---

### 10 · Appendix — full flow walk-through

```bash
pflow yt-transcript \
  --url=https://youtu.be/abc123 \
  >> summarise-text \
  --temperature=0.9

```

1. Engine injects `video_url`.

2. `yt-transcript` writes `raw_transcript`.

3. `summarise-text` reads it, writes `article_summary` (temp 0.9).

4. Run-log + derived snapshot saved; caches updated.