# Sub-Workflows

**Use when**: Reusable sub-tasks across workflows, or decomposing complex workflows — "reuse this", "same validation as X".

- Same syntax as any other node — pass params as inputs, access outputs via `${node_id.output_name}`
- Child workflow must declare `## Inputs` (for required params) and `## Outputs` (for exposed results)
- `workflow:` accepts a file path (`./child.pflow.md`) or a saved workflow name (`my-saved-workflow`)
- Nesting depth limited to 10 levels (configurable via `max_depth` param)

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
- type: string

## Outputs

### result
- source: ${transform.stdout}

## Steps

### transform
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
- text: ${title}

### process_body

Convert the body to uppercase using the shared sub-workflow.

- type: workflow
- workflow: ./to-uppercase.pflow.md
- text: ${body}

### combine

Combine the processed title and body into a single output.

- type: shell
- command: printf "Title: %s\nBody: %s" "${process_title.result}" "${process_body.result}"
````

