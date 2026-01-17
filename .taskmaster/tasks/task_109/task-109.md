# Task 109: Sandbox Bypass Security Controls

## Description

Define security controls for workflows that disable sandbox execution on shell and python nodes. Prevent AI-generated workflows from gaining unsandboxed access without explicit user approval.

## Status
not started

## Priority

medium

## Problem

Once sandbox execution is in place (Task 87, Task 104), nodes will have a mechanism to disable the sandbox (e.g., `sandbox: false` parameter). This creates a security concern:

- AI agents generating workflows could include `sandbox: false`
- Users might not notice this parameter in complex workflows
- No audit trail of which workflows have elevated privileges
- The sandbox-on-by-default posture is undermined if bypass is trivial

The threat model: an AI (or malicious workflow source) tricks the system into running unsandboxed code without explicit user awareness.

## Solution

**Not yet decided.** Three options were discussed:

### Option A: Don't Expose Sandbox as IR Parameter

Make sandboxing a runtime/environment configuration, not a workflow parameter:
- Workflows are always sandboxed
- Escaping sandbox requires changing pflow settings, not workflow definitions
- AI agents simply cannot generate workflows that escape the sandbox

**Pros**: Simplest, eliminates the attack vector entirely
**Cons**: Less flexible for legitimate use cases that need per-workflow control

### Option B: Separate Node Types

Create distinct node types with different privilege levels:
```
shell          → sandboxed, always safe
shell-unsafe   → no sandbox, denied by default in settings

python         → sandboxed, always safe
python-unsafe  → no sandbox, denied by default in settings
```

Leverages existing node filtering system (Task 50) without new machinery.

**Pros**: Uses existing infrastructure, clear separation of concerns
**Cons**: Node proliferation, may be confusing

### Option C: Workflow-Level Allow-List

The original proposal:
- Sandbox on by default
- `sandbox: false` parameter available
- Workflows using `sandbox: false` must be on an explicit allow-list

**Pros**: Defense in depth, audit trail, per-workflow granularity
**Cons**: New machinery, multiple approval layers, potential user friction

## Design Decisions

None finalized. This task exists to evaluate options once sandbox infrastructure is in place.

Key questions to resolve:
- What's the actual frequency of legitimate sandbox bypass needs?
- Should this be workflow-level, node-level, or environment-level control?
- How does this interact with saved workflows vs. ad-hoc execution?

## Dependencies

- Task 87: Implement Sandbox Runtime for Shell Node — Sandbox must exist before controlling bypass
- Task 104: Implement Python Script Node — Python node with sandbox must exist

## Implementation Notes

Depends on chosen approach. Each option has different implementation scope:

- **Option A**: Modify node implementations, remove/hide sandbox parameter from IR schema
- **Option B**: Create new node types, update registry, configure default deny rules
- **Option C**: New allow-list storage (extend settings.json?), validation hook during execution

Consider how MCP server (Task 72) and AI agents interact with whatever solution is chosen — they're the primary vector for untrusted workflow generation.

## Verification

- Unsandboxed execution is blocked by default (regardless of approach)
- Legitimate sandbox bypass works with appropriate approval mechanism
- AI-generated workflows cannot bypass sandbox without user action
- Clear error messages when sandbox bypass is blocked
- Audit trail exists for workflows with elevated privileges (if Option C)
