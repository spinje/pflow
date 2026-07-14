# Parallel Planner with Review

Autonomous loop that triages open GitHub issues, implements and reviews the
unblocked ones in parallel, opens a PR for each that passes review, then repeats
— picking up newly-unblocked work each cycle — until nothing is left or a cycle
cap is hit. This file is the entry point; every node's description explains its
own role and why it is that node type.
**The loop.** The orchestrator repeats the whole `run-cycle` sub-workflow with a
declarative `loop:` block until the cycle reports no planned issues, or
`max_cycles` caps it. It converges because `run-cycle`'s `open-prs` step strips
the `agent-ready` label from handled issues, shrinking the pool each cycle until
empty.
**Before running.** `gh` authenticated with push + PR rights on `origin`; the
labels `agent-ready` and `agent-needs-human` must exist. Opt issues in by
labelling them `agent-ready` — if none are, the loop correctly no-ops on cycle
one. Launch from anywhere inside the repo (`find-repo` resolves the root via
`git rev-parse`).
**How it composes.** Three nested workflows: this orchestrator →
`run-cycle/run-cycle.pflow.md` (one plan→implement→review→open-PRs cycle) →
`run-cycle/implement-and-review-one/` (the per-issue body, fanned out in parallel).
**Two caveats.** (1) Work opens a *PR*, not a merge — a dependency isn't resolved
until a human merges its PR, so cross-cycle unblocking is weaker than
merge-to-main (best for independent issues). (2) Each issue is attempted once; a
review requesting changes relabels it `agent-needs-human` rather than
re-attempting, so the swarm never spins on a hard problem.

```mermaid
graph TD
    classDef code fill:#D5E8D4,stroke:#82B366,color:#000
    classDef llm fill:#E8D5F5,stroke:#7B2D8E,color:#000
    classDef shell fill:#DAE8FC,stroke:#6C8EBF,color:#000
    classDef mcp fill:#FFE6CC,stroke:#D79B00,color:#000
    classDef writefile fill:#F8CECC,stroke:#B85450,color:#000
    classDef workflow fill:#FFF2CC,stroke:#D6B656,color:#000
    classDef decision fill:#F5F5F5,stroke:#666666,color:#000
    classDef input fill:#F5F5F5,stroke:#666666,stroke-dasharray:5 5,color:#000
    classDef output fill:#E8E8E8,stroke:#666666,color:#000
    subgraph workflow-inputs ["workflow inputs"]
        input_base_branch[/"base_branch (string)"/]:::input
        input_max_issues[/"max_issues (integer)"/]:::input
        input_max_cycles[/"max_cycles (integer)"/]:::input
    end
    style workflow-inputs fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4
    subgraph run-cycle-in ["run-cycle inputs"]
        run-cycle__in_base_branch[/"base_branch (string)"/]:::input
        run-cycle__in_max_issues[/"max_issues (integer)"/]:::input
    end
    style run-cycle-in fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4
    run-cycle__in_base_branch --> run-cycle__find-repo
    run-cycle__in_max_issues --> run-cycle__find-repo
    subgraph run-cycle ["run-cycle (workflow)<br/>⟳ while issues_planned · ≤ max_cycles"]
        run-cycle__find-repo[["find-repo (shell)"]]:::shell
        run-cycle__fetch-issues[["fetch-issues (shell)"]]:::shell
        run-cycle__plan(["plan (llm)"]):::llm
        run-cycle__gate["gate (code)"]:::code
        subgraph run-cycle__implement-and-review-each-in ["implement-and-review-each inputs"]
            run-cycle__implement-and-review-each__in_issue[/"issue (object)"/]:::input
            run-cycle__implement-and-review-each__in_base_branch[/"base_branch (string)"/]:::input
            run-cycle__implement-and-review-each__in_repo_dir[/"repo_dir (string)"/]:::input
        end
        style run-cycle__implement-and-review-each-in fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4
        run-cycle__implement-and-review-each__in_issue --> run-cycle__implement-and-review-each__implement
        run-cycle__implement-and-review-each__in_base_branch --> run-cycle__implement-and-review-each__implement
        run-cycle__implement-and-review-each__in_repo_dir --> run-cycle__implement-and-review-each__implement
        subgraph run-cycle__implement-and-review-each ["implement-and-review-each (parallel x|plan|)"]
            run-cycle__implement-and-review-each__implement["implement (agent)"]:::code
            run-cycle__implement-and-review-each__check-commits["check-commits (code)"]:::code
            run-cycle__implement-and-review-each__review["review (agent)"]:::code
            run-cycle__implement-and-review-each__implement --> run-cycle__implement-and-review-each__check-commits
            run-cycle__implement-and-review-each__check-commits -->|review| run-cycle__implement-and-review-each__review
        end
        style run-cycle__implement-and-review-each fill:#808080,fill-opacity:0.21,stroke:#999
        subgraph run-cycle__implement-and-review-each-out ["implement-and-review-each outputs"]
            run-cycle__implement-and-review-each__out_branch(["branch"]):::output
            run-cycle__implement-and-review-each__out_commits_made(["commits_made"]):::output
            run-cycle__implement-and-review-each__out_verdict(["verdict"]):::output
            run-cycle__implement-and-review-each__out_summary(["summary"]):::output
        end
        style run-cycle__implement-and-review-each-out fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4
        run-cycle__implement-and-review-each__implement --> run-cycle__implement-and-review-each__out_branch
        run-cycle__implement-and-review-each__implement --> run-cycle__implement-and-review-each__out_commits_made
        run-cycle__implement-and-review-each__review --> run-cycle__implement-and-review-each__out_verdict
        run-cycle__implement-and-review-each__implement --> run-cycle__implement-and-review-each__out_summary
        run-cycle__plan --> run-cycle__implement-and-review-each__in_issue
        run-cycle__find-repo --> run-cycle__implement-and-review-each__in_repo_dir
        run-cycle__in_base_branch --> run-cycle__implement-and-review-each__in_base_branch
        run-cycle__open-prs["open-prs (agent)"]:::code
        run-cycle__find-repo --> run-cycle__fetch-issues
        run-cycle__fetch-issues --> run-cycle__plan
        run-cycle__plan --> run-cycle__gate
        run-cycle__gate -->|implement-and-review-each| run-cycle__implement-and-review-each
        run-cycle__implement-and-review-each__out_branch --> run-cycle__open-prs
        run-cycle__implement-and-review-each__out_commits_made --> run-cycle__open-prs
        run-cycle__implement-and-review-each__out_verdict --> run-cycle__open-prs
        run-cycle__implement-and-review-each__out_summary --> run-cycle__open-prs
    end
    style run-cycle fill:#808080,fill-opacity:0.14,stroke:#999
    subgraph run-cycle-out ["run-cycle outputs"]
        run-cycle__out_issues_planned(["issues_planned"]):::output
        run-cycle__out_prs_opened(["prs_opened"]):::output
    end
    style run-cycle-out fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4
    run-cycle__plan --> run-cycle__out_issues_planned
    run-cycle__open-prs --> run-cycle__out_prs_opened
    summarize["summarize (code)"]:::code
    input_base_branch --> run-cycle__in_base_branch
    input_max_issues --> run-cycle__in_max_issues
    subgraph workflow-outputs ["workflow outputs"]
        out_summary(["summary"]):::output
    end
    style workflow-outputs fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4
    summarize --> out_summary
    run-cycle__out_issues_planned --> summarize
    run-cycle__out_prs_opened --> summarize
```
