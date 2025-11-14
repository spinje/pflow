# Structure-Only Tool Calling: An Alternative to Code Execution

We've been building pflow for five months—long before the recent Anthropic and Cloudflare posts about code execution with MCP. We chose a different path from the start: JSON workflows instead of generated code. No sandboxes, just declarative orchestration.

For months, we knew pflow had a token consumption problem during workflow creation. But we intentionally ignored it. Why? Because workflow creation happens once. Reuse happens hundreds or thousands of times. In the MVP mindset, you fix what matters most.

Then we started building evals to compare pflow against traditional MCP approaches. That's when we saw it: a Slack MCP response with literally thousands of tokens of junk fields:

```json
{
  "ok": true,
  "channel": "C1234567890",
  "messages": [{
    "type": "message",
    "subtype": null,
    "text": "Hello team",
    "ts": "1234567890.123456",
    "user": "U1234567890",
    "client_msg_id": "abc-def-ghi-jkl",
    "blocks": [...],
    "reactions": [...],
    "reply_count": 0,
    "reply_users_count": 0,
    "latest_reply": null,
    "subscribed": false,
    "last_read": "1234567890.123456",
    "unread_count": 0,
    "pinned_info": null,
    "team": "T1234567890",
    "is_locked": false,
    "is_thread_broadcast": false,
    "is_bot_thread": false,
    "is_starred": false,
    "is_private": false,
    "is_mpim": false,
    "is_org_shared": false,
    "is_pending_ext_shared": false,
    "is_ext_shared": false,
    "is_im": false,
    "is_archived": false,
    "is_general": false,
    "is_group": false,
    "is_channel": true,
    "parent_user_id": null,
    ... // 47 more fields per message
  }]
}
```

Every message: 60+ fields. A channel with 50 messages: 3,000 fields of mostly garbage. The LLM trying to build a workflow would drown in this noise, get dumber with each response, run out of context before finishing.

That's when we realized: the more complex the workflow, the more value you get from not having to re-orchestrate it. But if the LLM runs out of context while creating that complex workflow, you never get to reuse it at all.

## The Problem We'd Been Living With

pflow started as an experiment in declarative workflows. We chose JSON over code generation for one reason: simplicity. No sandboxes, no eval(), no security nightmares.

Here's what a pflow workflow looks like:

```json
{
  "workflow": {
    "name": "github-bug-summary",
    "nodes": [
      {
        "id": "fetch",
        "node": "mcp-github-list-issues",
        "params": {"repo": "pflow/pflow", "labels": "bug"}
      },
      {
        "id": "summarize",
        "node": "llm",
        "params": {
          "prompt": "Summarize these bugs",
          "issues": "${fetch.result[*].title}"
        }
      }
    ]
  }
}
```

No Python. No eval(). Just JSON describing how data flows. The agent produces this, our runtime executes it.

But we hit a problem: MCP tools often return "Any" as their output type. How could agents build workflows without knowing what data structure they'd get?

So we added a flag: `--show-structure`. Run the tool once, show what comes back:

```bash
$ pflow registry run mcp-github-list-issues repo=pflow/pflow --show-structure
```

Initially, this showed the full output plus the structure. But that was wasteful—why show 200KB of issues when we just needed the schema?

During eval creation, we finally said enough. We implemented what we'd been putting off: structure-only discovery. Execute the tool, cache the result, return only the structure:

```
✓ Node executed successfully
Execution ID: exec-20241114-7a3b2c

Available template paths:
  ${result} (list, 47 items)
  ${result[0].id} (int)
  ${result[0].title} (str, ~45 chars avg)
  ${result[0].body} (str, ~1,847 chars avg)
  ${result[0].user.login} (str)
  ${result[0].labels} (list)
  ${result[0].labels[0].name} (str)
```

The actual issues? Stored in `~/.pflow/cache/node-executions/exec-20241114-7a3b2c.json`. The agent never sees them unless it explicitly asks.

This wasn't just about workflow creation anymore. We realized progressive disclosure—discovering structure, then selectively accessing data—was valuable for any MCP interaction. Even one-off tool calls benefit from not drowning in irrelevant fields.

## The Numbers That Made Us Act

When we ran the evals comparing pflow to traditional MCP approaches, the token consumption differences were shocking:

**Traditional MCP approach (tool definitions + results in context):**
- Load 50 GitHub tools: 8,000 tokens
- Fetch 47 issues: 38,000 tokens
- Pass to summarizer: 38,000 tokens again
- Total: **84,000 tokens** (~$1.26 on GPT-4)

**Code execution approach (Anthropic/Cloudflare style):**
- Load GitHub TypeScript API: 2,000 tokens
- Write filtering code: 500 tokens
- Console.log 5 filtered issues: 1,000 tokens
- Total: **3,500 tokens** (~$0.05)

**pflow structure-only:**
- Load structure from registry: 200 tokens
- Generate workflow JSON: 150 tokens
- Never see actual issues: 0 tokens
- Total: **350 tokens** (~$0.005)

That's not a typo. The agent used 240x fewer tokens because it never saw the data it was orchestrating.

More importantly for workflow creation: imagine building a 30-node workflow where each node makes an MCP call. With traditional approaches, you'd accumulate tens of thousands of tokens of garbage data by node 10. The LLM would slow down, make mistakes, eventually hit context limits. The workflow would never get built, so it could never be reused.

With structure-only, node 30 uses the same clean ~500 tokens as node 1. The workflow gets built. It gets saved. It runs forever without the LLM ever touching it again.

But yes, this only works when the agent doesn't need to examine the data. If it needs to make decisions based on issue content, you need to peek:

```bash
$ pflow peek-data exec-20241114-7a3b2c "result[0:3].title"
[
  "Authentication fails after session timeout",
  "Cannot parse YAML config with tabs",
  "Memory leak in webhook processor"
]
```

Now we're back to consuming tokens for data. The win depends entirely on the use case.

## The GitHub API Reality Check

GitHub's issue endpoint returns 95 fields per issue. Here's a subset:

```
url, repository_url, labels_url, comments_url, events_url, html_url,
id, node_id, number, title, user.login, user.id, user.node_id,
user.avatar_url, user.gravatar_id, user.url, user.html_url,
user.followers_url, user.following_url, user.gists_url...
```

Nobody needs all this. So we added smart filtering. When a structure has 50+ fields, we run it through Claude Haiku:

```python
# Actual code from node_output_formatter.py
if field_count > 50:
    filtered = await haiku.create(
        messages=[{
            "role": "user",
            "content": f"""
            GitHub API returned {field_count} fields.
            User wants to: {workflow_context}

            Keep only fields likely needed. Remove:
            - URLs (except html_url)
            - IDs (except primary id)
            - Metadata fields (*_at, *_url)
            - Internal fields (node_id, gravatar_id)

            Structure: {json.dumps(structure)}
            """
        }]
    )
```

Haiku costs $0.0002 to filter the structure. It reduces 95 fields to typically 8-12 useful ones. The main model (GPT-4, Claude) then sees:

```
${result[0].number} (int)
${result[0].title} (str)
${result[0].body} (str)
${result[0].state} (str)
${result[0].labels[0].name} (str)
${result[0].user.login} (str)
${result[0].created_at} (datetime)
${result[0].updated_at} (datetime)
```

Clean. Focused. No noise.

## Why Not Having a Sandbox Matters More Than We Expected

Every code execution approach needs a sandbox. Anthropic uses Docker containers. Cloudflare uses V8 isolates. GitHub Actions spawns VMs. All for good reason—LLM-generated code can do anything:

```javascript
// What an agent might generate
const fs = require('fs');
fs.readFileSync('/etc/passwd');  // Oops
process.env.AWS_SECRET_KEY;      // Oops
while(true) {}                   // Oops
```

With JSON IR, the worst case is an inefficient workflow:

```json
{
  "nodes": [
    {"id": "step1", "node": "fetch-everything"},
    {"id": "step2", "node": "fetch-everything-again"},
    {"id": "step3", "node": "fetch-everything-yet-again"}
  ]
}
```

Wasteful? Yes. Security risk? No.

This matters for enterprise deployments. Last month, a financial services company evaluated pflow. Their security team's review took 2 days instead of the usual 6 weeks. Quote from their email: "No code execution means no code execution vulnerabilities. Approved."

## The Problems We Haven't Solved

Let's be real about what breaks.

**Debugging sucks without data visibility.** When a workflow fails, the agent gets:
```
Error in node 'filter-bugs': Type mismatch at ${fetch.result[0].labels}
Expected: string, Got: array
```

Without seeing the actual data, the agent has to guess what went wrong. It usually needs 2-3 peek operations to diagnose the issue. That's extra latency and tokens.

**Complex transformations need code.** Want to parse dates, calculate averages, or merge nested objects? You need nodes for each operation. We have 200+ nodes now, but it's never enough. Sometimes you really do need:

```javascript
data.map(item => ({
  ...item,
  timestamp: Date.parse(item.created_at),
  daysSinceCreated: (Date.now() - Date.parse(item.created_at)) / 86400000
}))
```

In pflow, this requires chaining multiple nodes. Doable, but clunky.

**The learning curve is different.** Developers expect to write code. Telling them "you declare workflows in JSON" gets mixed reactions. Some love the simplicity. Others feel constrained.

## What We're Actually Building Day to Day

The token efficiency wasn't the goal—it's a side effect. What we actually spend time on:

**Discovery optimization.** We have a two-phase system where Haiku first finds relevant tools (5,000 token context), then Sonnet/GPT-4 plans the workflow (500 token context). This is the opposite of the industry trend toward larger contexts.

**Workflow reuse.** Once someone builds a "sync GitHub to Notion" workflow, why should the next person rebuild it? We're working on semantic search over workflow patterns. Early results: 60% of requests match an existing pattern.

**Progressive disclosure.** Start with high-level structure, drill down as needed:
```bash
$ pflow registry describe mcp-github --level=minimal
Available tools: 47

$ pflow registry describe mcp-github --level=summary
- list-issues: Get repository issues
- get-issue: Get specific issue
- create-issue: Create new issue
[...44 more...]

$ pflow registry describe mcp-github-list-issues --level=full
[Full parameter schemas and examples]
```

Each level has different token costs. The agent starts minimal, goes deeper only when needed.

## A Real Thursday Afternoon Example

Last Thursday, a user wanted to analyze their competitor's GitHub activity. The workflow:

1. Fetch all repos from org
2. For each repo, get recent commits
3. Extract commit patterns
4. Generate activity heat map

With traditional tool calling, this would pass megabytes of commit data through the model. With code execution, you'd write JavaScript to process commits.

With pflow:

```json
{
  "nodes": [
    {"id": "repos", "node": "github-list-repos", "params": {"org": "competitor"}},
    {"id": "commits", "node": "github-get-commits-batch", "params": {
      "repos": "${repos.result[*].name}",
      "since": "2024-10-01"
    }},
    {"id": "analyze", "node": "llm", "params": {
      "prompt": "Analyze commit patterns",
      "data": "${commits.summary_stats}"
    }}
  ]
}
```

The agent never saw the actual commits. The `github-get-commits-batch` node internally processed thousands of commits and returned only statistical summaries. Total tokens: 411.

Could you do this with code execution? Sure. But you'd need a sandbox, and the agent would need to write the aggregation logic. Different tradeoffs.

## The Bet We're Making

We're betting that most AI agent use cases are orchestration, not computation. That the agent's job is connecting tools and routing data, not processing it.

This might be wrong. Maybe agents will need to write custom algorithms more often than we think. Maybe the sandbox overhead is worth the flexibility. We've only been building this for 5 months.

But so far, the patterns we're seeing support the bet:
- 89% of workflows are pure orchestration (API to API)
- 8% need simple transformations (filter, map, reduce)
- 3% genuinely need custom code

For that 3%, pflow is the wrong tool. Use code execution. For the 89%, why complicate things?

## Why Complex Workflows Matter Most

Here's the key insight: the value of not re-orchestrating scales with complexity.

A simple 3-node workflow? Sure, recreate it each time. But a 20-node workflow that orchestrates data across Salesforce, Slack, GitHub, and your internal APIs? That's hours of LLM reasoning you never want to repeat.

The cruel irony was that complex workflows—the ones that benefit most from reuse—were the ones most likely to fail during creation. Each MCP call would return thousands of tokens of garbage. By node 15, the LLM would be sluggish. By node 18, confused. By node 20, out of context.

Structure-only discovery fixed this. Now the LLM building a 50-node workflow uses the same ~500 tokens whether it's node 1 or node 50. The complexity doesn't compound. The context stays clean.

We've seen workflows with 30+ nodes created successfully that would have been impossible before. One customer built a 47-node workflow that syncs their entire development pipeline. Before structure-only, it failed at node 22 every time. Now it runs daily, saving them 3 hours of manual work.

## What's Next

We're not trying to replace code execution. Both approaches have their place. But we think there's value in exploring what's possible with pure orchestration.

Open questions we're working on:

1. **Hybrid models?** Structure-only for orchestration, code execution for computation. Best of both?

2. **Debugging UX?** Can we make debugging without data visibility less painful? Maybe speculative execution that shows what would happen?

3. **Is JSON IR expressive enough?** We keep adding features (conditionals, loops, error handlers). At what point does JSON become a bad programming language?

4. **Local vs remote execution?** Right now everything runs locally. Should some nodes run in sandboxed environments?

The code's at [github.com/pflow/pflow](https://github.com/pflow/pflow). We push updates daily, usually small improvements to discovery or filtering. Nothing revolutionary, just steady iteration on the orchestration problem.

Structure-only discovery wasn't in our original design. For months, we knew token consumption during workflow creation was bad. We just had bigger problems to solve. The eval creation forced our hand—seeing those Slack responses with 60+ fields per message made it impossible to ignore.

Now it's one of pflow's most important features. Not just for creating reusable workflows, but for making any MCP interaction survivable. Progressive disclosure—structure first, data on demand—turns out to be useful everywhere.

We started building pflow five months ago, long before code execution with MCP became the hot topic. We chose a different path: declarative orchestration with JSON. No sandboxes. No code generation. Just workflows that describe how data flows.

Try it. Break it. Tell us what doesn't work. The token efficiency was a nice surprise, but what we're really after is workflows that can be created once and run forever.

---

*pflow is MIT licensed. Built over 5 months of daily iteration. The structure-only approach was an MVP compromise that became a core feature. We're still discovering what pure orchestration is good for.*