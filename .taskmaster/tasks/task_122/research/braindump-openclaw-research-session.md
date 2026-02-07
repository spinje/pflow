# Braindump: OpenClaw Integration Research Session

## Where I Am

This session started as Task 107 (markdown format) verification but evolved into a deep exploration of:
1. PocketFlow's design and why pflow built on top of it
2. Whether a minimal Python framework with t-strings would be better for agent authoring
3. OpenClaw's Lobster and how it compares to pflow
4. Whether pflow could integrate with/replace Lobster for OpenClaw

The task file (task-122.md) captures the research findings. This braindump captures the journey and tacit knowledge.

## User's Mental Model

The user thinks in terms of **what agents actually do**. They kept pushing me to reconsider assumptions:

- "is this more or less valuable than pflow?" — they want honest comparative assessment, not advocacy
- "are we missing something obvious?" — they trust their instinct that there's a simpler solution
- "lets take a step back and think hard" — they use this phrase when I'm converging too quickly on a suboptimal answer
- "what would be easiest for agents to write?" — this is their north star for design decisions

Key reframe from the user: **agents are the users, not humans**. This changes everything about format design. LLMs know markdown, Python, shell. Novel DSLs are friction.

The user is genuinely exploring whether pflow's markdown format is the right approach, or whether something more Python-native would be better. They're not committed to any particular answer.

## Key Insights

### PocketFlow is good at one thing

PocketFlow (~200 lines) is for **Python developers building a specific application** — a fixed pipeline where the developer controls all nodes. The shared store with implicit key conventions works when one person wrote everything.

pflow added template wiring (`${node.output}`) on top, which fundamentally changes the model from implicit to explicit data flow. This is why pflow has so much wrapping code — it's bridging two different paradigms.

**The user asked**: "was it a mistake to build pflow on top of pocketflow?"

My honest answer: No at the start (got us running quickly), but the value is shrinking. pflow uses maybe 40 lines of PocketFlow meaningfully. The rest is bypassed or wrapped.

### The minimal framework idea

We designed a hypothetical ~400-line framework:
- Template wiring via **t-strings** (PEP 750, Python 3.14+)
- PocketFlow's action routing (`>>`, `- "error" >>`)
- Pre-built nodes (HTTP, LLM, Shell)
- Execution trace (inputs/outputs per node on failure)
- Timeouts per node

The key insight: **t-strings solve the eager evaluation problem**. `t"Summarize: {page['response']}"` looks like an f-string but returns a Template object. The framework resolves references at execution time. Agents write natural Python.

The user was excited about this but wanted to validate it works in practice.

### Lobster is not what I initially thought

I initially described Lobster as "workflows agents invoke." The user pushed me to research more.

**Lobster's actual purpose**: Human-in-the-loop automation with approval gates. Humans write `.lobster` files (YAML with shell commands). Agents invoke pre-defined pipelines. The key feature is `approval: required` which halts execution until human confirms.

**Critical insight**: Lobster workflows are shell commands (`command: inbox list --json`). pflow has typed nodes with known interfaces. Lobster can't validate before execution. pflow can.

### Approval gates require checkpoint/resume

The user asked if pflow could do "triage inbox, wait for approval, send emails."

I initially suggested a blocking MCP call. User pushed back: "is having a blocking process really the right way to go?"

**Answer: No.** A process waiting hours/days is fragile. The right approach is Lobster's model:
1. Serialize execution state at approval point
2. Exit with resume token
3. Human approves via external system
4. `pflow resume <token>` continues

This is new infrastructure for pflow, not just configuration.

## Assumptions & Uncertainties

**ASSUMPTION**: Python 3.14's t-strings (PEP 750) work as documented. I haven't actually run code with them. October 2025 release should mean they're available now (Feb 2026), but needs verification.

**ASSUMPTION**: The Airflow-style decorated function pattern (`@node` decorator, lazy function calls) is compatible with PocketFlow's action routing. Haven't proven this works together.

**UNCLEAR**: Does OpenClaw actually want pflow integration? The research was one-sided — we looked at Lobster, but don't know OpenClaw team's roadmap or interest.

**UNCLEAR**: How do agents discover available MCP tools in an OpenClaw environment? This is critical for agent-authored workflows.

**NEEDS VERIFICATION**: The `request_approval` MCP tool pattern — does OpenClaw already have something like this, or would it need to be built?

## Unexplored Territory

**UNEXPLORED**: Authentication and permissions. If pflow runs in OpenClaw context, how does it inherit permissions for MCP tools? Who authorizes what?

**UNEXPLORED**: Error handling in checkpoint/resume. What happens if the workflow changes between pause and resume? State compatibility?

**UNEXPLORED**: The "minimal framework" — we designed it conceptually but never built it. Should this be a separate project from pflow? Would it replace pflow or complement it?

**CONSIDER**: The minimal framework targets Python 3.14+. pflow targets Python 3.10+. These are different audiences. Maybe both should exist.

**MIGHT MATTER**: Lobster's `openclaw.invoke` pattern — workflows can call back into OpenClaw tools. pflow's MCP node already does this. But the trust/permission model wasn't discussed.

**MIGHT MATTER**: Lobster returns structured JSON envelopes with status, output, requiresApproval. pflow's MCP server has similar patterns. Could pflow be invoked the same way Lobster is?

## What I'd Tell Myself

1. **Don't assume the user wants pflow to win.** They're genuinely evaluating alternatives. The minimal Python framework might be better for some use cases.

2. **Lobster and pflow aren't competitors.** Lobster is for pre-defined human-authored automations with approval gates. pflow is for agent-authored workflows. They could coexist.

3. **t-strings are the answer to "natural Python but declarative."** I went through many wrong answers (eager execution, reference objects, operator overloading) before the user pushed me to research what already exists.

4. **The user values honest assessment over advocacy.** When I said "the minimal framework might be more valuable than pflow," they appreciated the honesty rather than being defensive.

## Open Threads

### Thread 1: Should we build the minimal framework MVP?

The user asked "should we build an mvp and see if this all works in practice?" — referring to the ~400 line t-string framework. I said yes. Then the conversation shifted to OpenClaw research. This is still pending.

### Thread 2: What exactly would OpenClaw integration look like?

Options discussed but not decided:
- pflow as MCP server (already exists)
- pflow invoked like Lobster (subprocess with JSON envelope)
- pflow with approval gates (checkpoint/resume)
- The minimal framework instead of pflow

### Thread 3: The `mappings` field is dead code

During Task 107 research, we discovered `mappings` in the IR schema is completely unused — a remnant from Task 9's abandoned proxy mapping design. Not relevant to Task 122, but should be cleaned up eventually.

## Relevant Files & References

### This session produced:
- `.taskmaster/tasks/task_122/task-122.md` — the stub task file

### From Task 107 research (read these for context on pflow's design):
- `.taskmaster/tasks/task_107/task-107.md`
- `.taskmaster/tasks/task_107/research/design-decisions.md`
- `.taskmaster/tasks/task_107/research/braindump-format-design-session.md`

### PocketFlow (understand what pflow is built on):
- `src/pflow/pocketflow/__init__.py` — the ~200 line framework
- `src/pflow/pocketflow/docs/core_abstraction/flow.md` — action routing
- `src/pflow/pocketflow/docs/core_abstraction/node.md` — prep/exec/post lifecycle

### External references:
- [PEP 750 – Template Strings](https://peps.python.org/pep-0750/) — t-strings for Python 3.14+
- [Lobster docs](https://docs.openclaw.ai/tools/lobster)
- [Lobster GitHub](https://github.com/openclaw/lobster)

## For the Next Agent

**Start by**: Reading task-122.md for the research summary, then this braindump for context.

**The user's real question**: Is pflow the right tool for OpenClaw integration, or should we build something different (the minimal Python framework)?

**Don't bother with**: Trying to make pflow "win" the comparison. The user wants honest evaluation.

**The user cares most about**: What's easiest for agents to author. Everything flows from that.

**Key decision not yet made**: Whether to build a minimal framework MVP to validate the t-string approach, or focus on pflow's OpenClaw integration path.

**If continuing this work**: Ask the user which direction they want to explore first:
1. Build minimal framework MVP (~400 lines, t-strings, Python 3.14+)
2. Design pflow approval gates (checkpoint/resume)
3. Reach out to OpenClaw team about integration interest

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
