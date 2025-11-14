# Structure-Only Discovery: How Declarative Workflows Accidentally Solved MCP's Token Problem

*December 2024*

We were building evaluation tests for pflow when we hit the problem. A simple Slack MCP call returned 3,847 tokens of response data for fetching a single message. Most of it was junk - internal IDs, deprecated fields, redundant metadata. The actual useful data? Maybe 200 tokens.

This wasn't supposed to be our focus. For five months, we'd been building pflow around a different principle: create a workflow once, run it forever. If the AI needs a few thousand extra tokens during workflow creation, who cares? You create once and reuse hundreds of times. The math seemed obvious.

But staring at that Slack response, we realized we'd been thinking about it wrong. Complex workflows - the ones that really matter - involve dozens of tool calls. If each one pollutes the context with thousands of unnecessary tokens, you hit context limits fast. The more valuable the workflow, the less likely you can actually create it.

## The Accidental Solution

Here's the thing: pflow's architecture already had a solution, we just hadn't recognized it as one.

We don't generate code. We don't need sandboxes. We use JSON intermediate representation (IR) to describe workflows declaratively. The AI orchestrates by understanding structure and routing, not by processing data. When a node executes, the data flows through our runtime, not through the AI's context.

This wasn't some brilliant foresight. We chose JSON IR because it was simpler to validate, easier to debug, and didn't require wrestling with sandbox security. But that constraint accidentally aligned with a deeper truth: **AI agents are orchestrators, not data processors.**

## Breaking the Reinvention Cycle

There's a pattern emerging in the AI tooling space. We build abstractions, they get too complex, so we tear them down and build new ones. Skills become MCP tools. MCP tools become generated code. Generated code becomes... skills again. Each iteration claims to solve the previous one's problems while introducing its own.

Code execution doesn't break this cycle - it continues it. By generating custom code for each integration, we're back to the fragmentation that standards were meant to solve. Every agent needs its own SDK implementations. Every service gets wrapped differently.

We chose a different path: declarative orchestration that doesn't generate code at all.

## Three Ways to Call Tools

Let's make this concrete. You want to copy a meeting transcript from Google Drive to Salesforce. Here's how each approach handles it:

**Traditional MCP Tool Calling:**
```
AI: Call gdrive.getDocument("doc123")
System: Returns 50,000 tokens of transcript
AI: [processes all 50,000 tokens]
AI: Call salesforce.updateRecord(...)
     [writes out all 50,000 tokens again]
Total: 100,000+ tokens through context
```

**Code Execution (Anthropic/Cloudflare approach):**
```typescript
// AI generates this code
const doc = await gdrive.getDocument({id: "doc123"});
await salesforce.updateRecord({
  type: "Meeting",
  id: "sf456",
  notes: doc.content
});
// Only logs what's needed
console.log("Updated meeting notes");
Total: ~3,000 tokens (code + selective output)
```

**Structure-Only (pflow's approach):**
```
AI sees: gdrive.getDocument returns {content: str(~50KB)}
AI writes: ${gdrive-get.content} -> ${salesforce-update.notes}
Execution: Data flows through runtime, never through AI
Total: ~300 tokens (just structure + routing)
```

The difference isn't incremental. It's fundamental.

## How We Actually Built This

When we decided to fix the token pollution problem, the implementation was surprisingly straightforward - because our architecture already separated execution from orchestration.

First, we modified our registry run command to cache execution results:

```bash
$ pflow registry run mcp-slack-get-message channel=C123 ts=1234.5678

✓ Node executed successfully
Execution ID: exec-20241210-a7b2c3

Available template paths:
  ✓ ${text} (str, ~200 chars)
  ✓ ${user} (str)
  ✓ ${ts} (str)
  ✓ ${thread_ts} (str)

[Note: 47 additional fields hidden. Full structure cached.]
```

The AI never sees the actual message content, user data, or the 47 fields of Slack metadata. It just learns what's available.

But showing 50+ fields is still noisy. So we added smart filtering. When an API returns more than 50 fields, we use Claude Haiku (cheap and fast) to identify what's actually useful:

```python
# Before filtering: 200+ GitHub issue fields
# After filtering: 8 relevant fields
filtered_fields = filter_with_haiku(
    all_fields,
    context="Building a workflow to summarize open bugs"
)
```

This isn't complex ML pipelines or fancy infrastructure. It's practical engineering: use a small model to make a big model more effective.

## "But MCP Can Do Progressive Disclosure"

Fair point. MCP doesn't technically require loading all tools upfront. You can build orchestration layers, use specialist agents for different tool subsets, add semantic routing. We've seen these implementations. They work.

But here's what bothers us: you're solving a problem the architecture created. If you need an orchestrator agent to decide which specialist agent to invoke based on which MCP tools they have access to, you've built a complex workaround for a simple problem. Every one of these solutions adds another moving part, another point of failure, another thing to debug.

With structure-only discovery, progressive disclosure isn't a feature you add - it's the default behavior. The AI sees structure when it needs to understand, retrieves data when it needs to (and hint: it almost never needs to). No orchestration layers. No specialist agents. Just natural, on-demand discovery.

## The Thing About Sandboxes

Anthropic and Cloudflare's code execution approach is technically impressive. Dynamic V8 isolates, TypeScript generation, secure sandboxes - it's solid engineering. But here's what bothers us about it: you're solving a trust problem you created.

When you let AI generate arbitrary code, you need sandboxes because that code might do anything. It might leak API keys through console.log(). It might have injection vulnerabilities. It might infinite loop. So you build elaborate containment.

We just... don't generate code. Our JSON IR describes what to connect, not how to connect it. The execution is deterministic. There's no arbitrary computation to sandbox because there's no arbitrary computation at all.

Is this the right abstraction? We're still figuring that out. There are definitely things you can't express declaratively that code handles easily. But for the workflows we see - API orchestration, data routing, multi-step processes - it's been enough. And the security story is so much simpler when you can't generate code that needs securing.

More importantly, we maintain standardization. Every workflow uses the same JSON IR format. Every node follows the same interface. When you generate custom code for each service integration, you're recreating the fragmentation that MCP was supposed to solve. We keep the standard without the bloat.

## The Orchestrator Never Touches Your Data

Here's something crucial we didn't truly realize how valuable it isuntil recently: when you need data processing in a workflow, it's never the orchestrating AI that does it. The orchestrator builds a workflow with specialized nodes for that work.

Consider summarizing GitHub issues. The orchestrator (Sonnet 4.5, GPT-5.1) creates this workflow:

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "fetch-issues",
      "type": "github-list-issues",
      "params": {
        "repo": "org/repo",
        "state": "open",
        "labels": "bug"
      }
    },
    {
      "id": "summarize",
      "type": "llm",
      "params": {
        "model": "gemini-2.5-flash-lite",
        "prompt": "Summarize these bug reports: ${fetch-issues.result}",
        "max_tokens": 500
      }
    }
  ]
}
```

The orchestrating AI never sees the issue data. It just understands:
- `github-list-issues` returns a list of issues
- An LLM node can summarize text
- Wire them together with template variables

During execution, Gemini Flash (35x cheaper than the orchestrator) does the actual summarization. You get optimal model selection for each task - powerful models for orchestration, efficient models for execution. Control over what data is visible to which llm model.

## The Discovery Problem We Actually Care About

Token efficiency was never our main goal. We've spent five months obsessing over a different problem: how do you find the right workflow components?

It's not enough to have thousands of MCP tools available. You need to:
- Discover which tools exist for your task
- Understand what they actually do (not just their names)
- Figure out how they compose together
- Find existing workflows you can reuse

This is the unsexy work that makes AI agents actually useful. Progressive disclosure (show less, reveal more on demand). Semantic search over tool descriptions. Pattern matching against existing workflows. These micro-optimizations compound.

When you're building complex workflows - the kind that touch 20 different services - these discovery optimizations matter more than raw token efficiency. Though, as we learned from that Slack response, you eventually need both.

## What We're Still Learning

Let's be honest about the tradeoffs. Structure-only discovery makes some things harder:

**Debugging gets weird.** When something fails, the AI can't see the actual data to diagnose why. We added a `peek_data` tool that requires permission, but it breaks the elegance.

**Some tasks need data visibility.** "Summarize the top 5 issues" requires seeing issue titles. But here's the thing: it's not the orchestrator that needs to see them. The orchestrator just wires up an LLM node inside the workflow to do the summarization. The orchestrating AI (expensive, powerful) never touches the data. The execution node (cheap, specialized) does the actual work. It's only in very rare cases that the orchestrator needs to see the data, for example if it needs to debug why the llm node is failing to summarize the issues correctly.

**Complex transformations are awkward.** "Parse this CSV and restructure it" is trivial in code, painful in declarative routing. We're exploring hybrid approaches.

**Rate limiting is invisible until it isn't.** When code execution runs parallel API calls, you hit rate limits. Our declarative approach naturally serializes when needed, but developers used to writing parallel code might find this constraining.

**The abstraction might be wrong.** Maybe code generation is more flexible long-term. Maybe we'll need both approaches. Five months in, we're still learning.

**We don't solve MCP's auth problem.** Neither does code execution. If MCP doesn't handle authentication well, we inherit that limitation. We just don't make it worse by adding more complexity.

## The Unexpected Security Story

We didn't build structure-only discovery for security. But it turns out that when AI can't see data, a whole class of problems disappears.

A healthcare company reached out about using pflow for patient data workflows. With traditional approaches, that's terrifying - PHI in AI context is a compliance nightmare. With structure-only, the AI orchestrates patient data flows without ever seeing a single patient name.

This isn't theoretical. You can configure pflow to completely disable data access:

```json
{
  "tools": {
    "peek_data": {
      "permission": "deny"
    }
  }
}
```

Now the AI can build and run workflows on sensitive data it will never observe. No tokenization schemes. No data masking. No trust boundaries. The data was never visible in the first place.

## Where This Goes

After Anthropic and Cloudflare published their code execution posts, we got asked: "Isn't pflow solving the same problem?"

Yes and no. We're all trying to make AI agents more efficient with MCP tools. But our path is different. They're making code execution better. We're questioning whether you need code execution at all.

The approaches aren't mutually exclusive. Code execution solves the token problem by moving computation outside context. We solve it by keeping data outside context. Code execution gives maximum flexibility through arbitrary computation. We give predictability through declarative orchestration. Both beat traditional MCP tool calling by orders of magnitude.

The real test will be complexity. Can declarative workflows handle the messy, stateful, conditional logic that production systems need? Or will we hit a wall where code becomes necessary?

We don't know yet. But five months in, we haven't hit that wall. Each month, we handle more complex workflows with the same simple abstraction: understand structure, route data, never process it yourself.

## The Code is the Product

pflow is open source. Not "open core" with paid features. Not "source available" with restrictions. Actually open source. The structure-only discovery, smart filtering, the entire orchestration engine - it's all there on GitHub.

Why? Because we think this abstraction question - code vs. declarative, processing vs. orchestration - is too important for one company to decide. We need more people exploring different approaches, finding what works, sharing what doesn't.

If you're hitting token limits with MCP tools, try structure-only discovery. If you're building workflows on sensitive data, try orchestration without observation. If you think we're wrong about declarative IR, tell us why.

The best solution might be something none of us have thought of yet.

---

*pflow is available at [github.com/pocketflow-ai/pflow](https://github.com/pocketflow-ai/pflow). The structure-only discovery feature ships in v0.2.*

*For technical details and benchmarks, see our [implementation notes](https://github.com/pocketflow-ai/pflow/docs/structure-only.md).*