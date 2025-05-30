# Planner Responsibility & Functionality Spec

---

## 1 · Purpose

The **planner** converts a *natural-language prompt* issued through the `pflow` CLI into a *validated, deterministic flow* ready for execution.\
Its primary goal is to give users an intuitive entry point **without sacrificing** pflow’s guarantees of auditability, purity, caching, and reproducibility.

---

## 2 · Architectural Position

```plain
             ┌─────────────┐
Prompt  ───▶ │   CLI shim  │
             └────┬────────┘
                  │ NL string
                  ▼
             ┌─────────────┐
             │   PLANNER   │  (PocketFlow sub-DAG)
             └────┬────────┘
     pipe / IR    │
                  ▼
           Validation Gates
                  │
                  ▼
             Execution DAG

```

- The planner is implemented **as a normal PocketFlow flow**—not hard-coded logic.

- It runs **before** any user code executes and obeys all node/purity rules itself.

---

## 3 · Core Responsibilities

| Stage | Responsibility | Outcome | 
|---|---|---|
| **3\.1 Retrieval** | Search existing validated flows for semantic match to prompt. | Returns *pipe preview* + associated lock file if found. | 
| **3\.2 Generation** | If retrieval fails, compose a new *pipe* string that satisfies user intent. | Returns draft pipe; never emits IR directly. | 
| **3\.3 Shadow Validation** | Type-level check on draft pipe (bindings only). | Pass → continue, Fail → repair or retry. | 
| **3\.4 Parameter Resolution** | Ensure all `input_bindings` have values and `config` defaults are acceptable.— Prompt user (interactive)— Infer from context (non-interactive attempt)— Abort if unsatisfied | Fully specified pipe string. | 
| **3\.5 Pipe→IR Compilation** | Convert pipe to canonical IR using shared compiler. | IR with bindings, purity flags, semver pins. | 
| **3\.6 IR Validation Gates** | Full lint, purity, namespace, dry-run checks. | Validated lock file (`*.lock.json`). | 
| **3\.7 Handoff** | Return lock file to CLI for execution. | CLI may save, show, or run immediately. | 

---

## 4 · Retrieval Logic

1. **Index**: JSON table of `{hash, description, pipe_preview}` for all prior validated flows (local project scope).

2. **Match algorithm (MVP)**

   - Exact pipe string match → immediate hit.

   - Fuzzy string similarity (`description` vs prompt) above threshold → candidate.

   - Prefer shortest pipe on tie (minimise complexity).

3. **Determinism**: Same prompt + same index → same retrieval result.

*If multiple hits remain, planner lists ranked options and aborts unless user selects.*

---

## 5 · Generation Logic

1. **Prompt-to-Draft pipeline**

   - LLM node suggests ordered node names plus minimal flags.

   - Each suggested node validated against registry for existence & purity.

2. **Retry budget**: `N=4` attempts. On failure planner sends structured error back to LLM node with validator messages.

3. **Deterministic envelope**: The *process* (node graph, retry count, validator rules) is deterministic; LLM output is not.

4. **Provenance**: Planner version, LLM model, temperature recorded in planner log, not in DAG hash.

---

## 6 · Parameter Resolution

| Case | Planner action | 
|---|---|
| Required `input_binding` missing | • Interactive: prompt user → inject value.• Non-interactive: abort with code `MISSING_INPUT`. | 
| `config` value unspecified | Accept node default.If node has **no default**, abort `MISSING_CONFIG`. | 
| User-supplied CLI flag collides with planner value | CLI flag **overrides** planner suggestion.Override recorded in derived snapshot. | 

*Changing `config` never alters DAG hash; missing `input_binding` **blocks execution**.*

---

## 7 · Validation Rules Recap

1. **Shadow type check** (bindings only).

2. **Pipe→IR compiler** must succeed.

3. **IR lint** (schema, syntax).

4. **Purity / side-effect** compliance.

5. **Namespace & semver** resolution.

6. **Optional dry-run** if `--dry`.

*Planner must exit `FAIL_VALIDATION` if any rule fails after retries.*

---

## 8 · Failure Modes & Codes

| Code | Description | Planner Output | 
|---|---|---|
| `MISSING_INPUT` | Required data value absent. | JSON diagnostic listing keys. | 
| `MISSING_CONFIG` | Node knob undefined & no default. | Node id + knob name. | 
| `FAIL_VALIDATION` | Draft pipe failed after retries. | Last validator error set. | 
| `AMBIGUOUS_MATCH` | Retrieval produced >1 candidate. | Ranked list of candidates. | 

CLI propagates codes; non-interactive runs terminate, interactive runs may re-prompt.

---

## 9 · Logging & Provenance

- **planner_log.json** per invocation:

   - prompt, retrieval hit/miss, chosen pipe, validator outcomes

   - planner flow version, LLM model id, temperature, retry count

- **Run-log** embeds pointer to planner_log for complete traceability.

- **Lock file** stores pipe/IR only—never planner internals.

---

## 10 · Trust Model

| Flow Origin | Trust Level | Cache Eligible | Notes | 
|---|---|---|---|
| Retrieved | `trusted` | Yes (if nodes `@flow_safe`) | Already validated earlier. | 
| Generated & validated | `trusted` | Yes | Planner guarantees structural validity. | 
| Human-edited after planner | `mixed` | No until re-validated by `pflow validate`. |  | 

---

## 11 · Metrics (MVP Targets)

| Metric | Target | 
|---|---|
| Retrieval hit-rate on repeated prompts | ≥ 90 % | 
| Planner generation passes full validation within 4 retries | ≥ 95 % | 
| Average planner latency (local LLM) | ≤ 800 ms | 
| Incidence of `MISSING_INPUT` in non-interactive CI runs | 0 | 

---

## 12 · Extensibility Hooks (vNext)

1. **Semantic Vector Index** for fuzzy retrieval across large flow sets.

2. **Constraint-driven generation** (LLM guided by purity & namespace constraints before emit).

3. **Parameter suggestion** by analysing run-log stats (e.g., temperature heuristics).

4. **Round-trip NL↔IR** for explainer UIs.

5. **Remote planner services**—but provenance still logged locally.

---

## 13 · Glossary

| Term | Definition | 
|---|---|
| **Pipe preview** | Shell-like flow string (`nodeA >> nodeB`) exposed to user. | 
| **Shared store** | Per-run key-value memory for node inputs/outputs. | 
| **Derived snapshot** | Run-time copy of IR with injected `config` overrides. | 
| **Planner log** | Artifact capturing every step the planner took. | 

---

### End of Spec