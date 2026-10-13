# CURRENT-STATE.md (last verified: 2026-10-13, session-16 close — main @ origin/main `84aa3cdb`, push CI green)

_Living state header — the ONE mandatory session-start read (~80-line budget; state + pointers
only). Rewritten at close/park (ORCHESTRATION "Artifacts and ownership"); work done outside a
numbered session appends a dated `## Outside-session — folded at next rewrite` block at the top,
which the next boot folds. How-it-got-here: latest `sessions/session-NN.md` (+ the previous three
braindumps); routing: `sessions/INDEX.md`. Every claim here is a pointer to verify, not a fact._

## Process

- Session-16 ran Fable, then **Opus** from the user's `/model` swap (saved as default). Routing unchanged (DECISIONS #24).
- **Review rule (DECISIONS #32, the user's words):** astra for every review lens (Claude builds, so astra IS the second family);
  only VERIFIED Criticals count; later rounds lean and per-lens; the falsifier counts; ≤3 rounds, a verified Critical at round 3
  ⇒ hand back. Its fold into ORCHESTRATION "Review policy" + `lane-implementer.md` + `task-orchestrator.md` + the deep-review
  skill is PROPOSED (needs the user's word) — until then, every packet states it.
- Lane gates must run `make test-all-local` (CI runs e2e; `make test` excludes it — #801 went red on that). State it in packets.

## In flight — nothing. No open PRs, no worktrees, no live agents.

## Next session, recommended order (NOT yet user-agreed)

1. **Rule the open proposals** (Decisions pending, below) — the review-rule fold first (every packet carries it by hand until then).
2. **Security pair from the residual sweep:** #865 (secrets escape via pre-scrub cuts / encodings / keys — closing shape: keep full
   text in diagnostics, cut only at display after the scrub) and #866 (the secret set is rebuilt per reader — R1 history/describe/
   skill-symlink exposure is the cheap first member). Both carry codex "Cross-model check" sections; read those first. #860
   (`/api/gate` raw secrets) attaches at `ui/server.py::gate` after the trace load (Task 185 landed the lookup).
3. Fills: #843 residuals (probe JSON doc uncapped — `_probe_impl.py::_json_document`); #867 (one-word saved name; delete the
   heuristic, decide `lint`/`check`/`validate` reservation); #869 (probe duplicate path, small); #806 remaining members
   (b)(d)(e)(g) + the `template_errors.py` "a object" allowlisted bug; docs lane (`scratchpads/session-16/residuals/drafts/
   docs-lane-and-hygiene.md`: R4 R14 R19 R22 + hygiene R2 R15).
4. Carried fills (verify ownership at pick-up): #842 #841 (redact before excerpting — #863's carrier) #832 #835 #838 #848 #849
   #851 #852 (help-text class guard, in-repo) #855 #834 #836 #837 #839.

## Decisions pending the user

- **Review-rule fold** (above) — recommend: apply as written in DECISIONS #32.
- **#858's class-closing fix = an ENGINE task** (a pending denial is delivered before the gated step's templates resolve; the
  preflight's static reference check is never needed). Option D shipped (#861); the issue stays open. Recommend: create the task.
- **#868** `command: ./tool.py` inlines script text — options (a) document `exec ./tool.py` / (b) never file-resolve `command`
  (breaks bundling + changes path base) / (c) shebang rule. Importance ~3.
- **#872** (research & design) traces store each step's static body every run (~85% of a typical trace) — shape at pick-up.
- **ADR-0018's cross-version scope** (older/newer pflow sharing `~/.pflow`: additive grammar, "a deleter keeps what it does not
  understand") — keep or trim? Merged as written.
- RECURRENCE PROPOSED (4): see RECURRENCE.md — incl. `tests-windows` flake now n=3 → file the de-flake issue.
- Carried: #845 · #844 · #828 · F4 demo-studio items · the release (v0.16.0 + 62 commits; the user: not 2026-10-12/13) ·
  #802/#803/#805 shapes. #692 is RULED (s14: open, low, lane at pick-up).
- **MCP server future (parity vs removal)** — HELD on the user (s15); Task 152 roadmap `later` with the hold in its spec.

## Do not re-raise (declined, with the trigger that reopens each)

- pr-closer / RELEASE-BLOCK / batched releases / docs-PR lane / automatic PR review / cross-task knowledge base — never.
- External PRs are not taken (s16: #856 closed); fix the issue in-repo as a class.
- #665 (`save --force`), #697 (trace 0644) — reopen when saved-library use becomes real.
- Consumer reports (s13 + s15) declines stand — reopen on a SECOND consumer hitting the same ask. Output `keys:` lives on #743.
- PyPI yank — closed. Execution-start MCP auto-sync — deleted (#751). #858 Option A (static denial-reference check) — withdrawn
  after rounds 3–4 each found a new leak; reopen only as the engine task above.

## Regime facts (dated — re-measure, never inherit)

- 2026-10-13: `make test-all-local` ~12,140 passed. Open issues 185 (newest #872).
- 2026-10-13: `~/.pflow/debug` 23,182 traces / 1.44 GB after Task 185's first sweep (31,396 before); `resume list` 0.28 s
  (was 16.8 s). Backup of the pre-sweep directory: `scratchpads/session-16/backup/pflow-debug-backup-2026-10-12.tar` (2.7 GB,
  gitignored) — delete once the user is satisfied.

## Watch list (non-obvious, easy to miss)

- **Trace filenames changed (Task 185, ADR-0018):** `…-{hash8}-{name}.{execution_id}[.only][.from-…]-{started}.json` + `.paused`
  sidecars; old-grammar traces are invisible to lookups and age out. Retention default 14 days; `runtime.trace_retention_days`,
  `PFLOW_TRACE_RETENTION_DAYS` (0 = keep all). Tests and probes that glob traces must use the new grammar.
- **Probe is the runner now (#862):** `execution/probe.py::probe_node` for CLI + MCP; exit table 0/1/2.
- **Exit codes (#815):** 2 wrong call, 1 failed, 3 denied, 4 paused, 130 interrupt.
- **The permission classifier blocks some subagent actions** (a lane's `gh pr merge`, a real-directory sweep) — never perform a
  blocked subagent action yourself; surface it to the user (s16: both resolved by the user's word).
- The user's shell exports provider keys — every probe/dogfood/verification agent `env -u`s them. The test suite redirects HOME.
- MCP stdio shims + `anyio>=4.5` exist only for Task 178 to delete. `stash@{0}` (Task 125 WIP) is the user's — never `git stash`.
- Agent defs/skills in the MAIN checkout are read live by agents launched from the session — committed or not.
