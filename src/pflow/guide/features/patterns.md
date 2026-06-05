# Workflow Patterns

**Use when**: composing several steps — LLM calls, agents, or plain nodes — into a recognizable shape: fan work out and merge it, verify a result from independent angles, generate many options and narrow to the best, rank by elimination, or repeat until done. These are recipes built from pflow's primitives (`batch`, `loop`, branching), not new node types.

**Why patterns help**: an LLM call or agent asked to do everything in one pass degrades — it gets lazy (does 7 of 15 asked), grades its own work favorably, and drifts from the original goal. Each pattern splits the work across separate steps, each with its own fresh context, and recombines the results — so no single call carries the whole load. The workers can be `llm` nodes (as in the examples below), `claude-code` agents, or plain `code`/`shell`/`http` nodes — whichever fits the step. The judgment-heavy patterns (verification, generate-and-filter, tournament) usually use `llm` or `claude-code`; fan-out, classify, and loop-until-done work with any node type.

| Pattern | Shape | Built on |
|---|---|---|
| Classify-and-act | route each input to the right handler | branching |
| Fan-out-and-synthesize | split work, run in parallel, merge | `batch` + a reduce node |
| Adversarial verification | check a result with N independent skeptics | `batch` + a tally node |
| Generate-and-filter | over-generate options, then narrow | `batch` + a filter node |
| Tournament | rank by pairwise elimination rounds | `loop` |
| Loop-until-done | repeat until an outcome is reached | `loop` |

---

## Classify-and-act

A "receptionist" step decides which path an input belongs to, then the right node handles it. Use for triage (inbox: bug / refund / upgrade), moderation, or any "decide, then handle" flow.

This is branching — a classifier (`llm`/`code`) whose output drives `- next:`. See `pflow guide branching`.

## Fan-out-and-synthesize

Split a task into independent pieces, run them in parallel (each in its own context, so they don't cross-contaminate), then merge the results in one reduce step. Use for deep research (one angle per worker), multi-file audits (one worker per file), or summaries with per-source citations.

```markdown
### research-each
Research one angle per item, in parallel.
- type: llm
- prompt: "Research this angle and cite your sources: ${item}"
- batch:
    items: ${angles}
    parallel: true

### synthesize
Merge every angle into one cited report — the reduce step reads all results.
- type: llm
- prompt: "Combine these findings into one report, keeping each source:\n${research-each.results}"
```

Mechanics (the `results` array, concurrency): `pflow guide batch`.

## Adversarial verification

Don't let a result grade itself. Fan out several **independent** skeptics over the same claim — each judges against a rubric and defaults to "refuted" unless convinced — then keep the claim only on a majority. Use for fact-checking or confirming findings, where a wrong "yes" is costly.

````markdown
### verify
Judge the claim from several angles — each reviewer tries to refute it.
- type: llm
- prompt: |
    Claim: ${finding.result}
    Judge it through the ${lens} lens; try to REFUTE it against the rubric.
    Reply with a verdict ("holds" or "refuted") and a reason. Default to refuted if unsure.
- batch:
    items: [correctness, sources, logic]
    as: lens
    parallel: true

### tally
Keep the claim only if a majority of reviewers say it holds.
- type: code
- inputs:
    verdicts: ${verify.results}

```python code
verdicts: list
holds = sum(1 for v in verdicts if "holds" in str(v["response"]).lower())
result: dict = {"confirmed": holds >= 2, "holds": holds}
```
````

Keep the producer and the verifier as **different** nodes — a node checking its own output inherits its own bias.

## Generate-and-filter

Over-generate options, then narrow to the best few — going from many to a few yields better results than asking for "the best" once. Use where taste matters: names, titles, copy, design directions.

```markdown
### generate
Generate one option per angle, in parallel.
- type: llm
- prompt: "Write a product name. Angle: ${item}"
- batch:
    items: [bold, playful, technical, minimal, evocative]
    parallel: true

### pick-best
Score against a rubric, drop near-duplicates, return the top few.
- type: llm
- prompt: "Score each against {memorable, on-brand}, drop duplicates, return the top 3 with reasons:\n${generate.results}"
```

As with verification, the generator and the judge should be **different** nodes.

## Tournament

Rank a large set by **pairwise** comparison instead of scoring each one cold — head-to-head judgments are more reliable, and the loop holds the bracket so only the running order stays in context. Each round can use its own rubric. Use for ranking many candidates (resumes, designs, proposals) where absolute scores drift.

This is a `loop:` whose body judges one round and carries the winners forward. See `pflow guide loop` → the tournament worked example.

## Loop-until-done

Repeat until an outcome is reached, with no fixed count — "keep going until X." Use when the iteration count isn't known up front: hunt a flaky failure, retry until a check passes, keep searching until nothing new turns up.

This is the core `loop:` primitive. See `pflow guide loop`.

---

## Stacking patterns

The real power is composition. A thorough audit chains three: **fan out** one worker per file → **adversarially verify** each finding by trying to refute it → **loop until** a clean pass turns up nothing new — returning only confirmed issues with file and line. Build it by naming the shapes; each stage is one pattern above.

## When not to reach for a pattern

These spin up many agents and burn tokens. For a single, straightforward change, a direct node (or a plain prompt) is better. Reach for a pattern when the task is large or complex enough that splitting it across fresh contexts actually buys reliability — and use `--dry-run` to preview cost first.
