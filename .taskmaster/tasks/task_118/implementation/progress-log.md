# Task 118 — progress log

Append-only. Entry format: ORCHESTRATION.md → "Progress-log entry format".

## [2026-10-06 22:45] task-planner (Fable) — plan written, self-review launching; PARKED-ON-USER after commit (CP-1)
- Did: investigated on `82341e2b`, fast-forwarded the branch to `b2cd92e3` when #715 merged mid-plan (no local
  commits yet, so `--ff-only`); eight `pflow-codebase-searcher` passes (Python param walks, the TypeScript
  scanners, display + redaction, validation layering + parser facts, stale surfaces, Windows + CI, two
  test-classification passes that read every listed site); read `template_surfaces.py`,
  `template_resolution.py`, `shell.py` prep/exec/post/fallback, `data_flow.py` scope + node-param check,
  `file_resolver.py`, `trace_report._format_resolutions`, both shell failure renderers and the carry warning
  directly. Wrote `implementation-plan.md`, `diagnostics-checkpoint.md` (CP-1, BEFORE executed on `b2cd92e3`),
  `inventory.py`; corrected the spec in place (plan §2.7).
- Changed: `implementation/{implementation-plan.md, diagnostics-checkpoint.md, inventory.py, progress-log.md}` (new),
  `task-118.md` (measured size, consumer list, probe sentence, stale-surface list, vehicle-test list, one citation).
- Verified (executed): `inventory.py` → 428 templated bodies / 128 files (plan §2.5 breaks it down);
  `task_159/baseline/verify.sh` → 75 pass / 12 drift / 0 harness errors, drift set named in plan §2.5;
  `task_170/.../capture.py --check` → 29 examples, 1 differing (`error-handling/typo-on-failed-node`) — both
  drifts pre-date this task; fourteen probe workflows (checkpoint BEFORE blocks); `sh` semantics of `${item}`,
  `${fetch-data.stdout}`, `$${HOME}`, `${a.b}` inside `$(…)`.
  | Assumed (named in plan §10): no user node registers as `shell`/`code`; the searcher offload is runnable from
  the build environment. Unverified, settled only by `tests-windows`/Linux CI: plan D8, D3.
- Deviations/surprises (vs the spec): (1) a ninth body consumer the spec did not name — the MCP single-node run
  expands `${VAR}` from the process environment and settings over every param, `command` included
  (`mcp_server/services/execution_service.py:731-736`); a shell loop variable written `${f}` raises there today.
  (2) `cli/commands/_probe_impl.py` resolves nothing — it needs no exemption, only the binding, which is why
  binding is node-owned (D2). (3) Two hand-maintained copies of guide content under
  `src/pflow/mcp_server/resources/instructions/` hold 16 templated shell fences — absent from the spec. (4) The
  inventory cannot see ≈50 sites passed through helper arguments, and a test expecting an error for an
  out-of-scope name in a command passes vacuously after the flip — the gate for PB is the T2 list by name, not
  the script. (5) Today a misspelled step id in a command is an ERROR with did-you-mean; under a scope-only rule
  it would be silent — hence checkpoint ruling 2 (a warning). (6) `tests/test_core/test_types.py` has no shell
  text; `test_union_types.py` is a vehicle file, not retired behaviour. (7) Converting the corpus *before* the
  flip is possible because `env:` already works for strings — it removes the "B without C" window the spec
  describes (D13) and makes the tooling workflows safe under both semantics.
- Not edited, goes up: `task-181.md` cites the unused-input check at `core/workflow/validator.py:555-600`; it is
  at `runtime/template_validation/validator.py:555-612`.
- Self-checks: plan-mode `deep-review` launching now (mandatory — engine contact): review-plan,
  architecture-fit, silent-failures, impact-completeness, validation-consistency, feature-interactions,
  agent-ux, concurrency-safety, test-fidelity. Outcome appended below before the commit.
- Resume point (if this session is lost): the plan and checkpoint are complete drafts on disk, uncommitted. Next
  acts in order — evaluate the nine lens reports, fold confirmed fixes into the plan, append the outcome here,
  commit plan + checkpoint + inventory + spec + log with deliberate staging, hand back with CP-1's path. After
  the user's ruling on CP-1 the planner is resumed ONCE to fold the ruling into the plan (strings and, if rule 1
  or 2 changes, D5) and to record it here; no build starts before that entry exists.
- Next: evaluate the battery.

## [2026-10-06 23:55] task-planner (Fable) — plan self-review folded; committing; PARKED-ON-USER (CP-1)
- Did: nine plan-mode lenses by direct launch (review-plan, architecture-fit, silent-failures,
  impact-completeness, validation-consistency, feature-interactions, agent-ux, concurrency-safety,
  test-fidelity). Criticals verified by the planner against code before folding: (1) FI C1 — a failing child
  shell step's output rides the child-failure bundle into batch error records that CLI text/JSON/MCP emit
  unredacted (`runtime/workflow_executor.py:662-672`, `execution/formatters/batch_errors.py:99-104`,
  `batch_executor.py:484-486`) → D9 now records one display-safe copy at the source; (2) SF C1 — `${limit:-10}`
  on an in-scope name is an Issue the rule ignored and sh would silently default → D5 treats an Issue whose
  leading name is in scope as a leftover; (3) SF C2 — `git-worktree-task-creator` pre-escapes a value for the
  pasting layer (`workflow.pflow.md:308-309`, read) → conversion rule 5.3 + a stubbed `launch-cli` run;
  (4) IC C1 — the drafted Interface comment `NAME: value` registers a fake param (lens executed the extractor)
  → wording changed + an assertion; (5) TF C1 — `document-processor`'s converted step never reaches the
  workflow result (lens executed) → the PC gate dumps per-node outputs from the trace (`baseline/node_outputs.py`).
  Warnings folded: per-step scope for the leftover rule (batch alias/`__index__` only on the batch step; a
  bare `${stepid}` never — VC W1/FI W1); D4's errors shared with the compiler (UI preflight — VC W2); carried
  values are parsed by `inputs:` (#686, accepted — VC W3); no braces in PC and guide fences convert in PC
  (RP W1/W2, VC W4); code bodies read through `ast` string constants so f-strings pass (RP W4/VC W5); file
  references through one node-aware predicate at four callers (RP W3/IC W1); E2BIG translated inside
  `exec()` non-retriable + lone-surrogate check (CS W1/W2); Windows merge keeps the author's spelling
  (CS S3); batch-item report pages (FI W2/IC W2/SF W3); per-row inputs for the consumer table and a
  dynamic instrumented suite run before the flip (TF W1/W3, SF W4); Task-159 compared actual-vs-actual and
  golden hashes bounded (TF W4/W5); the equivalence harness for non-runnable conversions (TF W6); D8
  presence checks (TF W7); dynamic names for the `ignore_errors` test (TF W8); parity-row shapes (TF W9);
  `text` taken off the mode axis into `binds_as_text` + the resolver's `parses_leaves` predicate (AF S1 and
  the coordinator's seam note: one per-leaf predicate Task 120 extends); resume `--force` + skill symlinks in
  the hand-back (AF W1/FI S1); the unread-`inputs:`-key warning (SF W2); every agent-ux rewrite (C1–C3,
  W1–W7) is in the checkpoint. Disputed/declined with reason in the plan: a required `TemplateConfig.node_type`
  (one constructor; 31 test constructions), an AST meta-test, a did-you-mean on plain braced names (Task 182),
  unbound-but-unread env warnings.
- Changed: `implementation-plan.md` (§1, §2.1, §3 rewritten, §4 phases, §5, §6.1, §7, §10),
  `diagnostics-checkpoint.md` (rewritten: per-step scope, hard cases f/g, Issue forms, every rewritten
  message, §4e/§4f new, §5 generalized, §6 display-safe copy), `task-118.md` (the `inputs:`/Carry parse
  clause).
- Verified: the five governing/related issues were read in full at investigation start (body + comments:
  #621, #59, #620, #686, #698) — recorded here because the earlier entry omitted it.
- Deviations/surprises: the spec's "validate-only and the run agree" needed the compiler to share D4's
  errors — the UI launches through a compile-only preflight, so a validator-only error there is invisible
  (`ui/server.py:1019, 1233-1237`); and the spec's byte-for-byte claim holds only for a value bound directly
  (a value through `inputs:` is parsed by #686's mechanism) — the spec now says so.
- Self-checks: all nine lens reports evaluated; two findings handed up unresolved (both other tasks' specs):
  `task-112.md:73` names Pass 7 as coverage; `task-181.md` mis-cites the unused-input check.
- Next: commit plan + checkpoint + inventory + spec + log; hand back with CP-1's path; on resume with the
  ruling, fold strings (and D5 if rule 1/2 change) and record it here before any build.
