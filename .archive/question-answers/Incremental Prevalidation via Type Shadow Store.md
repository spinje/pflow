---
tags:
  - ai-source
Source: https://chatgpt.com/g/g-p-683614bc126881919261d9cf02499ad4-pflow/c/68361c3a-2988-8009-aa9d-ed61a639547e?model=gpt-4o
---
# Incremental Prevalidation via Type Shadow Store

---

#### **Purpose**

To provide real-time, type-aware feedback during interactive flow composition—**before** the full IR is compiled or the LLM is invoked—by simulating a best-effort understanding of available data types via a *type shadow store*.

---

#### **Problem Addressed**

In pflow, nodes interact through a global shared store rather than direct chaining.\
However, during **pipe-syntax composition**, users (or planners) write flows linearly:

```bash
transcribe --url X >> summarize >> plot-chart

```

But:

- Inputs may come from any previous node, not just the last one.

- Final input/output **keys and wiring** are assigned by a later IR compilation step.

- Users need **early feedback** to avoid invalid compositions, discover compatible nodes, and reduce planner retries.

---

#### **Solution: The Type Shadow Store**

During composition:

1. pflow maintains an in-memory **type shadow store** tracking all available **types**, not keys.

2. Every node’s declared `produces` values (from the registry) are merged into the store by type.

3. Each candidate node’s `requires` types are checked against the current set.

If a node requires a type not yet produced by any prior node, it is flagged or excluded from autocomplete.

---

#### **Behavioral Flow**

```bash
yt-transcript         # produces transcript:text
>> summarize          # requires transcript:text → valid
>> write-csv          # requires dataframe → invalid here

```

At each step:

- The store accumulates available types (not keys).

- Autocomplete suggestions only include valid consumers of currently available types.

- Obvious incompatibilities are surfaced immediately.

---

#### **Implementation Requirements**

- Use the existing **node registry schema**:

```json
{
  "requires": {
    "transcript": { "type": "text" }
  },
  "produces": {
    "summary": { "type": "text" }
  },
  "side_effects": ["network.write"]
}

```

- Maintain a **set of known available types** (e.g., `{ "text", "url", "dataframe" }`).

- Evaluate each candidate node's `requires.*.type ⊆ available_types`.

No key matching, shared-store mapping, or LLM reasoning is needed at this stage.

---

#### **Limitations**

- Cannot detect:

   - Key mismatches (e.g., `summary` vs `text`)

   - Param-based key variations (e.g., `"summary_${lang}"`)

   - Shared-store collisions or overwrites

   - Purity or side-effect violations

   - Branching logic or conditional paths

These are deferred to the full IR compilation and validation phases.

---

#### **Lifecycle Note**

The type shadow store is ephemeral and advisory:

> It is discarded once the pipe compiles to IR.\
> The compiled IR owns the definitive key-type map and governs runtime behavior.

---

#### **Position in Architecture**

| Layer | Role |
|---|---|
| Type Shadow Store | Realtime assist; type-only checks |
| Pipe-to-IR Compiler | Generates full key wiring, param mapping |
| Lint & Execution Validator | Validates semantics, purity, and structure |

---

#### **Value Delivered**

- **Autocomplete filtering** of valid nodes at each step

- **Immediate error feedback** during interactive CLI or planner composition

- **Reduces planner retries** due to trivial flow failures

- **Preserves single source of truth** — same type contract metadata used at all layers

- **Zero LLM overhead** until IR compile time

---

#### **Strategic Fit in pflow**

This approach aligns tightly with pflow’s architectural goals:

- Explicit over implicit

- Fast feedback, slow commitment

- Layered validation

- NL or CLI input with the same deterministic guarantees

It’s a lightweight, high-leverage component that improves UX, planner efficiency, and correctness—all without compromising deterministic flow generation or execution.

But its value collapses the moment we treat it as a source of truth, rather than a partial hinting system.

> Use it for what it is. Don’t overextend it. Then it’s not just robust—it’s essential.
