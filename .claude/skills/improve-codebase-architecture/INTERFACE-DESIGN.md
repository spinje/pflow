# Interface Design

When the user wants to explore alternative interfaces for a chosen deepening candidate, use this parallel sub-agent pattern. Based on "Design It Twice" (Ousterhout) — your first idea is unlikely to be the best.

Uses the vocabulary in [LANGUAGE.md](LANGUAGE.md) — **module**, **interface**, **seam**, **adapter**, **leverage**.

## Process

### 1. Frame the problem space

Before spawning sub-agents, write a user-facing explanation of the problem space for the chosen candidate:

- The constraints any new interface would need to satisfy
- The dependencies it would rely on, and which category they fall into (see [DEEPENING.md](DEEPENING.md))
- A rough illustrative code sketch to ground the constraints — not a proposal, just a way to make the constraints concrete

Show this to the user, then immediately proceed to Step 2. The user reads and thinks while the sub-agents work in parallel.

### 2. Spawn sub-agents

Spawn as many subagents as needed (up to 8 total) using the runner's subagent tool. Launch only as many as the runner has child slots (Codex has four total slots, so an orchestrator can run at most three children at once), wait for that batch, then launch the remainder. Fork the current context rather than selecting a custom agent (`subagent_type` omitted in Claude; `fork_turns="all"` in Codex). Each must produce a **radically different** interface for the deepened module. Verify all assumptions and ambiguity — if something is unclear, the agent should investigate, not guess.

Prompt each sub-agent with a separate technical brief (file paths, coupling details, dependency category from [DEEPENING.md](DEEPENING.md), what sits behind the seam). The brief is independent of the user-facing problem-space explanation in Step 1. Give each agent a different design constraint. Examples:

- "Minimize the interface — aim for 1–3 entry points max. Maximise leverage per entry point."
- "Maximise flexibility — support many use cases and extension."
- "Optimise for the most common caller — make the default case trivial."
- "Design around ports & adapters for cross-seam dependencies."
- "Optimise for testability — what interface makes the module easiest to test without mocks?"
- "Optimise for deletion — what interface lets callers survive if this module is removed?"

Include both [LANGUAGE.md](LANGUAGE.md) vocabulary and `context/CONTEXT.md` vocabulary in the brief so each sub-agent names things consistently with the architecture language and the project's domain language.

Each sub-agent outputs:

1. Interface (types, methods, params — plus invariants, ordering, error modes)
2. Usage example showing how callers use it
3. What the implementation hides behind the seam
4. Dependency strategy and adapters (see [DEEPENING.md](DEEPENING.md))
5. Trade-offs — where leverage is high, where it's thin

### 3. Present and compare

Present designs sequentially so the user can absorb each one, then compare them in prose. Contrast by **depth** (leverage at the interface), **locality** (where change concentrates), and **seam placement**.

After comparing, give your own recommendation: which design you think is strongest and why. If elements from different designs would combine well, propose a hybrid. Be opinionated — the user wants a strong read, not a menu.
