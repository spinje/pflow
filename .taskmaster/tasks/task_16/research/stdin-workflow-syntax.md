# Plain Text Workflow Syntax via stdin

**Date**: 2024-12-19
**Context**: Investigation during Task 8.2 validation
**Author**: Claude (during dual-mode stdin validation)

## Background

During validation of the dual-mode stdin implementation (Task 8.2), a question arose about whether pflow should support piping plain text workflow syntax through stdin. This document captures the current state and considerations for future implementation.

## Current Limitation

The pflow CLI currently does NOT support piping plain text workflow syntax through stdin.

### What Doesn't Work
```bash
# This raises an error:
echo "node1 => node2" | pflow
# Error: "Stdin contains data but no workflow specified"

# This also fails:
echo "read-file => transform => write-file" | pflow
# Same error
```

### Why It Doesn't Work

1. The `determine_stdin_mode()` function only recognizes stdin as "workflow" if it contains valid JSON with an `ir_version` key
2. Any non-JSON content is categorized as "data"
3. When stdin contains "data" but no workflow is specified (via --file or args), the CLI raises an error

### Current Workarounds

Users must provide plain text workflow syntax as command arguments:
```bash
# This works:
pflow node1 => node2

# This also works:
pflow "read-file => transform => write-file"
```

## Design Considerations

### Should This Be Supported?

**Pros:**
- Unix philosophy: tools should accept input via stdin
- Enables workflow generation by other tools: `generate-workflow | pflow`
- Consistent with how other CLI tools work

**Cons:**
- Ambiguity: How to distinguish workflow syntax from actual data?
- Command args already work fine for this use case
- May complicate the dual-mode stdin logic

### Possible Solutions (If Needed)

1. **Smart Detection**: Enhance `determine_stdin_mode()` to recognize CLI syntax patterns (presence of `=>`, node names, etc.)

2. **Explicit Flag**: Add `--stdin-is-workflow` flag to force interpretation
   ```bash
   echo "node1 => node2" | pflow --stdin-is-workflow
   ```

3. **Planner Integration**: Let the natural language planner handle all non-JSON stdin as potential workflow descriptions

## Recommendation

**Wait and see.** This capability is not critical for MVP. The natural language planner (Task 17) will need to handle various input formats anyway, so this could be addressed as part of that implementation.

The current approach (JSON workflows via stdin, plain text via args) is sufficient for now.
