# The Graph model carries primitives only; pattern and cycle analysis is a separate optional layer

The Graph model represents only structural primitives — nodes, edges, Containers, and first-class Loop metadata. Higher-level interpretation is deliberately NOT in the model or the renderers: recognizing composite patterns (tournament, fan-out-and-synthesize, adversarial-verify, etc.) and detecting/containerizing strongly-connected components (hand-wired backward-edge loops) belong to a separate, optional analysis layer that consumes the Graph model and emits annotations. That layer has not been built.

We chose this because a pattern is an *interpretation* — heuristic, ambiguous, intent-laden (a fan-out + reduce is structurally identical for "verify" and "synthesize") — not a *fact* the IR declares. Baking it into the model would put guesses where facts live; baking it into renderers would make each renderer re-implement the heuristic and diverge. By the deletion test, an analysis layer with no consumer today would be a shallow pass-through, so it is not built now.

The model's only obligations toward that future layer, all of which it already meets: keep structural edges (including back-edges) faithful so SCC detection can run later; keep one general Container record so a detected cycle is expressible without a new shape; and carry an open `annotations` slot per node/Container so declared-or-inferred semantics have a home (wiring author-declared annotations end-to-end additionally needs a future carve-out in the validator's unknown-param check — not in scope here).

Recorded so future architecture reviews do not re-suggest building pattern or SCC recognition into the model itself.
