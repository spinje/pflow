# Nested Workflow Examples

Nested workflows let you call other workflows as nodes. They use the same syntax as any other node — pass params, access outputs via `${node_id.output}`.

## Examples

### to-uppercase.pflow.md (child workflow)

A simple sub-workflow that converts text to uppercase. Declares `## Inputs` and `## Outputs` so parent workflows can pass data in and read results out.

### document-processor.pflow.md (parent workflow)

Calls `to-uppercase.pflow.md` twice — once for the title, once for the body — then combines the results.

## Running

```bash
# Run the parent workflow
pflow examples/nested/document-processor.pflow.md title="Hello World" body="some text"

# Validate without executing
pflow --validate-only examples/nested/document-processor.pflow.md
```

## How It Works

```markdown
### process_title
- type: workflow
- workflow: ./to-uppercase.pflow.md
- inputs:
    text: ${title}
```

- `type: workflow` tells pflow this is a nested workflow call
- `workflow:` points to the child workflow file (or a saved workflow name)
- Child inputs are passed via the `inputs:` dict — every key must be declared on the child's `## Inputs`
- Child outputs are available as `${process_title.result}` (via the namespace system)

## Storage Modes

- **mapped** (default): Child only sees params you pass. Safe and predictable.
- **shared**: Child reads/writes parent storage directly. Use with caution.
