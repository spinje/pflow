# Product Requirements Document: pflow CLI

*A shell-native engine for deterministic, memory-aware, agent-planned flows that wrap MCP tools and reusable Python nodes.*

---

## 1 Vision & Positioning

> **pflow** turns natural language or terse CLI chains into explicit, replayable DAGs.\
> Unlike chat-only agents (Claude Desktop) or heavyweight orchestration stacks (Airflow, LangChain), pflow is a **minimal, traceable, node-based runtime** that emphasises **structured composition** first, with agent planning and MCP interoperability layered on top.

pflow’s defining promise is that a one-line natural-language prompt is compiled—through a deterministic, auditable planning sub-flow—into the same lock-file-backed DAG a power-user would hand-write. Intuitive intent is preserved **without** sacrificing deterministic execution, caching discipline, or traceability.

Primary differentiator → **Structured composition** (declarative flows, shared-store routing, version-pinned nodes).\
Agentic planning and MCP integration are enablers—not the core.

### 1\.1 Strategic Differentiators

| Differentiator | Description | Implementation Hooks | 
|---|---|---|
| **Transparent Execution** | Every node’s data, config, and errors are trace-logged and replayable. | CLI `--trace`, IR → run log schema, deterministic replay via `.lock.json`. | 
| **Composable Intelligence** | Complex automations built from simple, reusable nodes or subflows. | Pipe CLI grammar (`>>`), flows-as-nodes, validated IR DAGs with typed keys. | 
| **Deterministic Reproducibility** | Execution behavior is locked across environments and time. | IR versioning, semver-pinned nodes, lock-files, input-bindings/param split. | 
| **Caching & Efficiency Control** | Reuse of expensive results is always opt-in and safe. | `@flow_safe` nodes + CLI-level cache flags; content-keyed node-level caching. | 
| **Fine-grained Resilience** | Only safe nodes are retried; all failure points are logged, typed, and recoverable. | Retry logic scoped to pure nodes; retry contracts in flow IR. | 
| **NL ↔ Flow Round-Tripping** | Natural-language prompts compile to pipe syntax → IR → lock-file, then back to NL for explain or search. No structural loss at any stage. | Deterministic planner flow, shadow-store pre-validator, pipe-to-IR compiler, `description` field on flows, future `--explain` command. | 
| **Planner–Executor Separation** | NL is interpreted via a deterministic subflow that outputs pipe syntax → IR, validated before execution. | Planner flow emits pipes, validated with shadow store + compiler; provenance recorded. | 
| **Cognitive Middleware Alignment** | Flows externalize semantic context for agents and users to re-enter thought processes. | Shared store memory model; `description` used for flow retrieval; composable flow IRs. | 
| **Vendor-Neutral Modularity** | No hard binding to any LLM or backend service. | MCP wrappers; semver namespacing; pluggable local or remote back-ends. | 

### 1\.2 Design Philosophy

- **Explicit Over Magic**\
   Nothing is implicit. All I/O, bindings, side-effects, and caching constraints are declared in the IR and visible in the CLI.

- **Transparent Planning from Natural Language**

   NL input yields structured flows shown as CLI pipes before execution; users inspect, learn, and evolve from intent to explicit control without hidden logic.

- **Purity First, Impurity Declared**\
   Nodes are impure by default. Only nodes explicitly marked `@flow_safe` may be cached or retried. Unsafe behavior is opt-in, logged, and localized.

- **Planner–Executor Decoupling**\
   Natural language is not interpreted directly. A separate, deterministic planner flow transforms NL into pipe syntax, which is then compiled to IR and validated. This separation ensures traceability, testability, and semantic integrity.

- **Flows Are First-Class, Inspectable Artifacts**\
   Every generated flow is validated, saved, and traceable—never ephemeral or hidden. Execution guarantees apply regardless of origin (human or planner).

- **Round-Trippable Intent**\
   All flows and nodes carry `description` metadata that reflects original user intent in natural language. This metadata is used for planner reuse, UI summaries, and future `--explain` reverse mapping.

- **Immutable Graph, Mutable Data**\
   The IR defines a frozen DAG. Runtime inputs are passed via shared store bindings or config overrides. This enables planner reuse without graph mutations.

- **Composable Simplicity**\
   Each node solves one clear task. Flows and nodes interoperate through shared-store keys. Flows can be nested, versioned, and reused like any node.

- **Granular Trust & Debuggability**\
   Trust is earned per node and per run. Tracing, run logs, and planner provenance are mandatory for all executions. Replays are deterministic.

- **Controlled Flexibility**\
   CLI flags expose all toggles: caching, retries, param overrides. Nothing is auto-enabled or magic. Every override is tracked and audit-logged.

### 1\.3 Natural-Language Planning Pipeline

1. **Capture** – CLI receives raw prompt.

2. **Plan** – Delegates to a version‑pinned PocketFlow *planner* sub‑flow. The planner **first searches** the validated‑flow library for a semantic match and reuses it when found; generation is a fallback. Whether reused or generated, the result is a candidate pipe string.

3. **Shadow Validate** – Type-only shared-store check; failures trigger automated planner retry up to `budget.n`.

4. **User Preview** – First passing pipe is echoed; user may abort or edit.

5. **Compile** – Pipe compiled to canonical JSON IR.

6. **Full Validate** – IR passes lint, purity, retries, semver, side-effect gates.

7. **Persist** – Lock-file written unless `--no-lock`; provenance (`planner_version`, `planner_run_id`) embedded.

8. **Execute** – Standard engine run; trace, cache, retry semantics identical to hand-authored flows.

Round-trip guarantee: *prompt → pipe → IR → lock-file → run-log → NL-summary*.

---

## 2 Out-of-Scope for MVP

| Excluded | Rationale | 
|---|---|
| Auto-generating node code | Keeps surface small; focus on wrapping existing MCP tools and curated core nodes. | 
| GUI authoring / YAML flows | CLI + JSON IR are sufficient; GUI can be a later layer. | 
| Mid-run user interaction | Nodes run to completion (`prep → exec → post`) with no pauses. | 
| Global, implicit state | All data lives in per-run `shared` or explicit external side-effect nodes. | 

---

## 3 Core Concepts

### 3\.1 Node

- Python class with `prep`, `exec`, `post`.

- No direct knowledge of other nodes; communicates via **shared-store keys** given in `params`.

- **Impure by default**. Marked `@flow_safe` if deterministic, idempotent, side-effect-free (required for retry/cache).

### 3\.2 Shared Store + Params Pattern

- `shared : dict` travels through the flow.

- Each node’s `params` tell it **which keys** in `shared` to read/write—never hard‑coded paths.

- Flow IR is the single source of memory wiring.

#### 3\.2.1 CLI Parameter‑Resolution Algorithm

1. **Flag classification** – At run time each `key=value` CLI flag is checked against the first node that exposes that key.

   - *If it matches an `input_bindings` name* → value injected into `shared` under the corresponding store key.

   - *Else if it matches the node’s `config` field* → value becomes a *config override* captured in a **derived snapshot** (does **not** change the flow hash).

   - *Else* → engine aborts with `ERR_UNKNOWN_FLAG`.

2. **Pipe stdin** – When data is piped into `pflow`, bytes are injected as `shared["stdin"]`; that key name is **reserved**.

3. **Audit trail** – All injections and overrides, together with the derived snapshot hash, are recorded in the run‑log.

### 3\.3 Flow

- Directed acyclic graph of nodes.

- Defined in one of three surfaces:

   1. Python (`crawl >> analyze >> report`)

   2. CLI chain (`pflow crawl >> analyze >> report`)

   3. **JSON IR** (agent & persistence layer)

- Flow cannot mutate itself at runtime.

### 3\.4 JSON IR (v 0.1)

Governed by the spec in *JSON IR [Governance.md](Governance.md)* — includes schema URL, semantic version, nodes array, edges array, execution directives (`retries`, `use_cache`), and lock table. Unknown higher major IR version aborts execution.

---

## 4 Execution Semantics

### 4\.1 Failure & Retry

- Default: **fail-fast** — first uncaught exception aborts flow.

- Optional `exec.retries` (integer ≥ 0) for `@flow_safe` nodes; same inputs, fixed back-off.

- All failures (attempt timeline, params, stack trace, shared snapshot) go to run-log & `pflow trace`.

### 4\.2 Caching (opt-in)

- Only `@flow_safe` nodes.

- CLI flags: `--use-cache`, `--reset-cache`.

- Key = SHA-256(node-type + params + input hash). Stored at `~/.pflow/cache/<hash>.json`.

### 4\.3 Side-Effect Model

- **Impure is default.**

- Pure nodes explicitly declared with decorator; only these can be cached or retried.

- No side-effect enumeration in MVP.

### 4\.4 NL → Flow Guarantees

| Guarantee | Mechanism | 
|---|---|
| Structural soundness before execution | Shadow‑store pass + full validator gates | 
| Provenance recorded | `planner_version`, `planner_run_id`, origin tag \`{planner | 
| Reproducibility of accepted flows | Lock‑file produced on first successful run; subsequent runs skip planner | 
| Safe caching/retry | Only `@flow_safe` nodes eligible **and** run‑log origin =`planner`; other origins require `--force-cache` | 
| Failure transparency | Planner retry exhaustion emits `.failed.lock.json` + `planner_log.json` | 

---

## 5 MCP Integration

### 5\.1 Registrar & Registry

- JSON registry `~/.pflow/mcp.json` (or project-local override) defines servers, transports, auth env-vars, autostart flags.

- CLI: `pflow mcp add / list / launch / daemon`.

### 5\.2 Wrapper Generation

- On `install-mcp <url>` pflow fetches `/tools/list`, generates one wrapper node per tool, pins `tool_version` & `manifest_sha`, writes to `~/.pflow/nodes/mcp/...`.

- Transport handlers for `stdio`, `uds`, `pipe`, `sse`, `stream-http`.

### 5\.3 Security

- Remote transports require HTTPS; tokens via env-vars referenced in registry.

- Side-effects marked “network”; wrapper nodes default to impure.

- Optional certificate pinning & host allow-list.

---

## 6 CLI Surface (initial)

| Command | Purpose |  | 
|---|---|---|
| `pflow <node>[args] >> <node>[args]` | Run explicit chain. |  | 
| `pflow "<natural instruction>"` | Calls the planner; prints proposed pipe; executes only after `--yes` or interactive confirmation. |  | 
| `pflow trace <run-id>` | Inspect DAG, params, shared snapshots, cache hits, retries, failures. |  | 
| `pflow list` | Show installed nodes (name, version, flow_safe, side-effect flag). |  | 
| `pflow lock` | Emit lock-file for deterministic CI runs. |  | 
| \`pflow test <node | flow>\` | Run validation suite. | 
| `pflow mcp ...` | Manage MCP registry & server lifecycle. |  | 

---

## 7 Validation Pipeline (before run)

1. Shadow-store type validation of planner-generated pipe; on fail, planner retry.

2. JSON parse (no comments).

3. `$schema` + `ir_version` compatible? else abort.

4. Cycle detection.

5. Node identifier resolution (namespace, version).

6. Schema validation of each node’s `params`.

7. `@flow_safe` gate for `exec.retries` or `exec.use_cache`.

8. Shared-key wiring lint.

---

## 8 Node Discovery & Version Resolution

- Search order: flow-local → user → system → built-in.

- No implicit “latest”; unspecified version + multiple installs = error.

- `pflow lock` pins exact versions; CLI shorthand accepted only when unique.

---

## 9 Testing & Quality Gates

- **Node unit tests**: fixtures for `params` + `shared`; assert mutations.

- **Flow tests**: run on stubbed nodes or mock MCP servers; assert final `shared`.

- `pflow test` command discovers `tests/` directory in node package.

- CI policy: no node published to public registry without `@flow_safe` validation + test pass.

---

## 10 Traceability & Observability

- Every run creates a **run-log** (SQLite) with:

   - node order, params, input hash, output hash

   - cache hit/miss

   - retry attempts

   - failure trace

- `pflow trace` renders a textual DAG and optionally dumps intermediate shared snapshots to `./trace/<run-id>/`.

---

## 11 User Journey

1. **Exploration**

   ```
   pflow "get the weather for Stockholm and Oslo and summarize differences"
   
   ```

   → Agent proposes CLI chain; user confirms.

2. **Iteration**

   ```
   pflow mcp install-mcp https://api.weathercorp.com
   pflow weather.get --city Stockholm --retries 2 >> summarize >> save_file --path wx.md
   
   ```

3. **Hardening**

   ```
   pflow lock
   git add flow.lock.json
   
   ```

4. **Automation**

   ```
   0 * * * * pflow run my_hourly_flow.lock.json --use-cache
   
   ```

---

## 12 MVP Acceptance Criteria

| Metric | Target | 
|---|---|
| End-to-end flow latency (3-node pure flow) | ≤ 2 s overhead vs raw Python | 
| `pflow trace` correctness | 100 % node order, param, cache & retry info | 
| JSON IR validation false-negative rate | 0 critical misses in test suite | 
| Reproducibility | Same lock-file → identical outputs across machines (pure nodes) | 
| MCP wrapper generation | ≥ 95 % of `/tools/list` entries wrap without manual edits | 
| Docs | Quick-start (<5 min) reproduces “weather summary” example | 
| NL-prompt → validated lock-file success rate (planner default prompts) | ≥ 95 % within ≤ 3 planner retries | 

---

## 13 Roadmap Beyond v0.1 (High-confidence order)

1. **Checkpoint & resume** (`pflow resume run-123`)

2. **Partial-graph retries** / dynamic back-off strategy

3. **Remote cache backend (Redis/S3)**

4. GUI DAG explorer (web)

5. Claude-Code node scaffolder plugin

6. Side-effect schema (when untrusted nodes become common)

7. Distributed runner (k8s / Nomad)

---

## 14 Open Risks

| Risk | Mitigation | 
|---|---|
| Ecosystem fragmentation (many near-identical nodes). | Namespacing + search/registry UX + strong docs. | 
| Agent flow-planning hallucinations. | Human confirmation, IR validation gate. | 
| Security of remote MCP tokens. | Env-var only in MVP; secret store on roadmap. | 
| Cache poisoning for “pure” nodes accidentally impure. | Manual code review before `@flow_safe`; tooling lint. | 

---

## 15 Conclusion

pflow v0.1 delivers a **deterministic, observable foundation** for intelligent CLI automation by marrying:

- **Composable Python nodes**

- **Strict, versioned flow IR**

- **Opt-in cache/retry discipline**

- **First-class MCP tool wrappers**

- **Agent-assisted but user-confirmed planning**

…while keeping the implementation surface tight enough (\~100 LOC core runner + registrars) to remain hackable, auditable, and extensible.