# Inconsistencies Analysis: pflow Design Documents

## Overview

This document identifies inconsistencies between two key pflow design documents:
1. "Shared Store + Params Design Pattern in pflow.md" (referred to as **Design Pattern**)
2. "Shared-Store & Parameter Model — Canonical Spec.md" (referred to as **Canonical Spec**)

---

## 1. Parameter Terminology and Structure

### Inconsistency
The documents use fundamentally different terminology for the same concepts:

**Design Pattern** uses:
- `params: Dict[str, Any]` - a single, flat dictionary containing keys like `input_key`, `output_key`

**Canonical Spec** uses:
- `input_bindings` - maps CLI names to shared store keys
- `output_bindings` - maps node outputs to store keys
- `config` - literal per-node tunables

### Impact
This creates confusion about the actual node interface. Are parameters structured as three separate dictionaries or one unified dictionary?

---

## 2. Node Method Interface

### Inconsistency
The documents describe different node execution models:

**Design Pattern** shows:
```python
class Summarize(Node):
    def prep(self, shared):
        key = self.params["input_key"]
        return shared[key]

    def exec(self, text):
        return call_llm(text)

    def post(self, shared, _, summary):
        key = self.params["output_key"]
        shared[key] = summary
```

**Canonical Spec** implies a different structure focused on bindings rather than explicit `prep()`/`exec()`/`post()` methods.

### Impact
Unclear what the actual node implementation pattern should be.

---

## 3. JSON IR Structure

### Inconsistency
The intermediate representation formats differ significantly:

**Design Pattern** example:
```json
{
  "nodes": [
    {"id": "a", "type": "Summarize", "params": {"input_key": "raw_texts/doc1.txt", "output_key": "summaries/doc1.txt"}},
    {"id": "b", "type": "Store"}
  ],
  "edges": [
    {"from": "a", "to": "b"}
  ]
}
```

**Canonical Spec** example:
```json
{
  "nodes": [
    {
      "id": "fetch",
      "name": "yt-transcript",
      "input_bindings": { "url": "video_url" },
      "output_bindings": { "transcript": "raw_transcript" },
      "config": { "language": "en" }
    }
  ]
}
```

### Impact
- Different field names (`type` vs `name`)
- Different parameter structure (`params` vs separate binding objects)
- Different edge representation (explicit `edges` array vs implicit through bindings)

---

## 4. Parameter Mutability

### Inconsistency
The documents contradict each other on parameter mutability:

**Design Pattern** states:
- "It [params] does not mutate across the flow"
- "they are node-local and immutable per invocation"

**Canonical Spec** states:
- "`config` always overrideable" (Validation rule #4)
- "Can change per run" for config values

### Impact
Unclear whether node configuration can be modified at runtime or not.

---

## 5. CLI Integration Coverage

### Inconsistency
**Design Pattern** barely mentions CLI interaction, focusing on the programming model.

**Canonical Spec** is heavily CLI-focused with detailed resolution algorithms and CLI scenarios.

### Impact
Missing integration between the programming model and CLI interface. How do CLI flags map to the `params` structure described in the Design Pattern?

---

## 6. Shared Store Access Patterns

### Inconsistency
**Design Pattern** shows direct shared store manipulation:
```python
def prep(self, shared):
    key = self.params["input_key"]
    return shared[key]
```

**Canonical Spec** implies a more structured binding system where the engine handles store access rather than nodes directly accessing it.

### Impact
Unclear whether nodes directly access the shared store or if there's an abstraction layer.

---

## 7. Key Naming Conventions

### Inconsistency
**Design Pattern** uses path-like keys:
- `"raw_texts/doc1.txt"`
- `"summaries/doc1.txt"`

**Canonical Spec** uses simple identifiers:
- `"video_url"`
- `"raw_transcript"`
- `"article_summary"`

### Impact
No clear guidance on shared store key naming conventions.

---

## 8. Flow Definition vs Execution

### Inconsistency
**Design Pattern** focuses on how flows are structured and nodes are written.

**Canonical Spec** focuses on how flows are executed and how CLI arguments are resolved.

### Impact
The gap between flow definition (what developers write) and flow execution (what users invoke) is not clearly bridged.

---

## Recommendations

1. **Unify terminology** - Choose either the `params` model or the `input_bindings`/`output_bindings`/`config` model consistently across both documents.

2. **Clarify node interface** - Specify whether nodes use `prep()`/`exec()`/`post()` methods or a different pattern.

3. **Standardize IR format** - Ensure both documents use the same JSON structure and field names.

4. **Define mutability rules** - Clarify what can and cannot be modified at runtime.

5. **Bridge definition and execution** - Show how the programming model maps to CLI usage.

6. **Establish naming conventions** - Provide clear guidelines for shared store key naming.

7. **Create integration examples** - Show end-to-end examples that demonstrate both the programming model and CLI usage together.

## Path forward

1. **Unify terminology**: The `input_bindings`/`output_bindings`/`config` is the correct model to use.

2. **Unify the node interface**: The `prep()`, `exec()`, `post()` methods are correct and should be used. But using "binding" terminology is also accurate. The difference here is how the bindings are being used after the python code has been generated from the IR.
What to understand here is that:

- `input_bindings` and `output_bindings` handle routing
- `shared store` handles data
- `config` is node specific tunables that does not get written to the shared store

Make sure you think hard about this until you really understand how this works. you can read more about the `shared store` in the [communication](../pocketflow/docs/core_abstraction/communication.md) document but note that this document does not outline the Hybrid Power Pattern of dynamically changes the read and writes of the shared store based on injected parameters. This pattern in key to making nodes reusable within different flows, since the shared store layout for each flow will be different. A large part of why this pattern is important is because it allows for nodes furter down the chain to read from the shared store keys written by nodes further up the chain. (this way the input and output of the nodes are not hardcoded but dynamic based on the flow via the shared store).
It lets generic nodes cooperate without hard-coding a global schema, keeping reuse and introspection intact.
If this pattern was not used the input and output of nodes would always have to be synced with each other and this is not scalable.
Why not hard-code shared keys in nodes? It destroys modularity; a single schema change breaks every reuse.
Who defines the shared schema in flows? The planner acts as a “compiler,” selecting keys and binding params; humans don’t have to micromanage it.


3. **Standardize the IR format**: The IR format should be the same for both the Design Pattern and the Canonical Spec.
    - name is correct
    - remove params from the IR, use `input_bindings`/`output_bindings`/`config`
    - edges is present in the IR but it might not be relevant in this context

4. **Define mutability rules**: The `config` is mutable at runtime. config values are overrideable because they are isolated to the node (wont be written to the shared store).

5. **Bridge definition and execution**: The CLI integration is not relevant to the Design Pattern.

6. **Establish naming conventions**: using `raw_texts/doc1.txt` is just a way to show the path in the shared store (using subfolders). This will map to this structure in the final python code:

```python
shared = {
    "raw_texts": {
        "doc1.txt": "Some input",
    }
}
```

using subfolders in the shared store is just a way to express clear namespacing, scoping, avoiding collisions and easier debugging (but it is optional)

7. **Create integration examples**: Great suggetion. The integration examples should be shown in the Canonical Spec.
