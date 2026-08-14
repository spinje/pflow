# Run review lenses

Fan the pflow review battery out as parallel read-only subagents (Codex/GPT-sol by default, Claude optional), then merge the findings into one deduplicated report that flags where independent lenses converge. The merge preserves; it never adjudicates — verification and verdicts stay with the caller (the deep-review flow). Lenses run blind to each other; only the merge step sees all outputs, and no agent ever sees the merged report. Execution-based lenses (`review-falsifier`) never run here — this fan-out is read-only by contract.

## Inputs

### lenses

Which review specialists to run. Each entry is either a bare agent name (`"review-silent-failures"`) or an object `{name, target}` overriding the global `review_target` for that lens (e.g. pointing the test-fidelity lens at just the test files). Names resolve to `${cwd}/.claude/agents/{name}.md`; a missing file fails the run loudly rather than silently shrinking the battery.

- type: array
- required: true

### review_target

What every lens reviews, stated as an instruction (e.g. "Review all changes on this branch vs main for task 94 (LLM model listing)." or "Review the changes introduced by commit abc123."). Passed verbatim to each lens unless that lens carries its own `target` override.

- type: string
- required: true

### provider

Which engine runs ALL lenses: `codex` (GPT sol via the Codex CLI) or `claude` (Claude Code, opus). One provider per run — no per-lens routing. Codex is the default deliberately: a same-family reviewer shares the author's blind spots, and cross-model diversity is the point of this dispatch.

- type: string
- required: false
- default: codex

### cwd

Optional override: path of the repo or worktree to review. **Leave empty to auto-detect** the git top-level of wherever pflow is invoked (worktree-correct — each worktree reports its own root). Pass an explicit path to target a DIFFERENT checkout than the one you're standing in.

- type: string
- required: false
- default: ""

## Steps

### resolve-cwd

Compute the effective working directory once, up front. If `cwd` was passed, use it (resolved to absolute); otherwise auto-detect the git top-level of the directory pflow was invoked from. Relative `cwd` values resolve against the invocation dir, never the workflow file — so a fixed `../..` can't anchor to the repo root; this node removes that dependency and makes the default work from any subdirectory of a checkout. A bad explicit override fails loudly here (cd fails → non-zero exit).

- type: shell
- inputs:
    cwd_override: ${cwd}

```shell command
if [ -n "${cwd_override}" ]; then
  cd "${cwd_override}" && pwd
else
  git rev-parse --show-toplevel 2>/dev/null || pwd
fi
```

### load-lenses

Normalize the lens list and load each persona from its canonical `.claude/agents/*.md` file (single source of truth — the generated `.codex` twins are build artifacts). Each lens's **frontmatter is the runtime contract**: its `model`/`effort` drive the launch. Codex maps contract tiers per ORCHESTRATION.md's table (opus/fable → `gpt-5.6-sol`, sonnet → `gpt-5.6-terra`) and passes effort through `model_reasoning_effort`; Claude uses the model alias as-is and approximates effort as a thinking budget (pflow's claude backend has no effort parameter — this mapping is the workflow's own). All lenses go to the chosen provider's run node (the other receives an empty list and no-ops — two nodes exist only because pflow rejects one provider's parameters on the other's launch). Fails loudly on an unknown provider, a missing persona file, or an execution-based lens (`review-falsifier` needs write/execute access this read-only fan-out never grants).

- type: code
- inputs:
    lenses: ${lenses}
    provider: ${provider}
    review_target: ${review_target}
    cwd: ${resolve-cwd.stdout}

```python code
from pathlib import Path

lenses: list
provider: str
review_target: str
cwd: str

if provider not in ("codex", "claude"):
    raise ValueError(f"Unknown provider {provider!r} (expected codex|claude)")

EXECUTION_LENSES = {"review-falsifier"}

# Contract tier -> codex launch model (mirror of ORCHESTRATION.md's mapping table)
CODEX_MODELS = {"opus": "gpt-5.6-sol", "fable": "gpt-5.6-sol", "sonnet": "gpt-5.6-terra"}
# Effort -> claude thinking budget (approximation; claude backend has no effort param)
THINKING_TOKENS = {"low": 4000, "medium": 8000, "high": 16000, "xhigh": 32000, "max": 32000}

agents_dir = Path(cwd) / ".claude" / "agents"
items: list = []

for entry in lenses:
    spec = {"name": entry} if isinstance(entry, str) else dict(entry)
    name = spec["name"]
    if name in EXECUTION_LENSES:
        raise ValueError(f"Lens {name!r} is execution-based and cannot run in the read-only fan-out — launch it directly")
    path = agents_dir / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"No persona file for lens {name!r} at {path}")
    text = path.read_text()
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        meta = {}
        for line in fm.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"')
        body = body.strip()
    else:
        meta, body = {}, text.strip()

    tier = meta.get("model", "opus")
    effort = meta.get("effort", "high")
    if provider == "codex":
        if tier not in CODEX_MODELS:
            raise ValueError(f"Lens {name!r} frontmatter model {tier!r} has no codex mapping")
        model = CODEX_MODELS[tier]
    else:
        model = tier

    items.append({
        "name": name,
        "persona": body,
        "model": model,
        "effort": effort,
        "max_thinking_tokens": THINKING_TOKENS.get(effort, 16000),
        "target": spec.get("target", review_target),
    })

result: dict = {
    "codex_items": items if provider == "codex" else [],
    "claude_items": items if provider == "claude" else [],
}
```

### run-codex

Every codex-routed lens runs here concurrently as a read-only sol agent — its persona as system prompt, the repo as cwd so it reads REVIEW-PROTOCOL.md and the CLAUDE.md files itself. `continue` error handling: one dead lens never kills the battery; it surfaces as a named coverage gap instead. The 3600s timeout is a hang detector, not a pace expectation.

- type: agent
- backend: codex
- model: ${item.model}
- cwd: ${resolve-cwd.stdout}
- sandbox: read-only
- approval_policy: never
- timeout: 3600
- system_prompt: ${item.persona}
- config:
    model_reasoning_effort: ${item.effort}
- batch:
    items: ${load-lenses.result.codex_items}
    parallel: true
    max_concurrent: 12
    error_handling: continue

```prompt
Code review. ${item.target}

Follow .claude/agents/REVIEW-PROTOCOL.md (read it first). Your lens instructions are in your system prompt. Produce your findings in the protocol's output format.

You are in a read-only sandbox: verify by reading code, never by running tests or writing files — test execution is the caller's job. uv.lock is not a review target — a lockfile change is a signal of a dependency change, not code to critique.
```

### run-claude

Identical contract for claude-routed lenses (empty and skipped under the codex default). Read-only is enforced by the tool allow-list — the same `Glob, Grep, Read, Bash` set the battery's agent definitions declare.

- type: agent
- backend: claude
- model: ${item.model}
- cwd: ${resolve-cwd.stdout}
- allowed_tools:
    - Read
    - Grep
    - Glob
    - Bash
- timeout: 3600
- system_prompt: ${item.persona}
- max_thinking_tokens: ${item.max_thinking_tokens}
- batch:
    items: ${load-lenses.result.claude_items}
    parallel: true
    max_concurrent: 12
    error_handling: continue

```prompt
Code review. ${item.target}

Follow .claude/agents/REVIEW-PROTOCOL.md (read it first). Your lens instructions are in your system prompt. Produce your findings in the protocol's output format.

Verify by reading code, never by running tests or writing files — test execution is the caller's job. uv.lock is not a review target — a lockfile change is a signal of a dependency change, not code to critique.
```

### collect

Strip each result down to `{lens, provider, findings}` — batch results embed the full item, and the multi-thousand-token personas must not reach the merge as noise. Failed lenses become named `gaps` so the report can state coverage honestly.

- type: code
- inputs:
    codex_results: ${run-codex.results}
    codex_errors: ${run-codex.errors}
    claude_results: ${run-claude.results}
    claude_errors: ${run-claude.errors}

```python code
codex_results: list
codex_errors: list
claude_results: list
claude_errors: list

findings: list = []
gaps: list = []

for provider_name, results, errors in (
    ("codex", codex_results, codex_errors),
    ("claude", claude_results, claude_errors),
):
    for r in results:
        item = r.get("item", {}) if isinstance(r, dict) else {}
        findings.append({
            "lens": item.get("name", "unknown"),
            "provider": provider_name,
            "findings": r.get("result") if isinstance(r, dict) else str(r),
        })
    for e in errors:
        item = e.get("item", {}) if isinstance(e, dict) else {}
        name = item.get("name", "unknown") if isinstance(item, dict) else "unknown"
        gaps.append({
            "lens": name,
            "provider": provider_name,
            "error": str(e.get("error", e)) if isinstance(e, dict) else str(e),
        })

result: dict = {"findings": findings, "gaps": gaps}
```

### merge

Merge, don't adjudicate: deduplicate true duplicates, preserve every distinct finding with its evidence, and flag convergence. Runs as a codex agent (no API key is configured for plain `llm` nodes, and this keeps the whole workflow on one auth surface); it needs no repository access — everything it merges arrives in the prompt.

- type: agent
- backend: codex
- model: gpt-5.6-sol
- sandbox: read-only
- approval_policy: never
- timeout: 1800

```prompt
You are merging the outputs of independent code-review specialists ("lenses") that each reviewed the same change through a different blindspot lens. Produce ONE consolidated markdown report.

Rules — you merge, you never adjudicate:
- PRESERVE every distinct finding: its severity as the lens stated it, its file:line references, its evidence, and which lens raised it. Never drop, soften, re-grade, verify, or dispute a finding.
- DEDUPLICATE only true duplicates (same defect at the same location). Merge them into one entry citing every lens that raised it, keeping the strongest evidence.
- CONVERGENCE is the highest-value signal: when 2+ lenses independently hit the same defect or the same code area, flag it explicitly. A lens's "cross-lens handoff" mention counts toward convergence with the owning lens's own finding.
- Preserve each lens's verified-clean assertions — they are evidence, not filler.
- Name every coverage gap: a lens listed in the gaps input produced no review; the report must say so rather than imply full coverage.
- Do not read or edit any files in the repository. Your only job is to merge the findings and gaps without judgement, or verification in code.
- Only respond with your final report, nothing else.

Report structure:
# Merged Review Report
## Convergent findings  (2+ lenses; lead with these)
## Critical / ## Warnings / ## Suggestions  (remaining findings by stated severity, each tagged with its lens)
## Verified clean  (per lens, condensed)
## Coverage  (lenses that ran and their provider; gaps named explicitly)

Lens outputs:
${collect.result.findings}

Failed lenses (coverage gaps):
${collect.result.gaps}
```

## Outputs

### report

The consolidated review report — the workflow's product. The caller (the gate-runner / deep-review flow) verifies and adjudicates from here.

- source: ${merge.result}
- stdout: true

### raw

The per-lens findings and gaps exactly as collected (personas stripped) — the audit trail proving the merge dropped nothing. Terminal data: produced after all agents finish, never fed back to any agent.

- source: ${collect.result}
