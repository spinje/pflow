# Braindump: Task 109 Context from Task 104 Discussion

## Where I Am

Task 109's original framing assumes "sandbox on by default." Our Task 104 discussion revealed a different reality that affects this task's scope.

## Key Context Change

**Original Task 109 framing:**
- Sandbox is ON by default
- Problem: How do we control bypass (`sandbox: false`)?

**Actual situation after Task 104 decisions:**
- Script node is UNSANDBOXED by default (for MVP)
- Shell node currently has no sandbox either
- Task 87 will add OPTIONAL sandboxing to both
- The default is unsandboxed, not sandboxed

This flips the question: instead of "how to bypass sandbox," it becomes "when to REQUIRE sandbox."

## Revised Problem Statement

The real security concern isn't "AI generates `sandbox: false`" — it's:
- **MCP server context**: Untrusted callers can trigger workflow execution
- **Shared workflows**: Downloaded workflows might be malicious
- **AI-generated workflows**: Agent might generate dangerous commands

For local CLI use with self-authored workflows, unsandboxed is fine (user trusts their own code).

## How This Changes the Options

**Option A (sandbox not in IR)**: Still valid, but inverted — sandbox is ENVIRONMENT config, not workflow param. MCP server forces sandbox; CLI allows unsandboxed.

**Option B (separate node types)**: Less relevant now. The distinction is context-based (trusted vs untrusted caller), not node-based.

**Option C (allow-list)**: Inverted — instead of "allow-list for bypass," it's "require-list for unsandboxed." Workflows from MCP must be sandboxed unless explicitly trusted.

## Suggested Reframe

Task 109 should probably become: **"Sandbox Policy by Execution Context"**

| Context | Default | Can Override? |
|---------|---------|---------------|
| CLI (local user) | Unsandboxed | User can force sandbox |
| MCP server | Sandboxed | Only with explicit allow-list |
| Saved workflows | Depends on source | Trusted sources = unsandboxed |

## User's Mental Model

From the conversation:
- "shell node will have its own sandbox later"
- "we need a way for users to do anything" (for MVP)
- Implicit: security is about CONTEXT (who's calling), not WORKFLOW (what it says)

## Open Questions

**UNCLEAR**: Does Task 109 still make sense as originally scoped, or should it be rewritten after Task 87 is implemented?

**CONSIDER**: Maybe Task 109 becomes trivial — if sandbox is opt-in via Task 87, and MCP server just always enables it, there's no "bypass" to control. The policy is: MCP = sandboxed, CLI = user's choice.

**MIGHT MATTER**: The `sandbox: true/false` parameter in workflow IR might not be needed at all. Sandboxing could be purely a runtime/environment decision.

## For the Next Agent

**Don't implement yet** — Task 109 depends on Task 87's design decisions. Once Task 87 is done, revisit whether Task 109 is still needed or should be rescoped.

**Key insight**: The threat model is about CALLER TRUST, not workflow content. An unsandboxed workflow from a trusted user (CLI) is fine. A sandboxed workflow from untrusted caller (MCP) is the concern.

---

**Note to next agent**: This braindump captures context from a Task 104 conversation that affects Task 109's scope. The original task spec may need revision once Task 87 is complete. When ready, confirm you've understood the context shift before proceeding.
