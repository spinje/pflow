# Insight: run-step Should Be Part of Task 106

**Source**: Hands-on experience rewriting the generate-changelog workflow (Feb 2026)

## Context

While converting the 17-node generate-changelog workflow from shell/jq to Python code nodes, we identified that `run-step` (running a single workflow step in isolation) complements the iteration cache and should ship together.

The workflow has nodes like `get-commits-enriched` (65 lines of Python with subprocess calls to git/gh), `filter-and-format`, `prepare-context`, etc. During development of these nodes, the iteration loop is:

1. Edit a code node in the `.pflow.md` file
2. Run the full workflow to test it
3. Wait for all upstream nodes to complete before reaching the changed node
4. See if it works, go back to step 1

The iteration cache (Task 106's core feature) solves step 3 by caching completed upstream nodes. But there's a complementary use case the cache alone doesn't cover well:

## The run-step Use Case

```bash
# Extract and run a single step from a workflow file
pflow run-step workflow.pflow.md get-commits-enriched tag=v0.7.0
```

**When this is needed (and caching isn't enough):**

1. **First iteration on a new node** — no cache exists yet, but you want to test just the node you're writing before running the full pipeline
2. **Testing with different inputs** — you want to try `get-commits-enriched` with `tag=v0.5.0` and `tag=v0.6.0` without re-running the full workflow each time
3. **Developing a node in isolation before wiring it in** — write the code, test it standalone, then connect it to the data flow
4. **Rapid inner-loop iteration** — even cache lookup has overhead; for a tight edit-test cycle on one node, direct execution is faster

## Why It Belongs in Task 106 (Not a Separate Task)

1. **Shared infrastructure**: Both features need workflow parsing, node extraction, and isolated node execution. The cache's `compute_node_hash()` and node config extraction are exactly what `run-step` needs.
2. **Complementary UX**: Cache handles "re-run the workflow efficiently" while run-step handles "test this one node right now". Together they cover the full development loop.
3. **Small incremental effort**: Once the cache infrastructure exists (workflow parsing, node isolation, output capture), run-step is mostly CLI wiring — extract node config, resolve user-provided params into the inputs dict, call the existing `registry_run` execution path.

## Proposed UX

```bash
# Run a step, providing its template inputs manually
pflow run-step workflow.pflow.md get-commits-enriched tag=v0.7.0

# The command:
# 1. Parses the workflow file
# 2. Finds the step by name
# 3. Extracts its type, params, code block, etc.
# 4. Maps CLI args to the node's template inputs
#    (e.g., tag=v0.7.0 satisfies the ${resolve-tag.result} input)
# 5. Executes the node in isolation
# 6. Shows output using the existing registry-run display (template paths, structure)
```

**Input resolution**: The node's `inputs` dict has template references like `{tag: ${resolve-tag.result}}`. The `run-step` command maps CLI args by the input variable name (not the template source), so `tag=v0.7.0` satisfies the `tag` input regardless of where it normally comes from.

## What to Move from "Future Enhancements"

The task spec currently lists this under "Future Enhancements (Out of Scope)":

> **Run single node in isolation** — `pflow workflow.json --run-node=node_3` with optional mocked inputs

This should move into the main scope as a second deliverable alongside the iteration cache. The suggested CLI form `pflow run-step <file> <step-name> [params...]` fits better than `--run-node` flag since it's a distinct operation from running the workflow.
