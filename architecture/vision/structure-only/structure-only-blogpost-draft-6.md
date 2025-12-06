# Saving Is Easy, Structure Is Hard: Why We're Betting Against Code Execution

*December 2024*

We were building evaluation tests for pflow when we hit the problem. A Slack MCP call returned 3,847 tokens for a single message. Most of it was junk - internal IDs, deprecated fields, metadata nobody needs. The useful data? Maybe 200 tokens.

This mattered because we were trying to build complex workflows - the kind that chain dozens of tool calls together. Each call polluting context with thousands of unnecessary tokens meant hitting limits before the interesting work even started.

## The Industry Has Decided

Anthropic, Cloudflare, and Docker have all published solutions in the past few weeks. The consensus is clear: let AI agents write code. The code executes in a sandbox, data flows through the sandbox instead of the model's context, and only the final results come back.

It works. Their numbers show significant improvements. The industry is converging on code execution as the answer.

We've been building pflow for eight months. We've watched this consensus form. We've tried code-based approaches. And we're still betting against them.

## Everyone Saves Things

Here's what we noticed: every approach eventually saves artifacts for reuse.

Anthropic saves code as "skills." The DOE pattern saves Python scripts and markdown SOPs. Docker's MCP Gateway saves server configurations. Everyone discovers that regenerating from scratch every time is wasteful.

But saving is the easy part. The hard part is structure.

After six months of saving things:
- 200 Python scripts, each written slightly differently
- Markdown instructions the AI interprets (maybe differently each time)
- Scripts that reference each other in ad-hoc ways
- No way to validate that two saved things will work together
- Debugging requires reading generated code

The artifacts accumulate. The structure doesn't.

## What Structure Enables

pflow saves JSON intermediate representation instead of generated code:

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

Every workflow follows the same schema. Every node has a declared interface. The structure is enforced, not hoped for.

This enables things you can't do reliably with saved code:

**Validation before execution.** The workflow either conforms to the schema or it doesn't. Node interfaces either match or they don't. Errors surface before runtime.

**Predictable composition.** Workflows can nest other workflows. The schema defines how they connect. You don't hope the AI generates compatible patterns - compatibility is enforced.

**Discovery that scales.** When you have 200 saved workflows, how do you find the right one? With schema-enforced metadata, workflows are searchable by what they do, what inputs they need, what outputs they produce.

**Diffing and versioning.** Same schema means you can compare workflow versions meaningfully. Try diffing two versions of generated Python that accomplish the same thing differently.

## The Orchestrator Never Sees Your Data

Here's something we didn't fully appreciate until recently: when a workflow needs data processing, it's not the orchestrating AI that does it.

The orchestrator (Sonnet, GPT-4) creates the workflow. But it never sees the actual data. It just understands structure:

- `github-list-issues` returns issues
- An LLM node can process text
- Wire them together with template variables

During execution, a specialized model (Gemini Flash, 35x cheaper) does the actual summarization. The expensive orchestrator handles structure. The cheap execution model handles data.

This isn't unique to pflow - code execution can achieve similar isolation. But with declarative IR, the data flow is explicit and auditable before anything runs.

## Development vs Production

"But what about self-improvement? Code execution systems can fix their own errors and get better over time."

pflow can do this too. Our error messages are designed for AI comprehension. An agent can run a workflow, get a clear error, fix the IR, and retry. During development, this iteration is natural.

The difference is where we draw the line.

Code execution systems self-improve in production. The agent fixes scripts while the system is live. This sounds powerful until you think about it: your accounting workflow "self-improving" while processing real invoices. Experimental fixes affecting multiple users. Changes that fix one thing and break another.

In pflow, production workflows are immutable. They do exactly what the IR specifies. If something needs to change, you take it back to development, iterate with clear error feedback, validate, and deploy a new version.

Self-improvement belongs in development. Production needs predictability.

## The Bet We're Making

The industry is betting on powerful generalist agents - models that can generate any code, fix any error, handle any edge case through self-improvement.

We're betting on something different: a simpler orchestrator with specialized, validated tools.

The generalist agent approach requires:
- Powerful (expensive) models to generate good code
- Large context to understand the accumulated codebase
- Time for self-improvement to converge
- Trust in arbitrary code execution

The specialized tools approach requires:
- Simpler orchestrator (just wires validated workflows together)
- Smaller context (just structure, not data)
- Upfront validation cost (but then runs reliably)
- Trust in schema enforcement

We think most orchestration tasks don't need arbitrary code generation. They need reliability, composability, and auditability. The flexibility of code execution is real, but so is the complexity it introduces.

Eight months of building and watching the industry hasn't changed our minds. We might be wrong. But we haven't seen evidence that we are.

## What We Give Up

Let's be honest about the tradeoffs.

**Flexibility.** "Parse this CSV and pivot the data based on column headers" is trivial in code, awkward in declarative composition. Some tasks genuinely need arbitrary computation.

**Self-improvement in production.** If you want your system to adapt to API changes automatically without human intervention, code execution handles this more naturally.

**Industry momentum.** Everyone else is building code execution infrastructure. Tools, sandboxes, patterns - the ecosystem is forming around that approach. We're swimming against the current.

We're betting that the benefits of structure - validation, composition, auditability, predictable production behavior - outweigh these costs for most orchestration use cases.

## What We Don't Know

Is declarative IR the right abstraction for AI orchestration? We genuinely don't know.

Code execution is more flexible. If generated code quality keeps improving, the self-improvement problem might matter less. If the ratio of "needs flexibility" to "needs reliability" is higher than we think, we'll hit walls.

Eight months in, we haven't hit major walls. The workflows we build work reliably. The constraints that felt limiting at first now feel like guardrails. But we're still early.

The real test is scale and complexity. Hundreds of workflows. Dozens of services. Production traffic. We'll find out whether structure holds up or whether we need to reconsider.

## The Actual Claim

We're not claiming better performance than code execution. We don't have benchmarks to prove that.

We're claiming that **structure enforced by schema is different from conventions enforced by instructions**. That saving artifacts without structure leads to chaos at scale. That production systems should be predictable, with self-improvement confined to development.

Whether those claims justify betting against industry consensus depends on what you value. If you want maximum flexibility, code execution is probably right. If you want a composable library of reliable workflows, structure might be worth the tradeoffs.

We're exploring the second path. Eight months in, we still think it's worth exploring.

---

pflow is open source at [github.com/pocketflow-ai/pflow](https://github.com/pocketflow-ai/pflow). If you think we're wrong about structure vs flexibility, we'd like to understand why.
