# Braindump: Task 125 — Human-in-the-Loop Approval Gates

Context: Extended conversation where the user (who is Andreas Falcone, the sole developer of pflow) posed as a stranger evaluating the repo, pushed for honest assessment, explored OpenClaw integration deeply, received strategic advice, then created this task.

## Where I Am

Task 125 file is written. No implementation started. This braindump captures everything from the conversation that shaped the task and the strategic context around it.

## User's Mental Model

**The user values brutal honesty above all else.** They opened by pretending to be an outsider evaluating pflow, explicitly pushed back on marketing language ("but the marketing aside. I need to know if this is really usable and for what. I dont need you to repeat what allready in there"), and only revealed they were the developer after getting several rounds of unfiltered assessment. They want collaborators who tell them hard truths, not cheerleaders.

**Their strongest insight came from them, not the docs.** When discussing OpenClaw, they said: "couldnt the agent identify itself when its doing small automations that it will probably be using again, for example doing a step of 3-5 or more steps in sequence that will always be that that sequence but with different parameters. Shouldnt that happen all the time or?" This framing — agents self-identifying repeated sequences in real-time — is more compelling than anything in pflow's current marketing. It's the "aha moment" description that the README doesn't have yet.

## Key Insights

### The OpenClaw research changed the picture multiple times

1. **First assessment (wrong):** "Lobster already solves this, skip pflow for OpenClaw." Based on surface-level understanding.
2. **Second assessment (better):** After deep research, Lobster turned out to be 25 days old with no lifecycle, no MCP, no agent-authored workflows. pflow fills a real gap.
3. **Third assessment (after verification):** Several claims I made were wrong. Corrected picture is more nuanced. See verification section below.
4. **Final strategic advice:** Don't bet on OpenClaw specifically, but build HITL and HTTP MCP because they're right regardless of platform.

### Verification caught real errors

These corrections matter because the task file was written with corrected understanding, but the next agent should know what was wrong and why:

- **"Python is first-class in OpenClaw"** — OVERSTATED. `uv` is listed as a valid installer kind but has zero documented examples. Python skills exist but are a small minority. Official OpenClaw install docs list only Node.js.
- **"Lobster has no workflow lifecycle"** — OVERSTATED. Lobster does have save/resume with persistent state and cross-session resume tokens. What it lacks is discovery, registry, metadata indexing. The task file references Lobster's resume tokens — that reference is accurate.
- **"The 2.4s MCPorter cold-start"** — UNVERIFIABLE. This number appeared in earlier research but doesn't exist in the OpenClaw repo or docs. Don't cite it.
- **"70 concurrent LLM calls"** — The batch infrastructure exists and `max_concurrent` is configurable, but defaults to 5. "70" is what the README author (i.e., this user) claims to use for their changelog workflow. It's a real configuration, not a tested benchmark.
- **Lobster has NO MCP support** — TRUE. Confirmed. Zero MCP references in codebase. Issue #4834 (requesting MCP for OpenClaw/Clawdbot, not Lobster specifically) was closed as "not planned."

### The strategic advice I gave

I recommended:
1. Don't bet heavily on OpenClaw — platform risk, audience mismatch, fragile integration surface
2. Build HITL because it's right for pflow regardless of platform
3. Build HTTP MCP transport (Task 90) because it makes pflow callable from any agent
4. Un-gate the NL planner or remove it — disabled features signal "not ready"
5. The user's own framing ("agents self-identifying repeated sequences") is stronger than the current README pitch

The user didn't push back on any of this. They moved straight to creating the task, which suggests alignment.

## Assumptions & Uncertainties

ASSUMPTION: The wrapper chain described in `architecture.md` (InstrumentedWrapper → BatchWrapper → NamespacedWrapper → TemplateAwareWrapper → ActualNode) is the current implementation. I haven't read the actual source code — only the docs in this repo. The next agent implementing this MUST verify the wrapper chain in the actual codebase before designing the ApprovalWrapper placement.

ASSUMPTION: The shared store is a simple Python dict that can be serialized to JSON. The task file assumes this for state persistence. Verify — if the shared store contains non-serializable objects (functions, file handles, etc.), the serialization approach needs rethinking.

ASSUMPTION: Template resolution happens in `TemplateAwareWrapper` and produces resolved values before node execution. The task says "show resolved inputs at approval time." If template resolution and node execution are more interleaved than I think, the preview mechanism needs adjustment.

UNCLEAR: How does the compiler (`runtime/compiler.py`) currently handle node parameters? Does `approval: required` need to be added to the IR schema, or can it pass through as a generic parameter? If pflow validates against a strict schema, adding `approval` might require schema changes.

UNCLEAR: How does the `--output-format json` flag interact with approval pauses? If a calling process expects clean JSON output and gets an approval prompt instead, that breaks the contract. The non-TTY mode needs to emit structured JSON with a clear `"status": "paused"` envelope.

NEEDS VERIFICATION: The task file says "no dependencies." But if Task 90 (HTTP MCP transport) is also being worked on, there might be coordination needed — the approval/resume protocol should work over HTTP MCP too, not just CLI. Check if Task 90 exists and what its status is.

## Unexplored Territory

UNEXPLORED: **Security of resume tokens.** The task says tokens are "self-contained" and reference state in `~/.pflow/resume/`. If tokens contain workflow identity and can trigger execution, they're an attack surface. Can someone craft a malicious token? Should tokens be signed/encrypted? Lobster uses encrypted payloads — pflow should consider this.

UNEXPLORED: **How approval interacts with the `claude-code` node type.** The `claude-code` node delegates to another agent. If that sub-agent's workflow also has approval gates, you get nested pauses. Is that handled? Does the outer workflow block until the inner one completes (including its own approval cycle)?

UNEXPLORED: **How approval interacts with sub-workflows (`type: workflow`).** Same nesting question. If a sub-workflow has approval gates, the parent workflow needs to know it's paused, not failed.

CONSIDER: **Approval as a first step toward "dry run" mode.** If you can pause before every action and show what's about to happen, you're close to `pflow --dry-run` which previews the entire workflow without executing anything. This might be more immediately useful than selective approval gates and could be built on the same infrastructure.

CONSIDER: **Approval in the context of `pflow skill save`.** If a workflow is published as a Skill and another agent runs it, does the approval gate still work? Skills might run in contexts where interactive TTY isn't available. The non-interactive token mode becomes critical here.

MIGHT MATTER: **Approval UX in OpenClaw context.** If pflow is called via `exec` from OpenClaw, the approval prompt goes to... nowhere (it's a subprocess). The non-interactive token mode would need to emit the token to stdout, and an OpenClaw skill would need to parse it and present the approval to the user via chat. This isn't in scope for task 125 but it's the integration point if OpenClaw is ever pursued.

MIGHT MATTER: **Resume token cleanup.** The task mentions configurable TTL but doesn't specify a default. Stale resume state in `~/.pflow/resume/` will accumulate. Need a cleanup strategy — either auto-expire after N days, or `pflow resume clean` command, or both.

MIGHT MATTER: **Approval and the `--output-format json` flag.** pflow supports JSON output for programmatic consumption. When a workflow pauses for approval, the JSON output needs to clearly signal the pause state, include the resume token, and include the preview of what's about to happen — all in a structured format a calling process can parse.

## What I'd Tell Myself

1. **Read the actual source code, not just these docs.** These markdown files are internal strategy/planning documents. Several claims in them don't match the shipped product (e.g., "experimental" MCP server). The real truth is in `src/pflow/`.

2. **The user's own framing is gold.** "agents self-identifying repeated sequences" — this is the one-liner that should be in the README. Remember it.

3. **Don't over-engineer the resume token.** Lobster's approach (compact encoded token with protocol version) is good reference but Lobster is 25 days old — their design isn't battle-tested either. Start simple: JSON file in `~/.pflow/resume/`, UUID-based token that references it. Encrypt/sign later if needed.

4. **The wrapper chain placement is the key design decision.** Where ApprovalWrapper sits relative to TemplateAwareWrapper determines whether you can show resolved values in the preview. Get this right first, everything else follows.

5. **Test the non-TTY path first, not the interactive path.** The non-TTY token-based flow is harder and more important — it's what makes approval work in automated contexts (CI, OpenClaw, Skills). The interactive TTY prompt is the easy case.

## Open Threads

- The user might want to revisit the OpenClaw integration later if pflow gains traction. The research is extensive and captured here. Don't redo it.
- The "agents self-identifying repeated sequences" concept wasn't turned into a concrete feature or task. It's a UX/instruction-layer idea — teaching the agent to recognize when it should save a workflow. Could be a skill/instruction rather than a pflow code feature.
- The NL planner and self-healing features are both gated by "Task 107" (markdown format migration). Unclear if Task 107 is complete — the markdown format exists and works, but these features are still gated. The user might want to un-gate them as a separate priority.

## Relevant Files & References

**External (from research, not local):**
- Lobster approval gates: `src/commands/stdlib/approve.ts` in `github.com/openclaw/lobster`
- Lobster resume tokens: `src/resume.ts` in `github.com/openclaw/lobster`
- Lobster state persistence: `src/commands/stdlib/state.ts` in `github.com/openclaw/lobster`
- pflow source: `github.com/spinje/pflow` — actual implementation, not these strategy docs
- pflow MCP node: `src/pflow/nodes/mcp/node.py` — confirmed generic, calls any configured server
- pflow batch node: `src/pflow/runtime/batch_node.py` — ThreadPoolExecutor, configurable max_concurrent
- pflow CLI gating: `src/pflow/cli/main.py` lines 3043-3050 (auto-repair) and 3967-3975 (NL planner)

## For the Next Agent

**Start by:** Reading the actual pflow source code in the real repo (not the docs in `/Users/andfal/projects/temp/`). Specifically: the wrapper chain in `src/pflow/runtime/`, how compilation works in `runtime/compiler.py`, and how the shared store is structured. The task file's wrapper placement proposal needs to be validated against real code.

**Don't bother with:** Re-researching OpenClaw. That analysis is thorough and verified. The strategic decision (don't bet on OpenClaw, build HITL for pflow's own sake) has been made.

**The user cares most about:** Honesty, practical utility, and getting to something shippable. They don't want over-engineering. They want approval gates that work, are simple, and make pflow trustworthy for real-world actions. Start with the non-TTY token path — it's harder and more important.

**Tone note:** This user will push back if you repeat their own docs at them or give marketing-flavored answers. Be direct. Say what's hard. Say what you don't know.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
