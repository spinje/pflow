# Run From Plan

Manual entry point for the plan-to-code harness: invoke it by hand with a path to an
implementation plan (and optionally a spec). It resolves the target repo, fails fast if any
required review-lens dependency is missing or the repo has uncommitted changes, then runs the
invocation-agnostic `execute-plan` core: harden the plan (review+fix) → break it into segments →
implement every segment (segmentation is for context-window management, not review) → review-fix
the whole codebase → simplify the integrated whole → adversarially verify → open a PR.
**Target repo:** pass `repo_dir` to point at the repo where code should be written, or leave it
empty to use the git root of the current directory. The plan can live anywhere (e.g.
`~/.claude/plans/`) — it is independent of the target repo. Run against a **clean working tree**;
a fresh `git worktree` is the recommended isolation (and the only safe way to run against a repo
that has uncommitted changes).
**Prerequisites:** `gh` authenticated with push + PR rights on `origin`; the review-lens
subagents named in `plan_lenses`/`review_lenses` must exist as `.claude/agents/<name>.md` in the
target repo (preflight verifies). Claude runs on your subscription by default (no API billing;
opt into Anthropic Console billing per-node with `use_api_key: true`).

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
        input_repo_dir[/"repo_dir (string)"/]:::input
        input_plan[/"plan (string)"/]:::input
        input_spec[/"spec (string)"/]:::input
        input_progress_log[/"progress_log (string)"/]:::input
        input_base_branch[/"base_branch (string)"/]:::input
        input_work_branch[/"work_branch (string)"/]:::input
        input_plan_lenses[/"plan_lenses (string)"/]:::input
        input_review_lenses[/"review_lenses (string)"/]:::input
        input_simplify_lens[/"simplify_lens (string)"/]:::input
        input_verify_recipe[/"verify_recipe (string)"/]:::input
        input_max_review_rounds[/"max_review_rounds (integer)"/]:::input
    end
    style workflow-inputs fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4
    resolve-repo["resolve-repo (code)<br/>Resolve the TARGET repo AND absolutize the artifact paths, so everything downstr"]:::code
    preflight["preflight (code)<br/>Fail fast on two preconditions, before any agent runs: (1) every declared review"]:::code
    subgraph execute-plan-in ["execute-plan inputs"]
        execute-plan__in_plan[/"plan (string)"/]:::input
        execute-plan__in_spec[/"spec (string)"/]:::input
        execute-plan__in_progress_log[/"progress_log (string)"/]:::input
        execute-plan__in_repo_dir[/"repo_dir (string)"/]:::input
        execute-plan__in_base_branch[/"base_branch (string)"/]:::input
        execute-plan__in_work_branch[/"work_branch (string)"/]:::input
        execute-plan__in_plan_lenses[/"plan_lenses (string)"/]:::input
        execute-plan__in_review_lenses[/"review_lenses (string)"/]:::input
        execute-plan__in_simplify_lens[/"simplify_lens (string)"/]:::input
        execute-plan__in_verify_recipe[/"verify_recipe (string)"/]:::input
        execute-plan__in_max_review_rounds[/"max_review_rounds (integer)"/]:::input
    end
    style execute-plan-in fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4
    execute-plan__in_plan --> execute-plan__branch-setup
    execute-plan__in_spec --> execute-plan__branch-setup
    execute-plan__in_progress_log --> execute-plan__branch-setup
    execute-plan__in_repo_dir --> execute-plan__branch-setup
    execute-plan__in_base_branch --> execute-plan__branch-setup
    execute-plan__in_work_branch --> execute-plan__branch-setup
    execute-plan__in_plan_lenses --> execute-plan__branch-setup
    execute-plan__in_review_lenses --> execute-plan__branch-setup
    execute-plan__in_simplify_lens --> execute-plan__branch-setup
    execute-plan__in_verify_recipe --> execute-plan__branch-setup
    execute-plan__in_max_review_rounds --> execute-plan__branch-setup
    subgraph execute-plan ["execute-plan (workflow)<br/>Run the invocation-agnostic core."]
        execute-plan__branch-setup[["branch-setup (shell)<br/>Create (or reset) the work branch off the base branch, once, before any implemen"]]:::shell
        execute-plan__plan-review-fix["plan-review-fix (claude-code)<br/>Harden the plan before any code is written, in ONE agent: deploy plan-review len"]:::code
        execute-plan__breakdown["breakdown (claude-code)<br/>Group the (now hardened) plan's top-level phases into ordered agent-handoff segm"]:::code
        execute-plan__group-tick["group-tick (code)<br/>Hold the segment index."]:::code
        subgraph execute-plan__implement-chunk-in ["implement-chunk inputs"]
            execute-plan__implement-chunk__in_plan[/"plan (string)"/]:::input
            execute-plan__implement-chunk__in_spec[/"spec (string)"/]:::input
            execute-plan__implement-chunk__in_delta[/"delta (string)"/]:::input
            execute-plan__implement-chunk__in_progress_log[/"progress_log (string)"/]:::input
            execute-plan__implement-chunk__in_repo_dir[/"repo_dir (string)"/]:::input
        end
        style execute-plan__implement-chunk-in fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4
        execute-plan__implement-chunk__in_plan --> execute-plan__implement-chunk__implement
        execute-plan__implement-chunk__in_spec --> execute-plan__implement-chunk__implement
        execute-plan__implement-chunk__in_delta --> execute-plan__implement-chunk__implement
        execute-plan__implement-chunk__in_progress_log --> execute-plan__implement-chunk__implement
        execute-plan__implement-chunk__in_repo_dir --> execute-plan__implement-chunk__implement
        subgraph execute-plan__implement-chunk ["implement-chunk (workflow)<br/>The loop worker: a whole sub-workflow per segment (implement fork only — no revi"]
            execute-plan__implement-chunk__implement["implement (claude-code)<br/>Fresh implement fork: reads {plan, spec, progress log} by path, implements ONLY "]:::code
            execute-plan__implement-chunk__happy-check["happy-check (claude-code)<br/>Always-on final self-review of the just-implemented segment, run as a follow-up "]:::code
            execute-plan__implement-chunk__report-commits["report-commits (code)<br/>Surface a clean integer commit count for the parent loop, guarding the claude-co"]:::code
            execute-plan__implement-chunk__implement --> execute-plan__implement-chunk__happy-check
            execute-plan__implement-chunk__happy-check --> execute-plan__implement-chunk__report-commits
        end
        style execute-plan__implement-chunk fill:#808080,fill-opacity:0.21,stroke:#999
        subgraph execute-plan__implement-chunk-out ["implement-chunk outputs"]
            execute-plan__implement-chunk__out_commits_made(["commits_made"]):::output
        end
        style execute-plan__implement-chunk-out fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4
        execute-plan__implement-chunk__report-commits --> execute-plan__implement-chunk__out_commits_made
        execute-plan__in_plan --> execute-plan__implement-chunk__in_plan
        execute-plan__in_spec --> execute-plan__implement-chunk__in_spec
        execute-plan__group-tick --> execute-plan__implement-chunk__in_delta
        execute-plan__in_progress_log --> execute-plan__implement-chunk__in_progress_log
        execute-plan__in_repo_dir --> execute-plan__implement-chunk__in_repo_dir
        execute-plan__check-groups{"check-groups (code)<br/>Decide: loop back for the next segment, or (once all segments are implemented) a"}:::decision
        execute-plan__review-tick["review-tick (code)<br/>Hold the review-round counter for the whole-codebase review-fix loop."]:::code
        execute-plan__review-round["review-round (claude-code)<br/>One whole-codebase review-fix round (a fresh agent): deploy the relevant lenses "]:::code
        execute-plan__check-rounds{"check-rounds (code)<br/>Enforce the loop condition: continue only if the agent wants another round AND w"}:::decision
        execute-plan__simplify["simplify (claude-code)<br/>One focused simplicity pass over the COMPLETE implemented + reviewed change, run"]:::code
        execute-plan__verify["verify (claude-code)<br/>Adversarial verification of the fully-implemented, reviewed, and simplified resu"]:::code
        execute-plan__push["push (code)<br/>Push the work branch to origin so `ship` can open a PR."]:::code
        execute-plan__ship["ship (claude-code)<br/>Open a PR for the work branch against the base branch."]:::code
        execute-plan__branch-setup --> execute-plan__plan-review-fix
        execute-plan__plan-review-fix --> execute-plan__breakdown
        execute-plan__breakdown --> execute-plan__group-tick
        execute-plan__implement-chunk__out_commits_made --> execute-plan__check-groups
        execute-plan__check-groups -->|group-tick| execute-plan__group-tick
        execute-plan__check-groups -->|review-tick| execute-plan__review-tick
        execute-plan__check-groups -->|simplify| execute-plan__simplify
        execute-plan__review-tick --> execute-plan__review-round
        execute-plan__review-round --> execute-plan__check-rounds
        execute-plan__check-rounds -->|review-tick| execute-plan__review-tick
        execute-plan__check-rounds -->|simplify| execute-plan__simplify
        execute-plan__simplify --> execute-plan__verify
        execute-plan__verify --> execute-plan__push
        execute-plan__push --> execute-plan__ship
    end
    style execute-plan fill:#808080,fill-opacity:0.14,stroke:#999
    subgraph execute-plan-out ["execute-plan outputs"]
        execute-plan__out_pr_url(["pr_url"]):::output
        execute-plan__out_summary(["summary"]):::output
        execute-plan__out_segments(["segments"]):::output
    end
    style execute-plan-out fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4
    execute-plan__ship --> execute-plan__out_pr_url
    execute-plan__check-groups --> execute-plan__out_summary
    execute-plan__breakdown --> execute-plan__out_segments
    resolve-repo --> execute-plan__in_plan
    resolve-repo --> execute-plan__in_spec
    resolve-repo --> execute-plan__in_progress_log
    resolve-repo --> execute-plan__in_repo_dir
    input_repo_dir --> resolve-repo
    input_plan --> resolve-repo
    input_spec --> resolve-repo
    input_progress_log --> resolve-repo
    input_plan_lenses --> preflight
    input_review_lenses --> preflight
    input_simplify_lens --> preflight
    input_base_branch --> execute-plan__in_base_branch
    input_work_branch --> execute-plan__in_work_branch
    input_plan_lenses --> execute-plan__in_plan_lenses
    input_review_lenses --> execute-plan__in_review_lenses
    input_simplify_lens --> execute-plan__in_simplify_lens
    input_verify_recipe --> execute-plan__in_verify_recipe
    input_max_review_rounds --> execute-plan__in_max_review_rounds
    subgraph workflow-outputs ["workflow outputs"]
        out_pr_url(["pr_url"]):::output
        out_summary(["summary"]):::output
    end
    style workflow-outputs fill:#808080,fill-opacity:0.04,stroke:#999,stroke-dasharray:4 4
    execute-plan__out_pr_url --> out_pr_url
    execute-plan__out_summary --> out_summary
    resolve-repo --> preflight
```
