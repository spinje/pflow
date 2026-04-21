pflow — workflow execution system. Chains nodes (http, shell, llm, code, file, mcp)
through a shared data store. Write `.pflow.md` files, run them, iterate.

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
  --only <node>         Run just this node (upstream cached, downstream skipped)
  --no-cache            Force fresh execution (bypass cache)
  --report              Generate per-node execution report
  -o, --output-key <key>  Extract specific output
  --validate-only       Validate without executing
  --dry-run             Preview cache/execute plan + cost/duration estimates (no execution)
  --output-format json  JSON output for piping
  -p, --print           Minimal output (suppress progress)

Guide Topics:

Load tailored content: `pflow guide <topic> <topic>` (prefer combining nodes and features in one command: `pflow guide core http llm batch`)

Nodes:
  http             JSON REST APIs
  llm              LLM inference (summarize, interpret, decide)
  code             Python data transformation (filter, reshape, compute)
  shell            Shell commands and CLI tools (git, curl, docker)
  file             File read/write
  mcp              MCP service integrations (Slack, GitHub, Postgres, ...)

Features — when the user says X, load topic Y:
  batch            Same operation on N items
                   → "each", "for every", "in parallel", "N at a time"
  branching        Conditional paths, error handling
                   → "if X then Y", "handle failures", "retry on error"
  sub-workflows    Reusable sub-workflow composition
                   → "reuse this", "same validation as X"

Start here:
  core             Framework fundamentals — how to design and build workflows

Workflow-scoped: `pflow guide ./workflow.pflow.md` auto-detects relevant topics.

When to load the guide:
  Building a new workflow           → `pflow guide core` + relevant node/feature topics
  Modifying an existing workflow    → `pflow guide core ./workflow.pflow.md` (auto-detects topics)
  Running into errors               → read the error first (includes fix suggestions). For deeper inspection: `pflow report`

All commands support `--help` for detailed usage.
