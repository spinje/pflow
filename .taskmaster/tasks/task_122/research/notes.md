We should probably do this properly since we have a shared store that does alot of the heavy lifting for us.

---

Task 106: Workflow Iteration Cache.

  It's the same core problem — serialize the shared store (node outputs) to disk so you can resume
  execution from a midpoint instead of re-running everything from the start.

  For iteration cache: "node 3 failed, fix it, re-run — but skip nodes 1 and 2 because their results
  are cached."

  For approval gates: "node 3 needs approval, pause — when human approves, resume from node 3 with
  the shared store intact."

  The serialization/deserialization machinery is identical. If you build one, you get the other
  nearly for free.

---

- Task 106 (Iteration Cache) — direct overlap. Same serialization problem.
  - Task 98 (First-Class IR Execution) — architectural refactor away from PocketFlow wrappers. If
  you're building state serialization, doing it on top of the current wrapper-heavy architecture
  means redoing it later. This task is about simplifying the execution model, which directly affects
  how/where you'd snapshot state.
  - Task 64 (MCP Orchestration) — long-running MCP servers. If pflow needs to hold a workflow open
  waiting for approval over MCP, that's a long-running connection. Same problem space.

  Task 39 (parallelism) is tangentially related — if you serialize state for parallel branches, you
  need to track multiple execution positions, not just one.

  The dependency chain for approval gates would be:

  Task 98 (clean execution model)
    → Task 106 (state serialization)
      → Approval gates (pause/resume using serialized state)
      → Task 64 (long-running MCP, if needed)

---

Not a blocking call — actual pause/resume semantics. Let me think through what pflow would
  need.

  The flow:

  1. OpenClaw calls pflow (via MCP) → "run this workflow"
  2. pflow executes nodes sequentially
  3. Hits an approval node → pauses, returns partial result + token
  4. OpenClaw shows the human what needs approval
  5. Human approves/denies
  6. OpenClaw calls pflow (via MCP) → "resume this workflow with approval=yes"
  7. pflow picks up where it left off, runs remaining nodes, returns final result

  What pflow would need to build:

  1. Execution state serialization — when a workflow pauses, snapshot the shared store + which node
  we're at + all intermediate outputs. Write to disk or hold in memory.
  2. An approval node (or a node property like approval: required) — when the executor hits this, it
  stops and returns a structured response: { status: "needs_approval", token: "abc123", prompt: "Send
   5 emails?", items: [...] }
  3. A resume mechanism — pflow resume abc123 --approve (CLI) or a resume_workflow MCP tool. Loads
  the serialized state, injects the approval result, continues execution.
  4. Workflow instance tracking — pending workflows need an ID, a place to store state, and probably
  a TTL (expire after 24h if no response).

  The markdown format would look something like:

  ### categorize-emails
  - type: mcp
  - server: inbox
  - tool: categorize

  ### review
  - type: approval
  - prompt: "Send these ${categorize.count} responses?"
  - items: ${categorize.responses}

  ### send
  - type: mcp
  - server: inbox
  - tool: send_batch
  - emails: ${review.approved_items}

  What's hard here:

  The only genuinely new thing is (1) — serializing mid-execution state. Right now pflow's executor
  runs a PocketFlow Flow, which holds state in-memory in the shared store. To pause/resume you'd need
   to:
  - Serialize the shared store (which can contain arbitrary Python objects)
  - Record the execution position (which node, which action triggered the pause)
  - Deserialize and reconstruct the Flow at resume time

  The rest (approval node, resume CLI/MCP tool, instance tracking) is straightforward plumbing.

  Does this make sense as a feature? It depends on whether pflow workflows will have real-world side
  effects that need human sign-off. If pflow is primarily an agent tool for data processing, approval
   gates are overkill. If pflow workflows will send emails, create PRs, modify files — then yes, this
   becomes essential.

---

Task 106 builds 80% of what approval gates need. Specifically:

  What Task 106 builds:
  - Serialize node outputs to disk (JSON per node)
  - Restore shared store from cached outputs
  - Track execution position (which nodes completed, which failed)
  - Resume execution from a midpoint (skip cached nodes, run from first miss)

  What approval gates would still need on top:
  1. A new status: paused — Task 106 has completed and failed. You'd add paused_awaiting_approval.
  2. An approval node type — a node that writes its approval request to the cache and signals the
  executor to stop.
  3. A resume entry point — pflow resume <workflow> --approve that loads the cache, injects the
  approval result into shared store, and continues from the paused node.

  That's it. The hard parts — serializing shared store to disk, loading it back, determining where to
   resume, cascade invalidation — are all solved by Task 106.

  How easy after Task 106? Small task. Maybe a week of work:
  - New approval node type (~50 LOC)
  - New paused status in the cache metadata
  - Resume CLI command (~100 LOC)
  - Resume MCP tool for OpenClaw integration (~50 LOC)
  - Tests

  The serialization machinery, the cache directory structure, the "load cached outputs into shared
  store and skip to node N" logic — all that exists from Task 106. The approval gate is essentially:
  "intentional cache miss with a reason."

---