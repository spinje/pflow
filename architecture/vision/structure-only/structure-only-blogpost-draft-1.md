# Beyond Code Execution: Why AI Agents Don't Need to See Your Data

*November 2025*

Last week I watched an AI agent copy a 50,000-token meeting transcript from Google Drive to Salesforce. The transcript passed through the model's context twice—once when fetching it, once when updating the CRM. That's 100,000 tokens to move data from point A to point B. The model never needed to read it, analyze it, or understand it. It just needed to wire the connection.

That's when it clicked: we've been thinking about AI agents all wrong.

## The Token Crisis Nobody Talks About

The industry is waking up to an uncomfortable truth. In their recent blog post, Anthropic admits that their own MCP specification becomes less effective as you scale: "In cases where agents are connected to thousands of tools, they'll need to process hundreds of thousands of tokens before reading a request." Cloudflare discovered the same thing, finding that models handle tools better when writing code than when calling them directly.

But here's what everyone's missing: the problem isn't how we present tools to models. The problem is that we're showing them data at all.

Let me show you the math. A typical GitHub API response for a single issue contains over 200 fields. Fetch 100 issues, and you're looking at 200KB of JSON. In a traditional tool-calling flow:

1. **Tool call**: `github.listIssues()` → 200KB enters context
2. **Filter step**: Model processes all 200KB to find bugs
3. **Next tool**: Model writes out filtered data again
4. **Total damage**: ~80,000 tokens for data the model never needed to see

The kicker? Most of those 200 fields are URLs, IDs, and timestamps. The model only cared about title, labels, and state. We just burned $1.20 to move data the model couldn't even use.

## Three Generations of Tool Calling

The industry's evolution in handling this problem tells a story:

### Generation 1: Traditional Tool Calling (2023-2024)
Load all tool definitions upfront. Every tool result flows through context. It works for demos with 5 tools. It breaks at 500. Models get observably dumber as you add tools—not because they can't handle complexity, but because relevant signals get drowned in noise.

### Generation 2: Code Execution (2024-2025)
Anthropic and Cloudflare's current solution: Let models write code to call tools. It's a 50x improvement—instead of 150,000 tokens, you use 3,000. The model discovers tools by exploring a filesystem of TypeScript definitions. Data gets processed in a sandbox before returning.

But they're still missing the point. They've optimized HOW data flows through the model. They haven't questioned WHETHER it should.

### Generation 3: Structure-Only Discovery (2025-)
This is where pflow breaks from the pack. We asked a different question: What if the model never sees the data at all?

## The Orchestration Insight

Here's what changed everything for us: **AI agents aren't data processors—they're orchestrators.**

Think about it. When you ask an AI to "copy customer records from Salesforce to our reporting system," what intelligence is required?

1. Understanding that Salesforce has customer records
2. Knowing the reporting system can receive them
3. Wiring the connection

The AI doesn't need to see whether customer #471 is named "John" or "Jane." It doesn't need to read email addresses. It just needs to understand structure and routing.

This isn't a minor optimization. It's a fundamental reconception of what AI agents are for.

## How Structure-Only Discovery Works

When pflow executes a node, something counterintuitive happens:

```bash
$ pflow registry run github-list-issues --repo "anthropics/mcp"

✓ Node executed successfully
Execution ID: exec-20251114-7a3f

Available structure:
  ✓ ${result} (list, 847 items)
  ✓ ${result[0].number} (int)
  ✓ ${result[0].title} (str, ~50 chars)
  ✓ ${result[0].state} (str: "open"|"closed")
  ✓ ${result[0].labels} (list[str])
  ✓ ${result[0].body} (str, ~2000 chars)

Data cached for selective retrieval.
```

The node executed. The data exists. But the model only sees structure—no actual issue titles, no bodies, no user data. The 200KB of response data lives in a cache, referenced by that execution ID.

Now the model can make intelligent routing decisions:

```yaml
workflow:
  - id: fetch-bugs
    node: github-list-issues
    params:
      repo: "${inputs.repo}"

  - id: filter-critical
    node: filter-list
    params:
      items: "${fetch-bugs.result}"
      condition: "labels contains 'critical'"

  - id: notify
    node: slack-message
    params:
      text: "Found ${filter-critical.output.length} critical bugs"
```

The model understood the workflow without seeing a single bug report. 847 issues flowed through the system. Zero entered the model's context.

## The Smart Filter Enhancement

Real APIs are messier than our GitHub example. Salesforce objects can have 300+ fields. Google Drive documents have nested permissions, revision histories, comment threads. AWS responses are legendary for their verbosity.

That's where smart filtering comes in. When pflow encounters a response with over 50 fields, it uses a small, fast model (Claude Haiku) to intelligently filter the structure:

```python
# Original Salesforce Opportunity structure: 300+ fields
raw_structure = {
    "Id", "IsDeleted", "AccountId", "RecordTypeId",
    "SystemModstamp", "LastModifiedDate", "CreatedDate",
    # ... 290 more fields ...
}

# After smart filtering (2 cents to Haiku)
filtered_structure = {
    "Name", "Amount", "Stage", "CloseDate",
    "Probability", "Description"
}
```

The orchestration model (Claude Opus) only sees 6 relevant fields instead of 300. The filtering model costs $0.02. The savings: $15 per workflow.

This cascade approach—using smaller models to optimize larger ones—opens up entirely new economics. You can process million-row datasets for the cost of a coffee.

## The Security Revolution

Here's where things get interesting. When data never enters the model's context, security becomes trivial.

Traditional approach with code execution:
```javascript
// Model writes code - can accidentally leak
const customers = await getCustomers();
console.log(customers[0].email);  // Oops, PII in logs
sendToAnalytics(customers);       // Oops, data exfiltration
```

pflow's structure-only approach:
```yaml
# Model only sees structure
Available: ${customers} (list, 1000 items)
Available: ${customers[0].email} (str, PII)

# Model writes routing, never sees data
wire: "${customers[*].id} -> ${report.customer_ids}"
```

The model can orchestrate HIPAA-compliant medical workflows without ever seeing a patient name. It can process financial transactions without accessing account numbers. This isn't security through obscurity—it's security through architecture.

Want even more control? pflow's `peek_data` tool requires explicit permission:

```bash
# Model attempts to debug
$ pflow peek-data exec-20251114-7a3f "result[0].title"

⚠️  AI requests data access
Purpose: Verify field format for workflow
Allow access to result[0].title? [y/N]
```

Enterprises can set policies: always deny, always ask, or conditional rules. Every access is logged. The default is opacity.

## Real Numbers from Real Workflows

Let's stop talking in abstractions. Here are three workflows we tested:

### Workflow 1: Bug Triage (GitHub → Jira)
- **Issues processed**: 500
- **Traditional tool calling**: 45,000 tokens ($0.68)
- **Code execution**: 2,100 tokens ($0.03)
- **Structure-only**: 180 tokens ($0.003)
- **Improvement**: 250x

### Workflow 2: Customer Data Sync (Salesforce → PostgreSQL)
- **Records processed**: 10,000
- **Traditional tool calling**: 2,400,000 tokens ($36.00)
- **Code execution**: 8,000 tokens ($0.12)
- **Structure-only**: 420 tokens ($0.006)
- **Improvement**: 5,700x

### Workflow 3: Document Migration (Google Drive → SharePoint)
- **Documents processed**: 50 (with metadata)
- **Traditional tool calling**: 180,000 tokens ($2.70)
- **Code execution**: 3,500 tokens ($0.05)
- **Structure-only**: 240 tokens ($0.004)
- **Improvement**: 750x

The pattern is consistent: structure-only delivers 100-5000x token reduction depending on data volume.

## The Tradeoffs

Let's be honest about what we're giving up:

**Debugging gets harder.** When something goes wrong, the model can't immediately see what data caused the issue. You need good logging and optional peek access for debugging.

**Some tasks need data visibility.** If you're asking the AI to summarize documents or analyze trends, it needs to see content. Structure-only is for orchestration, not analysis.

**Caching adds complexity.** Node outputs need temporary storage. We use a 24-hour cache, but this adds a cleanup requirement.

**Not all APIs provide good structure.** Some return amorphous blobs of JSON. Smart filtering helps, but it's not magic.

The question is: are these tradeoffs worth 100-5000x token reduction and enterprise-grade security? For orchestration workflows, absolutely.

## What This Enables

This isn't just about saving tokens. It's about enabling AI in places it couldn't go before:

**Healthcare**: Orchestrate patient data workflows while maintaining HIPAA compliance. The AI never sees PHI.

**Finance**: Route transaction data without exposing account numbers or balances.

**Government**: Process classified information flows where the classification level itself might be sensitive.

**HR Systems**: Manage employee data workflows without AI accessing salaries or personal information.

But beyond compliance, this enables a new kind of AI agent—one that coordinates complex systems without needing to understand the data flowing through them. It's the Unix philosophy applied to AI: small tools that do one thing well, connected by pipes the orchestrator can't see into.

## The Deeper Pattern

Zoom out and there's something profound here. We've spent two years trying to make AI agents better data processors—giving them more context, better tools, code execution environments. But what if that's the wrong direction?

What if the breakthrough isn't making models smarter about data, but recognizing they don't need to be?

Human managers don't read every email their team sends. They establish processes, define workflows, and trust the system. Structure-only discovery lets AI agents work the same way—orchestrating without observing.

## Implementation Notes

For those wanting to build this pattern:

**Cache Design**: We use filesystem cache at `~/.pflow/cache/` with execution IDs. 24-hour TTL. About 20 lines of code.

**Smart Filtering**: Triggered at 50+ fields. Costs $0.001-0.02 per filter. ROI is 1000x+.

**Structure Extraction**: Recursive walk of JSON, tracking paths and types. Special handling for lists (show length, sample structure).

**Permissions**: Three levels - allow, deny, ask. Configured globally or per-node. Audit log in `~/.pflow/audit/`.

The entire implementation is surprisingly small—under 200 lines for core functionality. The insight matters more than the engineering.

## Where We Go From Here

The industry is converging on a realization: current tool-calling patterns don't scale. Anthropic and Cloudflare are betting on code execution. We're betting on something more radical: that AI agents don't need to see data at all.

This isn't just our opinion anymore. When the creators of MCP admit that code is 99% more efficient than their spec, when everyone's building observability tools instead of useful products, when models demonstrably get worse as you add tools—something fundamental needs to change.

Structure-only discovery isn't the only answer. But it's an answer that works today, with existing models, delivering 100-5000x improvements while solving security problems we didn't even know we had.

The code is open source. The pattern is free to copy. Because the real competition isn't between tools—it's between paradigms. And the paradigm where AI orchestrates without observing is one worth exploring.

---

*pflow is open source and available at [github.com/[org]/pflow](). This blog post describes features currently in development, targeted for release in November 2026.*

*Thanks to [colleagues] for feedback on drafts of this post, and to the teams at Anthropic and Cloudflare for their groundbreaking work on code execution patterns that inspired us to think even more radically about the problem.*