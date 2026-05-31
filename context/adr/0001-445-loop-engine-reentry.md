# Loop config executes by engine re-entry, not by desugaring to two nodes

Status: accepted

The `loop:` config block (issue #445) gives a step condition-terminated repetition
(`while:` over the step's own typed output, capped by `max_iterations`). The issue
proposed implementing it as **parse-time sugar that desugars into a two-node
backward-edge worker/checker composition**. We rejected that and instead make the
**engine re-enter the same node**: after a loop-configured node runs, the engine
evaluates the condition against the node's fresh output and, if truthy and under the
cap, sets the current node back to itself (re-running it) rather than advancing to
its successor. One authored node stays one node end-to-end.

## Considered options

1. **Desugar to two visible nodes** (the issue's plan). Reuses the existing
   backward-edge loop machinery, but the synthesized checker node leaks into every
   user-facing surface (trace, `--report`, mermaid, progress) — pflow has no
   mechanism to hide a synthesized node, so the author writes one node and sees two.
   Also requires synthesizing a counter node and edges. Rejected.
2. **A `loop_executor.py` that re-runs the node in an inner loop** (mirroring
   `batch_executor.py`). One node, but it must re-implement the
   anti-stale-cache/visit semantics the engine already owns — divergent duplicate
   logic. Rejected.
3. **Engine re-entry** (chosen). One node; reuses the engine's existing
   visit-guard + revisit-cache-bypass (the exact machinery a hand-written
   backward-edge loop relies on), so re-entry is byte-for-byte indistinguishable
   from a backward-edge revisit. Smallest net surface: a `continue` in the
   graph-walk plus the config/validation/condition-evaluation wiring.

## Consequences

- This is a deliberate deviation from the path the issue documents; a reader
  expecting the desugar will wonder where the second node went. That is the point —
  re-entry is what keeps it one node.
- `loop:` is **not** "zero new runtime" as the issue claimed. Re-entry is cheap, but
  the condition needs new machinery pflow never had: a truthiness evaluator
  restricted to typed outputs (string-typed sources are rejected at parse time so
  raw stdout like `"0\n"` can't invert the loop), an absent-aware condition
  resolver, a `while:`-grammar validator rejecting comparison operators, a
  self-reference carve-out in data-flow validation, `${__iteration__}` injection +
  registration, dry-run/`plan.py` parity, and a loop-scoped memo-read suppression
  guard for sub-workflow bodies.
- `max_iterations` is bounded by the hard `MAX_NODE_VISITS` guard (default 100) and
  is validated against it; reaching the cap is a non-degrading INFO advisory.
- `loop:` and `batch:` are mutually exclusive on one step.
