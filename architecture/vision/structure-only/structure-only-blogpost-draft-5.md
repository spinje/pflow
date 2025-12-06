# Constraints as Features: Why We Chose Declarative Workflows Over Code Generation

*December 2024*

We were building evaluation tests for pflow when we hit the problem. A Slack MCP call returned 3,847 tokens for a single message. Most of it was junk - internal IDs, deprecated fields, metadata nobody needs. The useful data? Maybe 200 tokens.

This mattered because we were trying to build complex workflows - the kind that chain dozens of tool calls together. Each call polluting context with thousands of unnecessary tokens meant hitting limits before the interesting work even started.

## Everyone's Solving This Now

Anthropic and Cloudflare recently published their solutions: let AI agents write code to call tools instead of calling them directly. The code executes in a sandbox, data flows through the sandbox instead of through the model's context, and only the final results come back. It works. Their numbers show significant token reduction.

We'd been building something different for five months before these posts came out. Not because we saw this coming, but because we'd made a bet early on: what if AI agents shouldn't generate code at all?

## The Bet on Constraints

Here's what we noticed: you can achieve reusability, composition, and discovery with code execution. You write markdown instructions telling the AI to search for existing code before writing new code. You document patterns for how code should compose. You build conventions and hope the AI follows them.

The key word is "hope."

With code execution, the AI *might* search for existing implementations. It *might* generate compatible code. It *might* follow your composition patterns. You're betting on instruction-following consistency across every task, every user, every edge case.

We made a different bet. What if the system enforced these patterns instead of hoping the AI followed instructions?

## Enforced by Architecture

pflow uses JSON intermediate representation instead of generated code:

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "fetch-issues",
      "type": "github-list-issues",
      "params": {
        "repo": "${input.repo}",
        "state": "open"
      }
    },
    {
      "id": "summarize",
      "type": "llm",
      "params": {
        "model": "gemini-2.0-flash-lite",
        "prompt": "Summarize these issues: ${fetch-issues.result}"
      }
    }
  ]
}
```

This isn't more elegant than Python. It's more constrained. And the constraints are the point.

- **`type: github-list-issues`** must exist in the registry. The AI can't hallucinate a node that doesn't exist.
- **`${fetch-issues.result}`** must match the declared output interface. Type mismatches fail validation before execution.
- **The workflow itself** is a saved artifact. It doesn't get regenerated - it gets reused.

The difference between "please follow the pattern" and "the schema rejects invalid patterns" is the difference between convention and constraint. We chose constraint.

## Create Once, Run Forever

Code execution generates code each time. Even when the task is identical, the AI regenerates the solution. Maybe it generates the same code. Maybe it doesn't. Each invocation is a fresh generation.

pflow workflows are artifacts:

```bash
# First time: AI creates the workflow
pflow "fetch open bugs from github and summarize them"
# → Workflow saved as 'summarize-github-bugs'

# Every subsequent time: no AI needed
pflow run summarize-github-bugs --repo=org/project
# → Executes instantly, deterministically
```

The AI does the hard work once. After that, it's just execution. No regeneration, no token cost, no variation. The same IR produces the same execution every time.

This changes the economics. With code execution, complex orchestration costs tokens every time. With saved workflows, you pay the creation cost once and amortize it across every subsequent run. The more you reuse a workflow, the more the initial cost disappears.

## The Orchestrator Never Sees Your Data

Here's something we didn't fully appreciate until recently: when a workflow needs data processing, it's not the orchestrating AI that does it.

Consider summarizing GitHub issues. The orchestrator (Sonnet, GPT-4, whatever you're using for planning) creates the workflow. But the orchestrator never sees the issues. It just understands:

- `github-list-issues` returns issues
- An LLM node can process text
- Wire them together with template variables

During execution, a specialized model (Gemini Flash, 35x cheaper) does the actual summarization. The expensive orchestrator handles structure. The cheap execution model handles data.

```json
{
  "id": "summarize",
  "type": "llm",
  "params": {
    "model": "gemini-2.0-flash-lite",
    "prompt": "Summarize: ${fetch-issues.result}"
  }
}
```

You get to choose which model sees which data. The orchestrator operates on structure and never needs to see customer records, patient data, or proprietary information. The execution nodes see only what they need to process.

This isn't unique to pflow - code execution can achieve similar isolation. But with declarative IR, the data flow is explicit and inspectable. You can audit exactly which nodes see which data before anything executes.

## What Constraints Enable

Generated code is flexible but opaque. Declarative IR is constrained but transparent.

**Validation before execution.** The workflow either conforms to the schema or it doesn't. Node interfaces either match or they don't. You find errors before runtime, not during.

**Composition by design.** Workflows can nest other workflows. The IR schema defines how they connect. You don't hope the AI generates compatible composition patterns - the structure enforces compatibility.

```json
{
  "id": "full-report",
  "type": "workflow",
  "params": {
    "name": "weekly-bug-summary",
    "inputs": {
      "repo": "${input.repo}"
    }
  }
}
```

**Static analysis.** You can trace data flow through a workflow without executing it. You can visualize the graph. You can diff two workflow versions. You can't reliably do any of this with generated code that varies each time.

**Workflow discovery.** Tools and nodes exist in both approaches - Anthropic's Tool Search Tool handles that well. What's different is saved workflows. When you build a workflow in pflow, it becomes searchable. Next time you need something similar, you find and reuse it rather than regenerating from scratch.

## What We Give Up

Let's be honest about the tradeoffs.

**Flexibility.** "Parse this CSV and pivot the data based on column headers" is trivial in code, awkward in declarative routing. Some tasks genuinely need arbitrary computation.

**Expressiveness.** Complex conditional logic, dynamic iteration patterns, error recovery strategies - code handles these naturally. We handle them through node composition, which works but feels indirect.

**Familiarity.** Developers know how to write Python. The IR schema is another thing to learn. The learning curve is real.

We're betting that most orchestration tasks don't need arbitrary flexibility. They need reliability, reusability, and auditability. If we're wrong about that ratio, we'll hit walls.

## Five Months of Unsexy Work

Token efficiency was never our main focus. We've spent five months on a less glamorous problem: how do you find the right workflow components?

Tool discovery exists in code execution too - Anthropic's Tool Search Tool is a good solution. What doesn't exist is workflow discovery. When you've built fifty workflows over three months, how do you find the one that does something similar to what you need now?

We've been building:

- Smart filtering when APIs return 200+ fields of structure
- Pattern matching against existing workflows
- A workflow manager that tracks what you've built and makes it searchable

None of this is revolutionary. It's careful, incremental work to make reuse practical. We're still not done.

The payoff is compound. Each saved workflow becomes a building block for more complex workflows. Your workflow library grows with use - yesterday's solution becomes today's component, rather than starting from zero each time.

## What We Don't Know

Is declarative IR the right abstraction for AI orchestration? We genuinely don't know.

Code execution is more flexible. If the ratio of "needs flexibility" to "needs reliability" is higher than we think, we'll hit walls. If generated code quality keeps improving, the instruction-following problem might matter less.

Five months in, we haven't hit major walls. The workflows we build work reliably. The constraints that felt limiting at first now feel like guardrails that prevent mistakes. But we're still early. The test is production complexity at scale.

## The Actual Difference

We're not claiming better token efficiency than code execution. We don't have the benchmarks to prove that, and Anthropic has actual data.

We're claiming something narrower: **constraints enforced by architecture are different from conventions enforced by instructions.** Whether that difference matters depends on what you value.

If you want maximum flexibility for one-off tasks, code execution is probably better. Generate the code, run it, move on.

If you want to build a library of reliable, reusable workflows that compose and can be audited, constraints might be worth the tradeoffs. The structure that limits flexibility also enables validation, composition, and analysis.

We're exploring the second path. We think it's worth exploring. We might be wrong.

---

pflow is open source at [github.com/pocketflow-ai/pflow](https://github.com/pocketflow-ai/pflow). If you think declarative IR is the wrong abstraction, we'd like to understand why.
