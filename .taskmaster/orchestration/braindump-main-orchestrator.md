# Braindump — main orchestrator (rolling tacit layer)

_Refreshed in place at each session close (`/close-orchestrator-session`, step 3 — the doctrine
lives there). Sessions: seeded 2026-07-12; first close 2026-07-12 (the restructure session)._

Predecessor tacit layer: `braindump-2026-07-02-orchestration-genesis.md` — HISTORICAL; its
process claims are superseded by ORCHESTRATION.md, its working-style observations were absorbed
into the command's "Working with the user".

- **The web UI is first-class product, not a dev tool.** I framed it as "a dev tool" to skip
  loudkult's UI ruling and the user hard-stopped it ("pflows web ui is not a web tool, and all
  ui should be done by fable… and verify everything"). Lesson shape: never infer a surface's
  importance from its architecture (local server ≠ low stakes) — the ruling is DECISIONS #8;
  the sensitivity behind it (UI quality matters to them, everywhere) is the tacit part.
- **When porting an artifact from another repo, port its WIRING too** — grep the source repo for
  references to the artifact before declaring the port done. I wrote the close skill without
  checking how loudkult's command invoked it; the user had to point ("see how its mentioned in
  the loudkult docs"). One `grep -rn <name>` would have caught it.
- **Mechanism that worked — cross-file coherence audit:** grep `DECISIONS #` across
  ORCHESTRATION + all agent defs, then check each def's standing rules against the lane rules.
  Caught a real contradiction (lane B's merge-it-itself vs the def's flat "never merge") that
  both writing passes missed. Run it after any multi-file process edit.
- **ASSUMPTION:** user-level skills (`/create-pr`, `/create-task-review` — verified on disk at
  `~/.claude/commands/`) resolve inside Agent-tool subagents. Fallback is written into the
  task-orchestrator def; the first lane-A/B launch confirms or kills this line.
- **Local-only right now:** `main` is unpushed (the restructure docs commit + `eeba1e8e` +
  `276672a4`) — ask the user before pushing. The Task-176 brief exists only inside its worktree
  (`scratchpads/` is gitignored — by design). Mid-session, index entries appeared staged that I
  didn't stage — almost certainly the user reviewing in their editor; don't treat a dirty index
  as your own mistake, but re-stage current versions before any commit.

Note to next agent: read this file fully, summarize it to yourself, then proceed.
