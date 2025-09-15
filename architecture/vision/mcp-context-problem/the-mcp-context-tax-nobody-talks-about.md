# The MCP Context Tax Nobody Talks About

*Or: Why your AI agent gets dumber and more expensive with every tool you add*

## The Promise vs Reality

Everyone's excited about MCP (Model Context Protocol). Finally, we can give AI agents real tools! GitHub access! Database queries! File systems! The demos look amazing.

Here's what they don't show you: the second you load more than 2-3 MCP servers, your AI agent becomes a expensive, confused mess.

## The Math That Kills You

Let's do the actual math on a real workflow. Say you want to:
> "Check my PRs, update JIRA tickets, and post a summary to Slack"

Simple enough, right? Here's how you'd run it:

```bash
$ claude --mcp-config ./github.mcp.json ./jira.mcp.json ./slack.mcp.json \
         --strict-mcp-config "check PRs, update tickets, post summary"
```

What actually happens under the hood:

```bash
# Loading the MCP servers your AI needs:
GitHub MCP schema:   46,000 tokens (documented)
JIRA MCP schema:     16,000 tokens (verified)
Slack MCP schema:     2,000 tokens (verified)
Your actual request:     50 tokens
─────────────────────────────────
Total context:       64,050 tokens
```

Before your AI even starts thinking, you've burned through:
- **$0.19** in context costs (Claude-3.5 Sonnet at $3/1M input tokens)
- **64k tokens** of context window (nearly 1/3 of Claude's 200k limit)
- **Severe performance degradation** (research shows 50% drop at 32k+ tokens)

And this is for a 3-step task you run every morning.

## The Hidden Reasoning Tax

Loading MCP schemas is just the first hit. Here's what everyone forgets: the AI has to THINK between each tool use, and output tokens cost 5x more than input:

```bash
Step 1: AI reasons about GitHub results (500 output tokens @ $15/1M)
Step 2: AI decides what JIRA updates needed (600 output tokens)
Step 3: AI composes Slack summary (800 output tokens)

Output reasoning cost: $0.029
Schema input cost: $0.19
Total per run: $0.22

# Run 10x daily for a year:
AI Agent: $803/year
pflow: $0.22 (one-time compilation)
```

You're not just paying for schemas. You're paying for the AI to reason through the same sequence every single time. Output tokens are 5x more expensive than input, and that reasoning adds up fast.

## The Training Data Lottery

Here's the dirty secret of how developers actually work today: They're NOT using the GitHub MCP server (46k tokens). They're gambling that the AI remembers `gh` CLI from its training data:

```bash
# What the MCP promise was:
$ claude --mcp-config ./github.mcp.json "check my PRs"
> 46,000 tokens loaded, expensive but reliable

# What developers actually do:
$ claude "use gh cli to check my PRs and format them nicely"
> 0 MCP tokens, but...
> Attempt 1: Uses gh syntax from 2024, fails
> Attempt 2: Hallucinates a flag that doesn't exist
> Attempt 3: Finally works (this time)
```

The funny thing is, if you are not paying attention to what the AI is doing, you will only see that it works, not the quirky road it took to get there.

This "works" for GitHub because `gh` is in the training data. But you're playing a lottery:

**Winners (might work):**
- `gh` - Popular enough to be in training
- `aws` - Extensively documented online
- `docker` - Common in tutorials

**Losers (definitely won't work):**
- Your company's internal CLI tools
- That MCP server released last week
- Proprietary database connectors
- Anything with recent API changes

So developers face an impossible choice:
1. **Use MCPs**: Reliable but 64k tokens = unusable
2. **Pray for training data**: Free but requires 2-3 retries, fails randomly
3. **Write manuals in prompts**: "First run `tool --flag`, then parse the JSON..."

The promise of MCP - reliable tool use for ANY tool - is locked behind a token tax that makes it unusable. Meanwhile, we're all pretending that hoping the AI remembers bash commands from 2023 is a production strategy.

## It Gets Worse at Scale

Real developers are reporting these exact issues:

**With 5+ MCP servers (documented on GitHub):**
- Context starts at 8-18% but quickly balloons
- Sessions become unusable after just 5 prompts
- Constant need to reset conversations
- Performance degradation becomes noticeable

**With ~20 MCP servers (actual bug report):**
- Context window exhausted almost immediately
- GitHub MCP alone: 46,000 tokens
- Database schemas: Can exceed 50,000 tokens for complex tables
- Models start "forgetting" earlier context arbitrarily
- Complete breakdown of functionality

## The Dirty Secret

MCP is great in theory. In practice, it doesn't scale. Every tool you add makes your AI:
1. **More expensive** (linear token cost)
2. **Slower** (more context to process)
3. **Dumber** (attention diluted across huge context)
4. **Less reliable** (picks wrong tools from confusion)

## What Developers Are Actually Doing (Documented Cases)

**CloudQuery's Solution:** Built aggressive schema filtering with Go regex and column ranking - achieved 90% token reduction but requires custom engineering for each database.

**Community Workaround:** Keep MCP servers under 5 running concurrently. Beyond that, context bloat makes sessions unusable.

**Block's Approach:** Combine multiple API calls into single high-level tools to reduce schema overhead. Requires rewriting entire tool architecture.

## The Workarounds That Don't Work

**"Just load the MCPs you need"**

Sure, let me maintain 50 different shell scripts:
```bash
alias pr-check="claude --mcp-config ./github.mcp.json ./slack.mcp.json 'check PRs'"
alias deploy="claude --mcp-config ./github.mcp.json ./docker.mcp.json ./aws.mcp.json 'deploy'"
alias report="claude --mcp-config ./jira.mcp.json ./slack.mcp.json ./sheets.mcp.json 'report'"
```

This is insanity.

**"Use a smaller model"**

Smaller models are worse at tool use. You'll save on tokens but fail on execution.

**"Cache the schemas"**

Caching helps with latency, not cost. You still pay for context every time.

## "But What About Prompt Caching?"

Anthropic offers prompt caching with 90% discount on cached tokens. Sounds like it solves the problem, right? Not quite:

### Cache Limitations (Verified)
- **5-minute TTL**: Cache expires after 5 minutes (or pay 2x for 1-hour cache)
- **Exact match required**: Any change invalidates the entire cache
- **Session isolation**: Different MCP combinations can't share cache
- **Output tokens never cached**: That $0.029 reasoning cost? Always full price

### The Reality Check
```bash
# Morning standup (9 AM): Full price ($0.22)
# Quick check (9:02 AM): Cached ($0.04)
# Coffee break (9:10 AM): Cache expired, full price ($0.22)
# After lunch (2 PM): Full price ($0.22)

Daily cost with "caching": $0.70
Daily cost with pflow: $0.00
```

### The Frequency Paradox
If you're running workflows frequently enough for caching to matter, you're the PERFECT pflow user. Why pay $0.04 per cached run when you could pay $0.00?

### Different Tool Combinations = No Cache
```bash
Session 1: GitHub + Slack (builds cache A)
Session 2: GitHub + JIRA (can't use cache A, builds cache B)
Session 3: GitHub + Slack + Database (can't use A or B, builds cache C)

Every unique tool combination needs its own cache. Most real work involves different tool combinations throughout the day.
```

## The pflow Approach: Compile Away the Context

Here's what we do differently:

### Traditional AI + MCP (every run):
```
Load schemas (64k tokens) →
Think about request (2k tokens) →
Generate reasoning (2k output tokens) →
Total: 66k input + 2k output tokens
Cost: $0.22 per run
Time: 30-120 seconds
```

### pflow (after compilation):
```
Compilation (once): Load schemas → Determine tools → Save workflow
Execution (every time): Run workflow → Zero schema tokens → $0.00
Time: 2-5 seconds
```

We pay the context tax **once** during workflow creation, then never again.

## Real Numbers from Production

Let's use actual documented costs (Claude-3.5 Sonnet: $3/1M input tokens):

**GitHub + Slack workflow (real example):**
- MCP schemas: 48,000 tokens (GitHub: 46k, Slack: 2k)
- Plus reasoning: 1,500 output tokens
- Cost per execution: $0.17
- 1,000 executions: $170
- pflow: $0.17 once, then free
- **Savings: $169.83 (99.9%)**

**Database-heavy workflow (documented case):**
- Complex table schemas: 50,000+ tokens
- Cost per execution: $0.15
- Daily runs for a year: $54.75
- pflow: $0.15 once for the entire year
- **Savings: $54.60 (99.7%)**

## The Uncomfortable Truth

MCP is revolutionary, but it has a scalability problem nobody wants to discuss. As you add more tools:

- Context windows explode
- Costs become prohibitive
- Performance degrades
- Reliability drops

This isn't MCP's fault. It's a fundamental limitation of the "load everything every time" model.

## What This Means

If you're using AI agents with multiple tools, you have three choices:

1. **Limit yourself to 2-3 tools** (defeats the purpose)
2. **Accept $100s in daily costs** (unsustainable)
3. **Compile workflows once** (pflow approach)

## The Bigger Picture

We're not anti-MCP. We USE MCP. We just recognized that the context tax makes it unusable at scale without compilation.

Every workflow system will eventually need to solve this:
- Load all tools every time (current state, doesn't scale)
- Manually specify tools (terrible UX)
- Automatically compile tool selection (pflow)

We chose to solve it now.

## Try It Yourself

```bash
# See your actual context usage:
$ claude --mcp-config ./github.mcp.json ./slack.mcp.json ./jira.mcp.json \
         --strict-mcp-config --debug "simple task"
> Context used: 64,050 tokens before processing

# Same task with pflow:
$ pflow "simple task"  # First time: compiles
$ pflow run simple-task  # Every time after: 0 tokens
```

## "But I Have Claude Pro Unlimited..."

Sure, you pay $200/month and get "unlimited" compute. Three problems with that:

### 1. Time Is Not Unlimited
Your 3-step workflow with MCP servers (documented industry average):
- Loading schemas: 2-3 seconds
- Tool 1 execution + AI reasoning: 10-15 seconds
- Tool 2 execution + AI reasoning: 10-15 seconds
- Tool 3 execution + AI reasoning: 10-15 seconds
- Final summary generation: 5-10 seconds
- Total: **30-120 seconds** per execution

Same workflow compiled with pflow:
- **2-5 seconds** flat (no reasoning, just execution)

Run this 20 times a day? You're wasting 30+ minutes daily waiting for AI to think through the same steps. That's 2.5 hours per week of pure waiting.

### 2. "Unlimited" Has Limits (August 2025 Update)
Anthropic just ADDED more restrictions despite the $200 price tag:
- New weekly usage caps on top of existing limits
- Heavy users report hitting caps within days
- Professional developers are "canceling en masse"
- Even at $200/month, it's "just buying more throttled access"

That $200 "unlimited" plan? It's neither unlimited nor sustainable.

### 3. The Subsidy Won't Last
One user hit 10 billion tokens in a month on Claude Code. That's $150,000 of compute for a $200 subscription. The math:

```
What they assumed: Today's Price - (10x Cheaper Compute) = Profit
What they got: Today's Price - (100x More Token Use) = Massive Loss
```

History lesson from cloud computing:
- **2010**: "Unlimited" cloud storage everywhere
- **2012**: Google Drive caps at 15GB
- **2014**: OneDrive pulls unlimited plan
- **2016**: Amazon Drive kills unlimited

AI compute is 1000x more expensive than storage. Those $200 unlimited plans are VC-subsidized customer acquisition. When the music stops (and it will), you'll either pay real costs or lose access.

Windsurf got acquired in a $5.4B bidding war (economics matter). Claude added MORE restrictions. The correction is happening now.

## The Non-Determinism Tax

Here's the problem nobody talks about: Every time AI reasons through your workflow, it might do something different:

```bash
Run 1: Fetches 20 PRs, checks all files, posts detailed summary
Run 2: Fetches 10 PRs, skips some checks, posts brief summary
Run 3: Fetches 20 PRs, adds "helpful" suggestions you didn't ask for
```

You can't:
- Debug why Tuesday's report looks different from Monday's
- Share the "fix" with your team (there is no fix)
- Trust it for critical operations
- Build reliable systems on top of it

With pflow compilation, you get the EXACT same workflow every time. Deterministic. Debuggable. Trustworthy.

## The Bottom Line

Whether you're paying per token or riding the unlimited wave, you're still:
- **Waiting 30-120 seconds** for what should take 2-5 seconds
- **Hitting context limits** that make work impossible
- **Playing the training data lottery** (will the AI remember this CLI?)
- **Getting different results** each run (non-deterministic)
- **Building on unsustainable economics** that will change

The current "solution" - hoping AI remembers bash commands from 2023 while avoiding MCPs that actually work - isn't a strategy. It's desperation.

pflow isn't about saving money (though it does). It's about making AI workflows that actually work—fast, reliable, scalable. No token tax. No training data lottery. No non-determinism. Just compiled workflows that execute exactly as designed, every time.

The math is simple. The time savings are massive. The current model is unsustainable.

---

*Note: All token counts and performance issues mentioned are from documented GitHub issues, research papers, and developer reports (2024-2025). The GitHub MCP server 46k token overhead is specifically documented in issue #3036 on anthropics/claude-code.*

*pflow is open source (FSL/Apache). We built it because we were tired of paying the context tax. You can [grab it here](https://github.com/youruser/pflow) and stop paying it too.*

*Discussion on [HN](https://news.ycombinator.com/item?id=xxx) | [Twitter](https://twitter.com/xxx)*