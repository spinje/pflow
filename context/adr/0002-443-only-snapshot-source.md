# `--only` reuses upstream from the debug trace, not the memo cache

Status: accepted

After the cache-defaults flip (only `llm` caches by default), `--only <node>` re-executed
every uncached upstream node — re-firing side effects like `gh pr create` on each iteration
(issue #443). We give `--only` **snapshot semantics**: it no longer walks the graph but seeds
the shared store with the target's **upstream** outputs (the nodes that ran before it) from the
**most recent full successful run** and executes only the target. The snapshot is sourced from the **debug trace**
(`~/.pflow/debug/workflow-trace-*.json`), not the memo cache (`cache.py`).

## Considered options

The snapshot needs the last full run's output for **every** upstream node, as a **coherent set**.

1. **Memo cache** (`MemoizationCache.get_latest_for_node`). Looks like the natural fit — it is
   literally "node X's last output on disk" — but fails on the two criteria that matter:
   - **Doesn't contain the data.** Writes are gated on `cache_enabled`, so the side-effecting
     `shell`/`http`/`mcp` upstream nodes (the whole problem) are never written. Using it would
     require writing *every* node's output to the cache — inverting the write-suppression the
     cache-flip deliberately established, i.e. coupling the fix to the bug's cause.
   - **Incoherent across runs.** `get_latest_for_node` returns each node's newest entry
     *independently*; on a branching workflow that mixes outputs from different runs into a
     combination that never actually co-existed.
   - Plus a 24h TTL — `--only` would silently break a day after the last full run. Rejected.
2. **Dedicated snapshot store** (new SQLite table or file written every full run). Clean
   separation and full fidelity, but a whole new subsystem (schema, lifecycle, write-every-run)
   for a v1 with no users. Rejected as premature; it is the natural escape hatch if the trace
   coupling ever bites.
3. **Debug trace** (chosen). Already records `node_output` for *every* executed node regardless
   of `cache_enabled`, as one coherent per-run record, with no TTL and at zero new write cost.
   Selection scaffolding (~80%) already exists in `prompt_cache_analysis/trace_loading.py`;
   per-node extraction is `final_events_by_node(trace["nodes"])`. Nested `--only a.b.c` is
   designed to recurse through the trace's `sub_workflow_events`, mirroring the workflow's own
   nesting — **deferred, not built**: v1 is flat-only (see Limitations) and dotted targets are
   rejected at validation (`engine.py:_validate_only_target`); the dotted plumbing exists dormant.

## Consequences

- **Debug traces become load-bearing for a core feature, not just a debug aid.** A reader will
  wonder why `--only` depends on `~/.pflow/debug/`. Concretely: `--no-trace` disables the
  snapshot source, and clearing the debug dir breaks `--only`. Both surface as a **hard error**
  ("no saved run to snapshot from — run the full workflow once, then retry `--only`"), never a
  silent re-fire — which was the entire point of #443.
- **`--only` runs must not poison the snapshot.** An `--only` run's trace contains only the
  target, so the trace records `only_node` and the snapshot loader selects only full runs
  (`only_node is None`; status `success` or `degraded` — never `failed`; a degraded source
  emits the loud advisory described in Limitations).
- **Binary upstream outputs degrade.** Trace sanitization replaces `bytes` with a
  `"<binary data: N bytes>"` placeholder, so a target consuming binary upstream gets the
  placeholder. Rare; documented. The memo cache and a dedicated store would not have this loss —
  a reason the escape hatch exists.
- **Branch divergence is loud, not silent.** If the last full run took a different branch and so
  lacks an upstream the target needs, the target's template resolution raises the normal
  unresolved-reference error rather than running on stale/absent data.
- **Interim by direction, not just by expedience.** A future PR is considering **merging the
  debug trace and memo cache into one artifact** (the trace currently repeats node data and can
  reach 50+MB on large workflows). The trace is already the superset of node outputs and the
  memo cache a subset, so building `--only` on the trace today means it rides that consolidation
  naturally — the snapshot reader repoints at the merged artifact — rather than being orphaned.
  The dedup the merge must solve is the same repetition that makes a dedicated store tempting.

## Limitations (v1, FLAT `--only` only)

- **Frozen upstream + live inputs are an incoherent mix if you change an input.** The target runs
  with inputs from the *current* invocation while every other node's output is frozen from the
  last full run. If you pass a different input, upstream does not reflect it (it's snapshotted) —
  only the target sees the new value. Re-run the full workflow when inputs change.
- **`--only` freezes the branch choice.** Coalesce/optional refs resolve against the snapshot's
  branch outcome, not the branch the new inputs would take. A missing upstream is usually a loud
  unresolved-reference error, but a coalesce can silently use the snapshot's branch.
- **Binary/dunder upstream degrades + can mask the target cache.** The trace's `node_output` is
  `_sanitize_for_json`'d (bytes → `"<binary data: N bytes>"`; dunder keys dropped except
  `__metrics__`). A target that templates a binary/dunder upstream field resolves the placeholder,
  so its resolved params — and its memo `cache_key` — differ from a live run; it silently
  re-executes rather than memo-hitting. Cache-parity with a live run is scoped to
  non-binary/non-dunder upstream.
- **`--no-cache` does not defeat the snapshot.** `--no-cache` controls memo *reads*; it does not
  re-run frozen upstream. To re-run upstream, run the full workflow.
- **A `loop:` target runs one iteration and won't memo-hit.** `__loop_active__` suppresses the
  loop body's memo read, matching the engine's per-iteration re-execution.
- **A snapshot from a `degraded` run emits a loud advisory.** A degraded full run can carry partial
  upstream data (e.g. a batch host with `error_handling: continue` that dropped failed items). The
  snapshot is still used (never silently), but a WARNING advisory flips the `--only` run to
  DEGRADED. An INFO-only advisory (empty batch, loop cap) is benign and does not trigger it.
- **Same-second trace-filename collision — resolved.** Trace filenames were second-granular, so a
  full run immediately followed by an `--only` run (same second) wrote the same filename and the
  `--only` trace (excluded as a snapshot source) overwrote the full-run snapshot. Fixed by giving
  `save_to_file`'s filename microsecond granularity (`%Y%m%d-%H%M%S-%f`) — the autoload glob keys on
  the hash prefix, so the timestamp format is free to change and ordering still sorts correctly.
