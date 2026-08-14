# session-02 — 2026-07-11

## [2026-07-11] main orchestrator — orchestration system restructured (agent-hierarchy adoption)

- Did: ported the sibling orchestration system to pflow with the user (discussion → 6 forks
  ruled → full doc set written). Sources read: the sibling repo's `task-orchestrator.md` /
  `task-phase-implementer.md` / `task-planner.md` / `ORCHESTRATION.md` + mainframe's
  `orchestrating-system.md` (the predecessor originals).
- Changed: NEW `.taskmaster/orchestration/ORCHESTRATION.md` (canonical process contract),
  `DECISIONS.md` (seeded #1–#7), `CURRENT-STATE.md`, `sessions/` (this file; session-01 = the
  converted old log); NEW `.claude/agents/task-planner.md` (fable), `task-orchestrator.md`
  (opus), `task-phase-implementer.md` (per-launch); REWRITTEN
  `.claude/commands/start-orchestration.md` (thin main-orchestrator role prompt);
  DELETED `orchestrator-progress-log.md` (content preserved in session-01 + git history).
- Verified: all source files read in full; pflow substitutions checked against the live repo
  (`.claude/agents/` inventory, `deep-review` SKILL.md, `worktree-pflow.md` flags incl.
  `open_cli`/`open_cursor`/`copy_folder`, `context/adr/` + ADR-0013, Makefile targets per
  CLAUDE.md). | Assumed: `/create-task-review`, `/create-pr`, `/braindump`, `/test-reflect` remain
  available user-level/project skills in subagent contexts (fallback written into ORCHESTRATION
  review policy: read the skill file directly).
- Deviations/surprises: none vs the approved skeleton. Deliberately NOT ported: the sibling repo's
  migration/DB machinery, prod verification, Django parallelism rules, the "ALL UI phases →
  Fable" ruling (sibling-repo-specific consumer-polish rule; pflow's web UI is a dev tool). pflow
  analog chosen for the mandatory plan-review trigger: engine (`runtime/engine/`,
  `workflow_executor`) + trace format.
- Self-checks: clean — one open risk flagged in CURRENT-STATE: the hierarchy hasn't run a real
  lane-A/B build yet; first launch is the shakedown.
- Next: user reviews the doc set → docs commit to `main` (user-gated push) → next unit of work
  picks a lane under the new system. 176 continues in lane C untouched.

## [2026-07-11] main orchestrator — correction: UI-routing ruling ported after all (DECISIONS #8)

- Did: the "not ported" call above was a misread on my part — the user corrected the premise
  (pflow's web UI is NOT a mere dev tool): **ALL web-UI phases route to Fable, and UI work
  ALWAYS invokes `screenshot-pflow-web-ui` and verifies everything.** Also ran the requested
  full re-read of every created file against the repo.
- Changed: DECISIONS #8 added; ORCHESTRATION.md (Fable routing row, DoD UI bullet now mandatory,
  lane B names its agent type — Opus task-orchestrator in issue mode, log format points at
  `/create-progress-log`); all three agent defs (planner states UI intent/acceptance criteria;
  orchestrator never implements UI inline; implementer's UI rule + description). Mirrors
  re-synced.
- Verified: `task-N.md` spec naming (task_176/171), `web/` + its CLAUDE.md exist, `tests-windows`
  is the real CI job name, `scratchpads/` gitignored, `screenshot-pflow-web-ui` +
  `test-reflect` + LANGUAGE.md + ADR-FORMAT.md + Task-159 baseline paths all exist,
  `pflow-codebase-searcher` frontmatter pinned opus, worktree workflow accepts
  `open_cli`/`open_cursor`/`copy_folder`/`work_type`/`base_branch`/`model`. | Assumed: nothing
  new.
- Deviations/surprises: none beyond the correction itself.
- Self-checks: clean.
- Next: unchanged — user review → docs commit.

## [2026-07-11] main orchestrator — DECISIONS #9: lane-B model policy

- Did: user ruling recorded — lane-B complexity assessed at pick time; Opus floor (never lower);
  Fable for complex/hard-debugging issues only with per-launch user approval. Folded into
  ORCHESTRATION.md (Lanes + Model routing); scoped to lane B (lane A's #3/#8 Fable rules are
  standing approvals). No agent-def changes → no mirror sync needed.
- Next: unchanged.

## [2026-07-11] main orchestrator — final audit ("fully happy?" pass)

- Did: coherence sweep across the whole doc set on the user's self-check prompt.
- Found + fixed: (1) **real contradiction** — lane B says the task-orchestrator merges its own
  PR, but the agent def had only two entry modes and a flat "never merge" → added the issue-mode
  entry (issue = spec, no task artifacts, scaled completion gate, squash-merges own PR after CI
  green) + the exception on the never-merge rule. (2) Genesis braindump + session-01 were
  orphaned from the boot reads → historical pointer added to the command's "Where things live"
  (braindump marked: process claims SUPERSEDED, working-style observations still hold).
- Verified: DECISIONS #8/#9 referenced consistently (ORCHESTRATION ×4, each agent def);
  mirrors re-synced after the def edit. | Known, pre-existing, not fixed: the Codex TOML sync
  drops `model:` frontmatter for ALL agents (searcher's opus pin included) — the hierarchy runs
  in the Claude harness where the explicit `model` param governs, so no impact; fix the sync
  script only if Codex ever runs orchestration roles.
- Self-checks: fully happy after the two fixes. Residual risk unchanged and already recorded in
  CURRENT-STATE: the hierarchy is untested until its first lane-A/B launch.
- Next: docs commit (user-gated), then the first launch under the new system is the shakedown.

## [2026-07-11] main orchestrator — DECISIONS #10: session-read rule

- Did: user ruled on boot reads — latest session file, plus read further back only past thin
  files (chose this over a fixed last-2 window). Folded into ORCHESTRATION.md (state artifacts)
  + the command's boot sequence; DECISIONS #10 records the rationale. Mirrors re-synced.
- Next: unchanged.

## [2026-07-12] main orchestrator — robustness pass (user picks on 5 proposals)

- Did: applied the accepted subset: pre-system dependency-review exception (light wording, not a
  formal clause — user: "almost all new tasks have this"); hot-seam rule made live
  (CURRENT-STATE watch list extends the static engine/trace pair); user-level-skill fallback
  path added to the task-orchestrator def (`~/.claude/commands/<name>.md` — locations verified
  on disk). CLAUDE.md pointer (#1) DROPPED on reflection at the user's hesitation — theorized
  problem, not observed; the routing truth already lives in the task-orchestrator's own def
  (stronger precedence than CLAUDE.md); revisit only if a shakedown shows actual misrouting.
  Rejected as over-process: retrospectives, budget tracking, triage cadence. Also: subagent
  frontmatter descriptions tightened to 1–2 sentences (user ask); mirrors synced.
- **Parallelism guidance (user: note only, deliberately NOT a rule): keep to ≤2 concurrent
  builds until the system has proven itself over a few tasks.**
- Next: user rules on the CLAUDE.md pointer text; then docs commit; shakedown candidate for
  lane B remains #565.

## [2026-07-12] main orchestrator — /close-orchestrator-session ported (DECISIONS #11)

- Did: adapted the sibling repo's close ritual as `.claude/skills/close-orchestrator-session/SKILL.md`;
  wired it source-repo-style — the command's session-end section is now a pointer at the skill (one
  home), and `braindump-main-orchestrator.md` (seeded) joins the boot stack after the session
  file. Also: subagent frontmatter descriptions tightened (earlier user ask this session).
- Adaptations: lane-C terminal agents exempt from the drain (they outlive the session); no
  prod-verify; push of `main` user-gated per DECISIONS #5; mirror-sync reminder folded into the
  skill's step 4.
- Next: docs commit (user-gated), then the lane-B shakedown (#565 candidate).

## [2026-07-12] main orchestrator — session close (first run of the ritual)

- Did: drain check (no subagents ran; 176's lane-C agent lives outside the session — state in
  CURRENT-STATE), retrospect, state audit (DECISIONS #1–#11 all rowed same-breath; roadmap/task
  statuses untouched this session — nothing shipped), braindump first real refresh (web-UI
  lesson, port-the-wiring rule, coherence-audit mechanism; codified lines pruned), docs commit
  to `main`.
- Process-evolution proposals: none beyond what this session already ratified — the session WAS
  the process change; the close ritual ran clean on its first use.
- Next for the successor: docs are on `main` (unpushed — user-gated); first live run of the
  hierarchy = lane-B shakedown, #565 candidate; on 176's merge follow CURRENT-STATE's on-merge
  duties.
