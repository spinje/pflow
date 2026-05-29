# Sub-Workflows

**Use when**: Reusable sub-tasks across workflows, or decomposing complex workflows — "reuse this", "same validation as X".

- Child inputs are passed via the top-level `inputs:` dict on the workflow node
- Child workflow must declare `## Inputs` (for required params) and `## Outputs` (for exposed results)
- `workflow:` accepts a file path (`./child.pflow.md`), a saved workflow name (`my-saved-workflow`), or a template that resolves to one at runtime (see Dynamic Child Selection below)
- Nesting depth limited to 10 levels (configurable via `max_depth` param)
- Parent→child boundary is strict — every key in `inputs:` must be declared on the child's `## Inputs`; typos are rejected at parse time

### When to Use Sub-Workflows

- Common sub-tasks are reused across multiple parent workflows
- A complex workflow benefits from decomposition into self-contained phases
- A sub-task needs to be executable both standalone AND as part of a parent
- You want to test sub-workflows independently but run them together as a unit

**Example**: "Fetch data, validate it (reusable), transform it, validate output (same validation reused)"
→ Validation is a NESTED `workflow` node, called twice in the parent

### Pattern: Sub-Workflow Composition

**Child workflow** (`to-uppercase.pflow.md`):
````markdown
# To Uppercase

Convert text to uppercase.

## Inputs

### text

The text to convert.

- type: string

## Outputs

### result

The uppercased text.

- source: ${transform.stdout}

## Steps

### transform

Uppercase via `tr`.

- type: shell
- command: echo "${text}" | tr '[:lower:]' '[:upper:]'
````

**Parent workflow** calling the child:
````markdown
## Steps

### process_title

Convert the title to uppercase using the shared sub-workflow.

- type: workflow
- workflow: ./to-uppercase.pflow.md
- inputs:
    text: ${title}

### process_body

Convert the body to uppercase using the shared sub-workflow.

- type: workflow
- workflow: ./to-uppercase.pflow.md
- inputs:
    text: ${body}

### combine

Combine the processed title and body into a single output.

- type: shell
- command: printf "Title: %s\nBody: %s" "${process_title.result}" "${process_body.result}"
````

### Dynamic Child Selection (Template References)

`workflow:` can be a template (`${var}`) that resolves at runtime — from CLI input, an upstream node's output, or a batch item field. The child is loaded and validated when the parent node executes, not at parent-parse time.

**Use when**: the same parent node needs to dispatch to different children per batch item or per run.

**Example** — fan out over three review aspects, each specifying which child workflow to run:

`````markdown
### reviews

Review the combined analysis from three critical perspectives. Each batch item picks which child workflow to run.

- type: workflow
- workflow: ${item.workflow}
- inputs:
    summary: ${combine.result}
    aspect: ${item.aspect}

```yaml batch
items:
  - aspect: accuracy
    workflow: ./review-aspect.pflow.md
  - aspect: completeness
    workflow: ./review-aspect.pflow.md
  - aspect: clarity
    workflow: ./review-aspect.pflow.md
parallel: true
```
`````

**Trade-off**: invalid children surface as runtime compile errors, not at `--validate-only`. Prefer the static-path form when the child is known at authoring time; reserve the template form for genuine runtime dispatch.

### Pattern: Heterogeneous Batch over Sub-Workflows

Parallel fan-out over N *different* child workflows, each with its own inputs.
Per-item `inputs: ${item.inputs}` lets each child receive exactly the values it declares.

````markdown
### reviews

Parallel review fan-out — each item names a different child and supplies
that child's exact inputs.

- type: workflow
- workflow: ${item.workflow}
- inputs: ${item.inputs}

```yaml batch
items:
  - workflow: ./reviews/review-narrative.pflow.md
    inputs:
      lyrics: ${write-lyrics.response}
      song_architecture: ${song-architecture.response}
  - workflow: ./reviews/review-imagery.pflow.md
    inputs:
      lyrics: ${write-lyrics.response}
      creative_direction: ${creative-direction.response}
  - workflow: ./reviews/review-emotional.pflow.md
    inputs:
      lyrics: ${write-lyrics.response}
      concept_brief: ${concept_brief}
parallel: true
```
````

Each child declares only the inputs it uses; nothing is "extra" from any
child's perspective. Reading one item tells you exactly what that child
receives. Typos in any item's `inputs:` fail at parse time with a fuzzy
suggestion — there's no silent drop.

### Pattern: Bounded iteration via batch

To run the same sub-workflow N times *in order*, batch it with a static index
list and `parallel: false`. Each iteration runs to completion before the next
starts — so an iteration can read filesystem (or other external) state that the
previous one mutated. This is the cleanest way to express a bounded loop where
state lives on disk.

**Child workflow** (`process-one.pflow.md`) — reads a queue file, takes the first
item, writes the rest back:
````markdown
# Process One

## Inputs

### iteration

The current iteration index.

- type: integer

## Steps

### read-queue

Read the current queue from disk.

- type: shell

```shell command
cat queue.txt
```

### take-and-write

Take the first item, log it, write the remainder back.

- type: shell
- inputs:
    raw: ${read-queue.stdout}
    iteration: ${iteration}

```shell command
printf '%s\n' "${raw}" | head -n 1 >> log.txt
printf '%s\n' "${raw}" | tail -n +2 > queue.txt
```
````

**Parent** — drive it five times, sequentially:
````markdown
### iterate

- type: workflow
- workflow: ./process-one.pflow.md
- inputs:
    iteration: ${item}
- batch:
    items: [1, 2, 3, 4, 5]
    parallel: false
````

Notes:
- `${item}` supplies the per-item value to any param of the sub-workflow invocation (here, the iteration index).
- The sub-workflow's working directory is shared with the parent by default. There is no per-item filesystem isolation — do NOT pass `cwd: ${item.workdir}`; `cwd` is not an accepted `workflow`-node param and will be rejected as an unknown field.
- **Cache correctness:** this works without any `cache: false` annotations because non-`llm` nodes don't cache by default — `read-queue` re-runs each iteration and sees the current file. See `pflow guide core` → cache for what gets cached and why this works without annotations.

Choose this over the in-store loop (`pflow guide branching` → Loops) when iteration state passes through the filesystem or each iteration is a substantial unit of work.

