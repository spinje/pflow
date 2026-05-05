# Cross-Workflow Cache Test (parent)

Parent declares `## Cache` with `${shared_doc}`. Calls `child.pflow.md` as
a sub-workflow, passing `${shared_doc}` through. Both parent and child
make LLM calls referencing the same value. Test: does the cache cross
the sub-workflow boundary, sharing bytes across both calls?

## Inputs

### shared_doc

The shared reference document — used by both parent and child LLM calls.

- type: string
- required: true

## Cache

- ttl: 5m

```cache
The reference document, shared across the workflow:

${shared_doc}
```

## Steps

### parent-call

LLM call in the parent workflow, references shared cache.

- type: llm
- model: gemini/gemini-2.5-flash
- prompt_cache: [shared_doc]
- max_tokens: 80

```prompt
Question: What is the magic value of a MERIDIAN frame?

Answer in one sentence.
```

### child-step

Sub-workflow call. Passes the same `${shared_doc}` to child.

- type: workflow
- workflow: ./child.pflow.md
- inputs:
    shared_doc: ${shared_doc}

## Outputs

### parent_answer
source: parent-call.response

### child_answer
source: child-step.child_answer
