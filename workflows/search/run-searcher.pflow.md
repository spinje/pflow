# Run searcher

Run one pflow codebase searcher (`pflow-codebase-searcher` — or any other read-only persona) as a Codex/GPT-sol subagent and return its cited answer. The second capacity pool and second model family for the orchestration's highest-frequency agent type: use it for cross-model verification (same question to this AND the native opus searcher, caller compares) or as capacity offload when Claude limits bite. Codex-only by design — the Claude side already has a better native path (the Agent tool with follow-up/resume), so a claude branch here would be dead scaffolding.

## Inputs

### agent

Name of the persona to run, resolved to `${cwd}/.claude/agents/{agent}.md` (canonical source — the generated `.codex` twins are build artifacts). Typically `pflow-codebase-searcher`; any read-only agent definition works. A missing file fails loudly.

- type: string
- required: true

### prompt

The search or verification task, phrased exactly as you would brief the native searcher — include DEPTH (quick | medium | thorough) and the report-shape ask (e.g. "report each claim as CONFIRMED (cite file:line) or REFUTED (state what you checked)").

- type: string
- required: true

### effort

Model tier — the reasoning lever, distinct from the DEPTH you write into the prompt (DEPTH = how broadly the agent searches; this = how hard the model thinks).

* `low` → **terra** (sonnet-tier), medium reasoning — mechanical/quick lookups ("which file defines X"). Search, not judgment, so sonnet-tier is appropriate; medium reasoning is the sensible floor.
* `medium` → **sol**, medium reasoning — ordinary investigation.
* `high` → **sol**, high reasoning (**default**) — real verification / cross-model adversarial checks.

- type: string
- required: false
- default: high

### cwd

Optional override: path of the repo or worktree to search. **Leave empty to auto-detect** the git top-level of wherever pflow is invoked (worktree-correct — each worktree reports its own root). Pass an explicit path to target a DIFFERENT checkout than the one you're standing in.

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

### load-persona

Load the persona body (frontmatter stripped) and resolve the `effort` tier to a codex `(model, reasoning_effort)` pair: `low` → terra/medium (mechanical lookups), `medium` → sol/medium, `high` → sol/high (verification). The persona frontmatter's own model/effort is intentionally NOT used here — `effort` is the single per-call control (searchers vary by call; review lenses, by contrast, stay frontmatter-pinned). Fails loudly on a missing persona file or an unknown effort value.

- type: code
- inputs:
    agent: ${agent}
    cwd: ${resolve-cwd.stdout}
    effort: ${effort}

```python code
from pathlib import Path

agent: str
cwd: str
effort: str

# effort tier -> (codex launch model, reasoning_effort). low = sonnet-tier terra at
# medium reasoning (a sensible floor for search); medium/high = sol (opus/fable-tier)
# for judgment/verification.
TIER = {
    "low": ("gpt-5.6-terra", "medium"),
    "medium": ("gpt-5.6-sol", "medium"),
    "high": ("gpt-5.6-sol", "high"),
}
if effort not in TIER:
    raise ValueError(f"Unknown effort {effort!r} (expected low|medium|high)")
model, reasoning = TIER[effort]

path = Path(cwd) / ".claude" / "agents" / f"{agent}.md"
if not path.is_file():
    raise FileNotFoundError(f"No persona file for agent {agent!r} at {path}")

text = path.read_text()
body = text.split("---", 2)[2].strip() if text.startswith("---") else text.strip()

result: dict = {"persona": body, "model": model, "effort": reasoning}
```

### run

The searcher runs read-only in the repo — its persona as system prompt, findings grounded in citations. The 3600s timeout is a hang detector, not a pace expectation (searcher queries typically run 2–10 min).

- type: agent
- backend: codex
- model: ${load-persona.result.model}
- cwd: ${resolve-cwd.stdout}
- sandbox: read-only
- approval_policy: never
- timeout: 3600
- system_prompt: ${load-persona.result.persona}
- config:
    model_reasoning_effort: ${load-persona.result.effort}

```prompt
${prompt}

You are in a read-only sandbox: answer by reading code, never by running tests or writing files. Ground every claim in file:line citations.
```

## Outputs

### answer

The searcher's cited findings — the caller owns the conclusions and any comparison against a second channel.

- source: ${run.result}
- stdout: true
