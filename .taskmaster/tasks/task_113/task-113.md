# Task 113: Add TypeScript Support to Code Node

## Description

Extend the code node (Task 104) to support TypeScript/JavaScript as an additional language option. TypeScript enables V8 isolate sandboxing - true isolation WITHOUT losing native objects, something Python fundamentally cannot do.

## Status

not started

## Priority

low

## Problem

Code node (Task 104) only supports Python. Users may need TypeScript for:
- Libraries only available in npm ecosystem
- Familiarity with JavaScript/TypeScript
- **Sandboxed execution with native objects** - V8 isolates can sandbox code while preserving native object passing, unlike Python which requires container serialization

Language choice should be driven by library availability and user preference, not by sandboxing constraints.

## Solution

Add `language` parameter to code node:

```json
{
  "type": "code",
  "params": {
    "language": "typescript",
    "inputs": {"data": "${upstream.result}"},
    "code": "const result = data.map(x => x.toUpperCase())"
  }
}
```

Same interface as Python mode:
- `inputs`: dict of variable names → template values
- `code`: inline code string
- `requires`: npm packages needed (optional)
- `result` variable captured as output

## Design Decisions

- **Same node, language parameter**: Not a separate `ts-code` node. Unified interface, implementation handles runtime differences internally.

- **V8 isolates for sandboxing**: TypeScript sandboxed mode uses V8 isolates (via `isolated-vm` or similar), NOT containers. This preserves native object passing while still being sandboxed.

- **Sandbox behavior differs by language**:
  - `language: python, sandbox: true` → Container (Task 87), loses native objects
  - `language: typescript, sandbox: true` → V8 isolate, keeps native objects
  - This difference should be clearly documented

- **Node.js dependency**: TypeScript support requires Node.js installed. Graceful error if unavailable.

## Dependencies

- **Task 104: Python Code Node** — Must be implemented first. TypeScript support extends the same node.
- **Task 87: Sandboxed Execution Runtime** — For understanding sandbox integration. TypeScript sandbox (V8 isolates) may be implemented here or in this task.

## Implementation Notes

### Execution Approaches

**Option 1: Subprocess to Node.js**
```python
# Simple but loses native objects (serialization)
subprocess.run(["node", "-e", code], input=json.dumps(inputs))
```

**Option 2: Embedded V8 (PyMiniRacer, py_mini_racer)**
```python
# In-process V8, potentially native objects
from py_mini_racer import MiniRacer
ctx = MiniRacer()
ctx.eval(code)
```

**Option 3: isolated-vm via Node subprocess**
```python
# Best sandboxing, but subprocess = serialization
# Unless we use some IPC optimization
```

Research needed at implementation time to determine best approach.

### Interface Parity

TypeScript mode should have identical interface to Python:
- `inputs` dict → variables in scope
- `result` variable → captured as output
- `requires` → npm packages
- `timeout` → execution timeout

### Task 107 Integration

Markdown format should support TypeScript:
```markdown
## transform
type: code
language: typescript

```typescript
const result = data.filter(x => x.active)
```
```

## Verification

**Functional tests:**
- Basic TypeScript execution with inputs/outputs
- Multiple inputs accessible as variables
- `result` variable captured correctly
- npm package imports work (if `requires` specified)

**Parity tests:**
- Same workflow logic produces same results in Python and TypeScript
- Error messages equally clear for both languages

**Sandbox tests (if implemented here):**
- V8 isolate prevents filesystem access
- V8 isolate prevents network access
- Native objects preserved through sandbox (unlike Python)

## Open Questions

1. **Embedded V8 vs subprocess**: Trade-off between native objects (embedded) and simplicity (subprocess). Research needed.

2. **Where does V8 sandbox live**: In this task? Or as part of Task 87's scope? Task 87 currently focuses on container sandboxing.

3. **npm package installation**: How does `requires: ["lodash"]` work? Pre-installed? Install at runtime? Container with deps?

4. **Deno as alternative**: Deno has built-in security model (permissions). Could be simpler than Node.js + isolated-vm. Worth evaluating.

## References

- Task 104 braindump: `.taskmaster/tasks/task_104/starting-context/braindump-sandbox-decision-reversal.md`
- Task 87 braindump: `.taskmaster/tasks/task_87/starting-context/braindump-sandbox-architecture-context.md`
- V8 isolates: https://github.com/nicolo-ribaudo/isolated-vm
- PyMiniRacer: https://github.com/nicolo-ribaudo/PyMiniRacer
- Deno permissions: https://deno.land/manual/basics/permissions
