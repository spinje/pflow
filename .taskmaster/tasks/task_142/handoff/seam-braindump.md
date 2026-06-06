# Task 142 — Code-Node Seam: Handoff Braindump

Source: live build session (RSS digest workflow). Hit the two-zone gotcha firsthand.

## Root smell (confirmed)
Two zones that look alike but mean different things — two mirror symptoms, one cause:
- **#148** — `key: str = ${...}` in the YAML `- inputs:` zone → silently the string `"str = ..."`.
- **#477/#478** — `x: T = value` as a LOCAL in the code zone → misread as an orphan input.
Same root: annotation syntax is overloaded as input-declaration on *both* surfaces.

## Function syntax (Approach A) — what it fixes for free
`def run(results: list, pool_size: int): ...; return {...}`
- params vs locals is unambiguous in Python → the #478 gotcha becomes **structurally impossible**
- `return` replaces the magic `result` variable
- genuinely runnable / IDE-checkable Python (today's block is NOT — `x: T` NameErrors if run)

## Central open question, resolved: can `- inputs:` be eliminated? (A's promise)
**No, not fully.** Two hard blockers:
1. A Python param name can't carry a dotted source path — `def run(fetch.results)` is illegal,
   so any **node-output** input still needs an explicit binding line.
2. Fully-implicit deps (function reaches into a ctx bag) go **opaque** → breaks the cache key,
   execution ordering, `--validate-only`/`--dry-run`, AND the data-flow visualization.

→ Realistic landing = **HYBRID**:
   - auto-bind params whose name matches a workflow input (drop the line)
   - keep explicit `- inputs:` for node-output / nested-path / transformed / renamed edges

## Reframe (the load-bearing insight)
`- inputs:` is not redundant ceremony — it declares the **dependency EDGE**.
The signature gives names+types; `- inputs:` gives *which upstream values flow in*.
Declared edges = knowable graph = what buys caching, ordering, dry-run, and (especially) a
human-legible **visualization** of agent-written workflows. Kill the edges → the graph goes dark.

## Still open (NOT covered here)
- `next: str = "target"` dynamic routing → how it maps to a function return
- multiple return values / downstream template resolution
- `print()`/side-effect capture; `exec()`-vs-define-and-call
- migration & back-compat (can both syntaxes coexist?)
