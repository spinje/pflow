pflow — workflow execution system. Chains nodes (http, shell, llm, code, file, mcp, claude-code)
that pass data via `${...}` templates. Write `.pflow.md` files, run them, iterate.

First Action:

Check for existing workflows before building:

  pflow find "what user wants to do or build"

The output includes guidance on what to do based on match confidence.

No match?
  Need an external service?  → `pflow mcp list <keyword>` or `pflow mcp find "description"`
  1-2 operations             → run directly with `pflow probe <tool> param=value`
  3+ operations              → build a workflow: start with `pflow guide core`

Running Workflows:

  pflow ./workflow.pflow.md param1=value1    Run from file
  pflow my-workflow param1=value1            Run saved workflow

If execution succeeds, present results concisely. Do not re-run.

Run Options:
  --only <node>         Re-run one node against the last full run's snapshot (upstream reused, not re-run; needs a prior run)
  --no-cache            Bypass pflow memo-cache reads
  --report              Generate per-node execution report
  -o, --output-key <key>  Extract specific output
  --validate-only       Validate without executing
  --dry-run             Preview cache/execute plan + cost/duration estimates (no execution)
  --output-format json  JSON output for piping
  -p, --print           Minimal output (suppress progress)

Guide Topics:

Load tailored content: `pflow guide <topic> <topic>` (prefer combining nodes and features in one command: `pflow guide core http llm batch`)

Topics are already condensed to the minimum — read each in full. Truncating backfires: you miss format rules, guess wrong, and spend more tokens rewriting than you saved.

Nodes:
  http             JSON REST APIs
  llm              LLM inference (summarize, interpret, decide)
  claude-code      Agentic coding in a repository (edit, test, debug)
  code             Python data transformation (filter, reshape, compute)
  shell            Shell commands and CLI tools (git, curl, docker)
  file             File read/write
  mcp              MCP service integrations (Slack, GitHub, Postgres, ...)

Features — when the user says X, load topic Y:
  batch            Same operation on N items
                   → "each", "for every", "in parallel", "N at a time", "one at a time / in order"
  loop             Repeat until a condition is met, carrying state
                   → "loop until X", "repeat while", "keep refining until good", "poll until ready", "run rounds until one remains"
  branching        Conditional paths and routing
                   → "if X then Y", "classify and route", "pick a path based on data"
  error-handling   Retry, fallback, recover from failures
                   → "retry on failure", "fall back if X fails", "handle the error", "undo on failure"
  approval         Human-in-the-loop gates — pause for a yes/no or a decision
                   → "ask before sending", "confirm before deploying", "let me approve it", "escalate to me if unsure"
  resume           Continue a failed/interrupted run from the step that failed, or answer a paused approval gate by its token
                   → "it failed halfway", "resume the run", "don't re-run the whole thing", "approve the paused run", "it exited 4 with a resume token"
  sub-workflows    Reusable composition, bounded iteration
                   → "reuse this", "same validation as X", "iterate over a fixed count"
  prompt-caching   Provider prompt caching, ## Cache, prompt_cache:
                   → "cache prompts", "reduce LLM cost", "speed up repeated calls"
  patterns         Multi-step LLM/agent recipes — fan-out, verify, generate-filter, tournament
                   → "fan out and combine", "verify from multiple angles", "rank/tournament", "generate and pick the best", "orchestrate steps"
  ui               Show the user a workflow as a LIVE visual canvas while you build it (Mermaid diagram on request)
                   → "show me the workflow", "let me see/watch it build", "open the UI", "make a mermaid diagram"

Start here:
  core             Framework fundamentals — how to design and build workflows

Workflow-scoped: `pflow guide ./workflow.pflow.md` auto-detects relevant topics.

When to load the guide:
  Building a new workflow           → `pflow guide core` + relevant node/feature topics
  Modifying an existing workflow    → `pflow guide core ./workflow.pflow.md` (auto-detects topics)
  Running into errors               → read the error first (includes fix suggestions). For deeper inspection: `pflow report`

All commands support `--help` for detailed usage.
