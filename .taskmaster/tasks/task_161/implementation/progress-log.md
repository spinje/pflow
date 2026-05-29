# Progress Log — Safer Cache Defaults + Iteration Pattern Documentation

**Branch:** `feat/cache-defaults-iteration-docs`
**Status at write time:** All work complete; 62 files staged; `make check` clean; `make test` green (7190 passed, 1 skipped). Nothing committed/pushed.
**Follow-up filed:** GitHub issue [#441](https://github.com/spinje/pflow/issues/441) (coalesce absent-field semantics).

This log captures **insights, decisions, deviations, and things done beyond the plan** — not a phase-by-phase recap (the plan already has that). Read it to understand *why* the diff looks the way it does and where reality diverged from the plan.

---

## 1. The headline result, in one paragraph

Flipped memo-cache defaults so only `llm` nodes cache by default; every other node type (shell/code/http/file/mcp/claude-code) now defaults to `cache: false`. Deleted the now-wrong "input-less shell" lint. Extended `??` to accept JSON literal operands (`${a ?? 0}`, bare `${0}`, etc.) with a reserved-keyword guard. Gave reserved internal keys (`${__execution__.x}`) a targeted validator error. Rewrote the docs that actively lied about loops, plus the MCP resource mirrors. The load-bearing proof is `tests/test_integration/test_iteration_pattern.py`: a sub-workflow batch (`parallel: false`) read/mutate/write-back loop that now processes 5 distinct items **without any `cache: false` annotation** — and fails (re-processes `A` five times) the instant the cache flip is reverted.

---

## 2. Critical insights & learnings (the stuff worth remembering)

### 2.1 The cache key is blind to the world, which is the whole bug
The memo cache key = node type + static params + raw template strings + batch config + prompt-cache content + resolved inputs. It models **nothing about the world outside declared inputs** — no filesystem, clock, env, or network state. A `shell` node running `cat queue.txt` has a *stable* key even as the file changes underneath it. Under the old "cache everything by default", iteration 2+ of a loop re-served iteration 1's stdout forever while reporting success. `llm` is the only node type whose output is genuinely a pure function of its declared inputs — hence the predicate `node_type == "llm"`.

### 2.2 `cache` is NOT part of the config hash — this is load-bearing in two places
- It's what lets a regression test flip `cache: false`→`cache: true` on otherwise-identical IR and get the **same** cache key (used to probe write-leaks).
- It's why the dry-run `_tag_from_entry` can't tell "explicitly disabled" from "default-disabled" — both surface as `cause="cache_disabled"`.

### 2.3 Coalesce `??` skips on absent NODE, not absent FIELD (the deepest insight)
`resolve_coalesce` returns:
- root absent from context → skip operand (branch didn't run) ✅ fall through
- root present, path resolves → value ✅
- root present, **field missing** → `path_error` → template left unresolved → strict mode errors ⚠️

This is deliberate (typo detection), but it means `${ran_node.optional_field ?? "default"}` does **not** fall through to the default. Optional A makes this trap far easier to hit (literals read as "default when missing"). It broke our own `claude-code.md` example. **Not fixed here** (out of scope; trades against typo detection) → filed as issue #441. This is the single most important latent issue in the change.

### 2.4 A predicate and a regex can "agree" on first chars but disagree on what parses
`is_literal_operand` (coarse first-char check) returns `True` for `01`, `[1,2]`, `1e5`; the `_LITERAL_PATTERN` regex rejects them. Code review found that for `01`/`007` (and `"a ?? b"`), the regex *accepted* them but `try_parse_json`/the splitter rejected them at runtime → validate-clean-then-silently-fail. The fix was to make the **regex** the single source of truth for "what is a usable literal" and document that `is_literal_operand` is only a coarse classifier gated by the regex. **Lesson: when two checks guard the same value, define which one is authoritative and make the other defer to it — don't claim they "must agree" when they structurally can't.**

### 2.5 `testpaths = ["tests"]` means `--doctest-modules` never touches `src/`
`make test` runs `--doctest-modules` but only collects under `tests/`, so the ~22 pre-existing `src/` doctest failures (inline `# comment` on expected-output lines, `None`-returns-nothing) are invisible to the gate. This explained the apparent contradiction "make test passes but the file's doctests fail when I target it directly." Important for anyone trusting `make test` as full doctest coverage — it isn't.

### 2.6 "I can't run it" was an unverified assumption, not a fact
I claimed I couldn't run the `claude-code` example because the env lacked the SDK/credentials ("sandbox"). Wrong on every count: there is no sandbox, `claude-agent-sdk` is a declared core dep (`pyproject.toml:32`), and Claude Code authenticated fine via the user's subscription login. A live run confirmed success→`result` is a **dict** (`type=dict`, cost $0.08). **Lesson: verify environment limitations by trying, don't reason about credentials you haven't checked.**

---

## 3. Decisions made (and why)

| Decision | Choice | Rationale |
|---|---|---|
| Cache default rule | `node_type == "llm"` single literal predicate | Simplest expression; one-line change to add a future cached type. No config/metadata indirection. |
| Tag rendering in dry-run (`_tag_from_entry`) | Show `cache: false` tag **only for `LLMNode`** | Post-flip, every non-llm node is `cache_disabled` by default; tagging all of them is noise. The tag is only informative when it signals an explicit opt-out of the default-on behavior (which only `llm` has). |
| `_warn_inputless_shell_nodes` lint | Delete entirely | It existed to warn about the old unsafe default; after the flip its message ("its result is cached and reused") is factually false. |
| `??` literal parsing | Reuse `try_parse_json` from `core/json_utils.py` | Established pattern; correct `(success, value)` semantics that distinguish "literal null" from "not parseable". |
| `_LITERAL_PATTERN` strictness (post-review) | Forbid leading-zero numbers and `??` inside strings | Align the grammar with what runtime can actually resolve, so the validator catches it loudly instead of a silent runtime no-op. |
| Reserved-literal-name guard placement | `WorkflowValidator` only (not compile-time) | Sound today (all execution routes through `WorkflowValidator`). Structurally different from the reserved-`__key__` guard (scans inputs/node-ids, not template refs), so folding into `data_flow.py` adds surface for marginal value. Noted as a known asymmetry. |
| `${__execution__.x}` rejection | Validator-only, not a runtime guard | One source of truth. Runtime `TemplateResolver` *could* resolve it against `dict(shared)`, but all 5 production `compile_workflow` callers validate first, so no workflow reaches runtime with it. A runtime guard would be a second place to maintain the rule. Documented the asymmetry in code. |
| claude-code recovery example rewrite | Branch on `${review.result}` type (dict vs str), not `_schema_error` | `result` is always present; `_schema_error` only on soft-fail. Works around issue #441 without a node behavior change. |
| Coalesce absent-field semantics | Do NOT fix; file issue #441 | Fixing it trades against typo detection — a real product decision, out of scope for this PR. |

---

## 4. Deviations from the plan & things done beyond it

### 4.1 Test migration was larger and messier than the plan's line estimates
- The plan listed specific line numbers; nearly all had drifted. I migrated by **running the suite and fixing what broke**, not by line number.
- Used a **perl global replace** to add `cache: True` to shell/code/http nodes in the big plan-drift files, then surgically removed the two duplicate-key collisions where a node already had `cache: False` on a separate line. The plan implied per-node edits; the bulk approach was faster and the reviewer confirmed it didn't neuter the tests.
- **Markdown-format** child workflows (`- type: shell` in `.pflow.md` strings inside tests) needed `- cache: true` bullets too — a second pass the plan didn't separate out.

### 4.2 Tests deleted/changed that the plan didn't enumerate
- `test_validate_only.py::test_validate_only_json_warnings_are_structured` — used the deleted cache-lint as its warning vehicle; deleted.
- `test_runner.py::test_child_cache_lint_warning_propagates_to_parent_validation` — same; deleted.
- `test_template_type_preservation.py::test_invalid_variable_names_not_simple` — asserted `${123}` is NOT a simple template; under Optional A it now IS (a bare int literal). Flipped the assertion.
- `test_failed_node_invariant.py` — removing `cache: false` from example fixtures shifted source-line numbers (40→38, 39→37, 50→48); updated the line-number assertions.

### 4.3 Source-line drift was a real coupling I didn't anticipate
Removing `- cache: false` lines from `examples/error-handling/*.pflow.md` shifted the line numbers that `test_failed_node_invariant.py` asserts on (those fixtures double as source-line-tracking regression tests). Editing an example file = editing a test fixture's expected line numbers. Worth knowing for any future example edits.

### 4.4 Two CRITICAL bugs found ONLY by the post-implementation reviews (not the plan, not my own testing)
Both were validate-clean-then-silently-fail, exactly the failure mode the feature was meant to kill:
- **C1 leading-zero ints** (`007`, `01`): grammar accepted, `try_parse_json` rejected → raw `${...}` leaked into output.
- **C2 `??` inside a string literal** (`"a ?? b"`): grammar accepted, the operand splitter shredded it → unresolved + a misleading `${b"}` error.
Both fixed by tightening `_LITERAL_PATTERN`. **These were the highest-value findings of the whole effort and neither the plan nor my own happy-path tests caught them** — the multi-agent review earned its keep here.

### 4.5 Doc examples that didn't actually run (found by adversarial verification)
- The new `branching.md` **Loops** example was broken three ways as first written (missing `- next: checker` on the loop-back target; int/str type mismatch in the counter; literal-seed type conflict). Rewrote with consistent `int` typing + the missing `- next:` and **ran it** ("Looped 3 times").
- The `claude-code.md` recovery example was broken (issue #441 root cause); rewrote and validated, then later confirmed live.
**Lesson: a doc code example is only "done" when it has actually executed.** `--validate-only` is necessary but not sufficient.

### 4.6 Extra consumer site the plan's "13 sites" list missed
`_PERMISSIVE_PATTERN` in `template_validation/validator.py` is a *third* copy of the template grammar (alongside `TEMPLATE_PATTERN` and `TEMPLATE_EXTRACT_PATTERN`). It had to be extended with the literal sub-grammar too, or `${0}` / `${a ?? 0}` would false-trip the malformed-template check. The impact-completeness reviewer confirmed I'd caught it; flagging here because the plan's enumeration omitted it.

### 4.7 Mermaid grammar copy (cosmetic, fixed anyway)
`mermaid/_scope.py` has its own `_REF_IN_BLOCK_RE` that doesn't go through `is_literal_operand`. For `${missing ?? "x"}` it would extract `x` as a candidate data-flow ref → a spurious diagram edge if a node is coincidentally named `x`. Added a literal filter to `source_refs_in`. Purely cosmetic (rare), but cheap and consistent with the other 13 sites.

### 4.8 Things the plan said to do that I deliberately did NOT
- Did **not** add `cache: true` to the pure-transform shell echoes in `examples/core/*.pflow.md` (plan said don't; they take ms and the example's point is shape).
- Did **not** touch `examples/core/prompt-caching*.pflow.md` (LLM-only, unaffected).
- Did **not** add a runtime guard for `${__execution__.x}` (validator-only by design).
- Did **not** fix the ~22 unrelated pre-existing `src/` doctest failures (out of scope; only fixed the 4 in `template_resolver.py`, the file this PR touches).

---

## 5. Verification beyond the test suite (and what it caught)

The plan's two appended steps (adversarial verification + multi-agent code review) were the highest-leverage part of the whole effort:

- **Adversarial CLI pass** (real `uv run pflow` runs, not reasoning): caught the broken Loops doc example (3 ways) and the claude-code example breakage. Confirmed the cache flip, all literal forms resolve with correct types, reserved-key errors, and keyword-prefix disambiguation (`truthy_value` is a variable, not `true`).
- **4-agent `/code-review`** (silent-failures, validation-consistency, impact-completeness, test-fidelity): found C1 + C2 (both critical), the weak write-leak test, the missing falsy-present coalesce test, and the stale `cache_lint` docstrings. test-fidelity *mutation-tested* the regression test (reverted the flip → it failed correctly) — the strongest possible confidence signal.
- **Live claude-code run**: closed the last "verified by reading, not running" gap (`result` is a dict on success).

**Meta-lesson:** my own implementation + tests were green and *felt* done at "Checkpoint 2", but the reviews found two critical silent-failure bugs and two non-running doc examples. The first-80%/last-20% framing was accurate — the last 20% was entirely in the verification phases.

---

## 6. Test-strength improvements made in response to review

- `test_cache_false_does_not_write_to_memo_cache`: rewrote to use **identical IR except the `cache` flag** so a leaked write actually collides with the probe read (previously different `purpose` strings → different keys → could never expose a leak).
- Added `test_present_but_falsy_left_value_wins_over_literal` (`${node.x ?? 5}` with `x=0`/`""`/`False` returns the falsy value — guards against a naive truthiness reimplementation).
- Added leading-zero / `??`-in-string / single-`?`-in-string validation tests.
- Added bare-reserved-key and bare-`${__index__}`-valid tests after fixing the bare-form gap the silent-failures reviewer flagged.

---

## 7. Known-open / deferred (explicitly not done)

1. ~~**Issue #441** — coalesce absent-field fall-through.~~ **RESOLVED in this branch** (Option 2). See Section 9 below.
2. **claude-code soft-failure branch** verified by code-read + structural validation, not a live induced soft-fail (hard to trigger deterministically; wiring identical to the verified success path).
3. **Reserved-literal-name guard** has no compile-time backstop (sound today; noted asymmetry).
4. **~22 pre-existing `src/` doctest failures** in unrelated modules (`smart_filter.py`, `type_checker.py`, …) — not in the gate, not this PR's scope.
5. **`examples/test-worktree.pflow.md`** — `cache: false` lines removed; rest of file only spot-checked.

---

## 8. Files & artifacts

- **62 files staged.** Production: `compiler.py`, `engine/types.py`, `ir_schema.py`, `template_resolver.py`, `template_validation/{validator,path_validation,type_validation,batch_item_validation}.py`, `core/types.py`, `core/workflow/{validator,data_flow}.py`, `core/{cache_overlap,prompt_refs}.py`, `prompt_cache_analysis/{trace_loading,token_estimation,stages/discrepancy/predict}.py`, `execution/{plan,formatters/plan_formatter}.py`, `engine/{engine,template_errors}.py`, `mermaid/_scope.py`.
- Docs: `guide/{core,nodes/claude-code,features/{branching,sub-workflows,batch}}.md`, `docs/reference/cli/index.mdx`, 2 MCP instruction files, 4 CLAUDE.md files.
- Tests: new `test_iteration_pattern.py`, new `test_literal_operands.py`, deleted `test_cache_lint_warning.py`, + migrations across cache/plan/validator/resolver suites.
- New helper functions: `_default_cache_for_node_type` (compiler), `is_literal_operand` (resolver), `is_template_reserved_internal_key` (core/types), `_reserved_internal_key_diagnostic` + `_reject_reserved_literal_names` (validators), `_malformed_literal_operand_hint` (template validation).

---

## 9. Follow-on session: reviewed the implementation, then fixed #441 in-branch

This section covers a **separate later session** on top of commit `c2bd2508`. Two phases: (a) review the committed implementation, (b) fix #441 (the one deferred item) at the user's request. Result: commit `00fbddb7` (7 files, +211/−89), full gate green.

### 9.1 Phase A — review of the committed work (no code changes)

Read the 62-file commit's load-bearing surfaces (cache-flip predicate, `??` literal grammar, reserved-key validator), re-ran the load-bearing suites, and confirmed quality is high. Findings worth recording:

- **The two "unplanned" files in the commit are benign** — `mcp_server/tools/execution_tools.py` and `core/diagnostic_render.py` are dead-comment cleanup from the `_warn_inputless_shell_nodes` lint deletion, not scope creep.
- **The committed gate claim held** — re-ran `make check` (clean) + `make test` (7190 passed, 1 skipped) on the actual commit, not just the staging snapshot the log was written against.
- The only substantive open item was **#441**, with an honest docs caveat already in place. Surfaced it as the one thing worth a decision; everything else was PR-ready.

### 9.2 Phase B — the #441 decision (Option 2) and why

User chose to fix #441 in this PR rather than defer. I drove the option choice with a tradeoff analysis. **The whole question reduces to one ambiguity:** when a node ran but a field is absent, is that a *typo* (error) or *"not there"* (fall through)? The system can't tell them apart at resolution time, so each option is just a different way to resolve that:

| Option | What | Verdict |
|---|---|---|
| 1. status-quo + docs | always treat as typo → error | rejected by user (wanted code fix) |
| **2. fall through on absent field** | always treat as "not there" → try next | **CHOSEN** |
| 3. explicit optional-marker operator | author disambiguates with new syntax | rejected — invents syntax no mainstream lang has (overengineering); 2nd grammar extension in one PR |
| 4. schema-aware (optional-vs-typo) | resolver consults declared output schema | rejected — breaks on dynamic JSON (`${shell.stdout_json.items ?? []}` — `items` is in no declared schema → falsely flagged a typo); fragile |

**Why Option 2 is the top-10% answer:** every mainstream coalescer (JS `??`, C# `??`, jq `//`, Jinja `default()`, Go templates, Liquid) treats missing-field-with-default as "use the default." pflow's old "node-ran + field-absent → hard error" is *idiosyncratic* — no mainstream precedent. An agent's prior is "`??` = default when the left isn't there." **And it makes the FINAL code simpler** (removes a branch + a status, see 9.3) — the rare case where simplest-code, convention, and agent-familiarity all align.

**The typo-detection objection, honestly weighed:** Option 2 lets a typo *inside an explicit `?? fallback`* go silent (`${node.tpyo ?? "x"}` → "x"). But (a) bare `${node.tpyo}` — the dominant typo case — still errors loudly; (b) the relaxation only applies where the author wrote an explicit fallback, signalling "absence is expected"; (c) honoring an explicit author-written fallback is *not* the cache-style silent-failure this PR set out to kill. The loss is narrow and opt-in.

### 9.3 The implementation (surgical — Option 2 removes complexity)

1. **`template_resolver.py::resolve_coalesce`** — the `path_error` branch (root present, field absent → STOP + error) became a fall-through (`continue`, try next operand). `resolve_coalesce` **no longer emits `"path_error"`** at all; it returns only `"resolved"` / `"unresolved"`. Load-bearing reason it's a 1-liner: `resolve_template` and `_resolve_complex_match` already collapsed `path_error` and `unresolved` to the same "return template unchanged" branch, so **no caller changed**. A bare `${node.field}` (no fallback) still yields `"unresolved"` → strict-mode error → typos caught.

2. **`template_validation/validator.py`** — Pass 5 (path/field existence) must not hard-error on a missing field inside a `??` chain, or validator and runtime drift (validator rejects what runtime now handles). Refactored the flattened extraction into **one generator `_iter_template_operands` → `(operand, in_coalesce)`** as the single source of traversal truth; `_extract_all_templates` (full operand set, for unused-input detection) and the new `_field_checkable_templates` (excludes multi-operand `??` operands) both derive from it. Pass 5 now consumes `_field_checkable_templates`. **Root** existence is still validated independently in `data_flow.py`, so `${nonexistent.x ?? "d"}` is still caught.

3. **Scope boundary (deliberate, documented):** `output_resolver._is_all_absent_coalesce` (the `## Outputs` coalesce) is **UNCHANGED**. It intentionally surfaces a recovered-node failure rather than falling through (a different concern: not swallowing recovery-handler failures in the declared output contract). #441 is about node-*input* templates only. The `resolve_coalesce` docstring now notes this asymmetry so a future agent doesn't "unify" them.

### 9.4 Gotchas / insights from this session (for the next agent)

- **Only Pass 5 consumes the extracted template set.** Passes 6 (type), 7 (shell-type), 8 (batch-item), 9 (code-annotations) all take `workflow_ir` and re-extract themselves. So the validator-consistency fix was localized to one feed. Verified Passes 6/7 do NOT independently hard-error on a missing field (type checks skip unknown-type fields — confirmed end-to-end with a typed-output `code` node).
- **The diagnostics path is independent of `resolve_coalesce`.** `classify_unresolved_references` (`engine/template_errors.py`) re-classifies references itself and still emits `status: "path_error"` for genuinely-unresolved *bare* references — so `diagnostic_render.py:455` and `test_runner.py:1060` (a bare `${producer.stdout.nested}` case, NOT a coalesce) stayed green untouched. The two remaining `"path_error"` strings in `src/` are this path, correctly kept.
- **`_extract_all_templates` must keep returning the full operand set.** It feeds `_validate_unused_inputs` — dropping coalesce operands there would falsely flag an input referenced only inside a `??` as "unused." That's why the split is full-set (unused-input) vs field-checkable-subset (Pass 5), not "drop coalesce operands everywhere."
- **C901 after the refactor.** The generator + nested `walk` tripped ruff complexity (>10). Fixed by extracting `_operands_in_string` (per-string match logic) so each function is simple — cleaner than the original's `# noqa: C901`. Lesson: when splitting a `# noqa: C901` function, the pieces can still individually exceed the threshold; extract by responsibility, don't just move code.
- **`test_typo_in_field_still_errors_despite_optional` (branch_convergence) did NOT need changing** — it uses a *bare* reference `${branch-high.stddout}` (no `??`), which still errors under Option 2. It now reads as documentation of the preserved typo-detection.

### 9.5 Tests

- Flipped 3 `path_error` assertions in `test_template_coalesce.py::TestResolveCoalesce` to fall-through semantics (renamed for clarity); updated the module docstring.
- Added resolver-level cases: missing field → literal default, → node fallback, → mid-chain skip-to-resolvable, empty-dict-root fall-through.
- Added 3 **end-to-end `WorkflowRunner` proofs** in `test_branch_convergence.py::TestBranchConvergenceIR`: `?? "literal"` → default; `?? peer` → peer; **bare missing field still errors** (the regression guard for preserved typo detection).
- **Mutation-checked the load-bearing proof**: `git stash`-ing only the resolver change makes `test_missing_field_with_coalesce_fallback_resolves_default` fail (old behavior errors), restoring it passes. The test catches the regression it's meant to.

### 9.6 Docs

- `guide/features/branching.md` — caveat rewritten: was "`??` does NOT skip on a missing field… stays unresolved" → now "falls through whenever the left isn't there (node didn't run OR field absent); a bare `${node.field}` with no fallback still errors."
- `guide/nodes/claude-code.md:77` — removed the now-false claim that `${node._schema_error ?? ""}` "does not fall through… stays unresolved" (it cited the old behavior as justification). Kept the `isinstance(result, str)` discriminator example as the clearer pattern (it's robust regardless of #441).
- `runtime/template_validation/CLAUDE.md` — updated the "Coalesce operands are pre-split" design-decision and the split-extractor contract to document `_field_checkable_templates` and the deliberately-reversed "validate both operands early" tradeoff.

### 9.7 Verification, files, commit

- `make check`: clean (ruff, ruff-format, mypy, deps). `make test`: **7195 passed, 1 skipped** (net +5 vs the 7190 baseline). Pre-commit hooks passed on commit.
- **Files (7):** `runtime/template_resolver.py`, `runtime/template_validation/validator.py`, `runtime/template_validation/CLAUDE.md`, `guide/features/branching.md`, `guide/nodes/claude-code.md`, `tests/test_runtime/test_template_coalesce.py`, `tests/test_integration/test_branch_convergence.py`.
- **Commit:** `00fbddb7` on `feat/cache-defaults-iteration-docs` (message includes `Closes #441`). Not pushed. `scratchpads/` left untracked (matching `c2bd2508`'s convention).
- **PR note:** the branch now has two commits beyond `main` — `c2bd2508` (cache defaults + Optional A + docs, 62 files) and `00fbddb7` (#441, 7 files). PR body should summarize both and will auto-close #441 on merge.

---

## 10. Follow-on session: opened the PR, then a guide-content audit that found a real `--only` regression

A **third session** on top of `00fbddb7`. Three phases: (a) re-verify the committed work and open PR #442; (b) audit the `pflow guide` surface for stale content (prompted by the user asking whether the guide topics needed updating); (c) chase "are you FULLY happy?" into a real feature-interaction bug. Result: commit `2a6c708d` (9 doc files), PR #442 (3 commits), and issue #443 filed.

### 10.1 Opened PR #442

Branch was unpushed with no upstream. Confirmed `make check`/`make test` green **on the actual commit** (not just the staging snapshot), then `git push -u` + `gh pr create --base main`. PR body summarizes all three change areas and carries `Fixes #441` (body, not title — GitHub only auto-closes from body/commit keywords). No taskmaster task id existed (work originated from the `scratchpads/` feature-request, not `.taskmaster/`), so the PR omits the Task section. `scratchpads/` stayed untracked, matching the prior two commits.

### 10.2 The routing-vs-content distinction (the user's question)

The user asked whether the `pflow guide <topic>` surface needed updating. Two separate surfaces, and the PR had only fixed one:

- **Content** (the topic `.md` bodies) — mostly handled by the PR. `core.md`'s rewritten cache section is accurate.
- **Routing** (`entry.md`, rendered by both `pflow --help` and bare `pflow guide`) — **NOT handled.** The "Features — when the user says X, load topic Y" trigger list had **no entry for loop/iteration intent**. We wrote the destination pages (`branching` → Loops, `sub-workflows` → Bounded iteration) but left no signpost, so an agent whose user says "loop until X" / "up to N times" routed nowhere. **Lesson: fixing destination pages without the routing surface agents read first is an incomplete fix — the discoverability gap this whole effort targeted reappears one level up.**

Auto-detection (`detect_topics_from_ir`) was already fine: a backward-edge loop trips `branching` (non-default edge action); a `parallel: false` sub-workflow batch trips both `batch` and `sub-workflows`. So *modifying* an existing loop workflow routes correctly; only *intent* routing for a new build was missing.

### 10.3 The `--only` regression — the highest-value find, caught by "are you FULLY happy?"

The cache flip **silently changed `--only`'s behavior**, and the original PR never analyzed it (the progress log through §9 doesn't mention `--only`). Verified against `engine._run_inner`: `--only` walks from `start_node` and **executes every upstream node** until the target (no trace restoration), consulting the memo cache per node.

- **Before the flip:** all nodes `cache_enabled=True` → upstream memo-hits → cached result returned, `exec()` not run → **side effects did not re-fire**.
- **After the flip:** non-`llm` upstream `cache_enabled=False` → memo skipped → `exec()` runs → **side effects re-fire** (`--only summarize` over `shell: gh pr create` re-creates the PR every run).

This is a genuine regression in `--only`'s core purpose (cheap single-node iteration without disturbing upstream), not just a perf change. Filed as **issue #443** with four options; the right long-term fix is **trace-based upstream restoration** (hydrate uncached upstream from the last `~/.pflow/debug/` trace instead of re-executing) — out of scope here, same defer-with-an-issue call as #441. The docs now carry the interim warning everywhere.

**Meta-lesson (third time this pattern has paid off — see §5, §9):** my implementation felt done and the gate was green, but the user's "are you FULLY happy?" prompt is what surfaced both the `--only` bug *and* my own incomplete first pass (§10.4). Verification-on-demand keeps earning its keep; "green + feels done" is not the same as "done."

### 10.4 My own first doc pass was incomplete — re-introduced cross-surface drift

First pass fixed only the `pflow guide` surface (`core.md`, `llm.md`, `entry.md`). Grepping ALL surfaces for the stale `"upstream cached"` claim found it in **three more places** I'd missed:
- `mcp_server/resources/instructions/mcp-agent-instructions.md:635` — the PR had just *synced* these mirrors; my partial fix re-diverged them.
- `docs/reference/cli/index.mdx:403` — "served from cache if available" (softer but still wrong, no side-effect warning).
- `src/pflow/cli/CLAUDE.md:157` — "Upstream from cache." (developer-facing, still wrong).

**Lesson: when correcting a phrase that's mirrored across surfaces (guide / CLI ref / MCP mirrors / CLAUDE.md), grep the whole repo for the phrase, not just the file you're looking at.** The PR's own §9 MCP-sync work proved these surfaces drift; editing one without the others recreates exactly that drift. Verified the `warning_catalog.py` "upstream cache" hits are provider-prompt-cache (unrelated, correct) and the "11. cache_result" hits are per-node *execution* step numbering (not the validator pipeline — that was correctly renumbered to 10 by the PR).

### 10.5 Content audit findings (what was actually stale vs. fine)

| Item | Verdict | Fix |
|---|---|---|
| `core.md` rewritten cache section (385-417) | Accurate & complete | none |
| `core.md:262` "Caching makes re-runs fast" | Overgeneralized — only `llm` now | scoped to `llm` |
| `--only` "upstream cached" (5 surfaces) | Stale + hides side-effect re-fire | corrected all 5 + warning |
| node files `shell.md`/`code.md` | Silent on the new default (gap, not wrong) | added one-line cache note at point-of-use |
| `docs/how-it-works/template-variables.mdx` coalesce | Stale on BOTH Optional A (literals) and #441 (absent-field) | rewrote section |
| `prompt-caching.md`, `http/file/mcp` node files | Fine — no memo-cache claims | none |

### 10.6 Decisions

- **Didn't hard-link #443 into user-facing guide text** — issue numbers don't belong in guide content (they churn). Referenced #443 in the commit message instead. (`branching.md` similarly cites behavior, not the #441 number.)
- **Included the Mintlify website surface** (`docs/how-it-works/template-variables.mdx`) even though the user's question was about `pflow guide` — same PR's responsibility, and it now lied by omission about `??` literals + fall-through.
- **Included node-file one-liners** (`shell.md`/`code.md`) — these are the loop-building nodes; a cache note at point-of-use reinforces the iteration-safety win even though `core.md` covers it centrally. Skipped `http/file/mcp` node files (less loop-central).
- **`[skip review]` in the commit message** per user request (doc-only change).

### 10.7 Verification, files, commit

- `make check`: clean. `make test`: **7195 passed, 1 skipped** (unchanged — doc-only edits). `test_guide.py` + `test_docs/` (67 tests) green; no pinned-wording assertion tripped. Ran the full gate three separate times across this session (review checkpoint, after first doc pass, after consistency fixes) — all green.
- **Files (9):** `guide/entry.md`, `guide/core.md`, `guide/nodes/{llm,shell,code}.md`, `docs/how-it-works/template-variables.mdx`, `docs/reference/cli/index.mdx`, `cli/CLAUDE.md`, `mcp_server/resources/instructions/mcp-agent-instructions.md`.
- **Commit:** `2a6c708d` (`[skip review]`), pushed to `origin/feat/cache-defaults-iteration-docs`. PR #442 now has 3 commits: `c2bd2508` (62 files) + `00fbddb7` (#441, 7 files) + `2a6c708d` (docs, 9 files).
- **Issue #443** filed: `--only` re-fires side-effecting upstream after the cache flip. The one genuine open design item — captured, not silently shipped.

### 10.8 For the next agent

- **PR #442 is open and ready for review/merge.** `Fixes #441` in the body auto-closes #441 on merge. #443 is the fast-follow (trace-based `--only` upstream restoration is the recommended option).
- **First commit message is the generic `"implementation completed"`** (`c2bd2508`). Cosmetic; if the merge preserves individual commit messages rather than squashing, reword it first.
- **The `--only` interaction is the load-bearing thing to understand here** — if you touch caching or `--only`, read #443 before assuming "upstream cached" anywhere.
</content>
