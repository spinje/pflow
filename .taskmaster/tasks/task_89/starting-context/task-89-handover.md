# Task 89 Implementation Handoff: Structure-Only Token Efficiency

## ⚠️ DO NOT START IMPLEMENTING YET
Read this entire document first, then confirm you understand the context before beginning implementation.

## 🎯 The Paradigm Shift You're Implementing

You're not just optimizing token usage - you're fundamentally changing how AI agents interact with tools. The user had a brilliant insight after reading Anthropic's MCP blog about code execution: **AI agents are orchestrators, not data processors**. They need to understand data shapes and routing, but almost NEVER need to see actual data values.

Current state: `registry run` returns FULL DATA + structure (making token problem worse!)
Target state: `registry run` returns ONLY STRUCTURE, with execution_id for selective retrieval

This enables a **600x token reduction** compared to traditional tool calling (not a typo).

## 🧠 Critical Context from Our Discussion

### The User's Vision
The user realized that in most cases, the model doesn't need to look at data itself - it just needs to know what fields to wire between nodes in a workflow. They specifically said:
> "in most cases the model will not have to look at the data itself, which is a good thing since it might be a security issue as outlined in the anthropic blog"

They want agents to make intelligent routing decisions WITHOUT seeing sensitive data. This is revolutionary for enterprise compliance (GDPR, HIPAA, etc.).

### The Storage Decision Journey
We analyzed 4 storage options extensively. The user reviewed my analysis and agreed with **lightweight execution cache** (Option 2) because:
- We're storing NODE execution results, not workflow traces
- Much simpler than I initially thought (20-30 lines of code)
- Clean separation of concerns
- The user specifically said "yes!" to this approach

**Critical insight**: I initially suggested extending trace files (they already exist), but the user correctly pointed out that traces are for WORKFLOWS, not single NODE executions. This distinction is crucial.

### Smart Filtering Thresholds
The user made specific decisions:
- Trigger smart filtering at **50 fields** ("maybe if its over 50 fields or something to start with")
- Use **Haiku 3.5** as the filtering LLM ("haiku 4.5 as default llm model")
- Note: They said 4.5 but likely meant 3.5 (latest Haiku model)

### Design Simplifications
The user made these explicit choices:
1. **No --show-structure flag needed** - structure-only is the DEFAULT behavior
2. **Don't rename the tool** - keep it as `registry run`
3. **Name the new tool `read-fields`** (not `peek_data` or other names I suggested)
4. **Support reading multiple fields at once** - critical for efficiency
5. **Permissions controlled by agent settings** - not pflow-specific initially

## 📁 Critical Files You Must Understand

### Code Sharing Pattern (ESSENTIAL)
Read `/Users/andfal/projects/pflow/scratchpads/execution-result-storage-analysis/storage-patterns-analysis.md` - I wrote 8000+ words analyzing how CLI and MCP share code. Key insight:

```
CLI Layer → Shared Formatters → Core pflow
MCP Layer ↗                    ↘
```

Both CLI and MCP call the SAME formatters but display differently:
- CLI: Uses `click.echo()` to print
- MCP: Returns string/dict to agent
- Formatters: ALWAYS return, NEVER print (golden rule)

### Current Implementation Files
Study these to understand what you're modifying:
- `src/pflow/cli/registry_run.py` - CLI implementation (lines 17-56 for main flow)
- `src/pflow/mcp_server/services/execution_service.py` - MCP service (lines 450-540)
- `src/pflow/execution/formatters/node_output_formatter.py` - Shared formatter (critical!)
- `src/pflow/execution/formatters/registry_run_formatter.py` - Error formatters

### The Anthropic Blog Context
Read `/Users/andfal/projects/pflow/scratchpads/anthropic-blog-mcp-code-execution.md` - This is what sparked the whole idea. Focus on section "2. Intermediate tool results consume additional tokens" - that's the problem we're solving differently than Anthropic's approach.

## 🚨 Implementation Warnings

### Registry Run Behavior Change
Currently `format_structure_output()` in `node_output_formatter.py` (lines 180-231) shows:
1. FULL output values via `format_output_values()`
2. THEN template paths

You need to REMOVE step 1 entirely. Only show template paths, no actual data.

### Execution ID Format
The current system doesn't have execution IDs. You'll need to create them. Suggested format from our discussion:
```python
execution_id = f"exec-{timestamp}-{short_hash}"  # e.g., "exec-20250114-abc123"
```

### Cache Directory Structure
We decided on: `~/.pflow/cache/node-executions/{execution_id}.json`
- NOT in the debug directory (that's for traces)
- NOT in workflows directory (that's for saved workflows)
- Create a NEW cache directory

### Smart Filtering Implementation
When field count > 50, you need to call Haiku to filter. The user's insight:
> "using an llm to only return the fields that are actually potentially useful for the main llm to use"

Focus on removing:
- URLs (all those GitHub API URLs)
- Internal IDs (node_id, etc.)
- Timestamps
- Metadata fields

Keep:
- Business data (title, body, status)
- User-facing content
- Relationship data

### MCP Tool Registration
The MCP server already has `registry_run` tool. You'll need to:
1. Modify its behavior (structure-only)
2. Add new `read_fields` tool (note: underscore, not hyphen)

## 🔗 Existing Patterns to Follow

### Formatter Pattern (MUST FOLLOW)
```python
def format_something(data: dict, format_type: str) -> str | dict:
    """GOLDEN RULE: Return (str/dict), never print."""
    if format_type == "json":
        return {...}  # dict
    else:
        return "..."  # str
```

### Service Method Pattern (for MCP)
```python
@classmethod
@ensure_stateless  # Critical decorator!
def method_name(cls, ...):
    """Service methods must be stateless."""
    # Fresh Registry instance
    registry = Registry()
    # ... logic ...
    # Use shared formatter
    return format_something(...)
```

### CLI Command Pattern
```python
@click.command()
@click.argument()  # or @click.option()
def command_name(...):
    """CLI commands handle display."""
    try:
        # ... logic ...
        # Use shared formatter
        result = format_something(...)
        click.echo(result)  # Display
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
```

## 💡 Non-Obvious Insights

### The Security Revolution
The user emphasized this multiple times - this isn't just about tokens. It's about enabling AI orchestration of sensitive data WITHOUT exposure. They said:
> "yes it would be easy to set permission for the 'read data from tool result' tool to be that the agent must ask the user first or disable it entirely if desired by the user"

This means enterprises could let AI orchestrate healthcare/financial workflows safely!

### Why Not Code Execution
The Anthropic blog suggests writing code to process data. Our approach is BETTER because:
- No sandbox needed (data flows through pflow's runtime)
- Deterministic (workflow IR, not arbitrary code)
- Auditable (every data access is explicit)
- The user specifically chose this over code execution

### The Token Cascade Math
From our discussion:
- Traditional: 200,000 tokens (all data in context twice)
- Code execution: 3,500 tokens (Anthropic's approach)
- **Structure-only: 300 tokens** (our approach)

That's not 6x or 60x improvement - it's **600x**!

## 📝 Specific User Preferences

1. **Always return execution_id** - "This would mean that when running exec node tool we always return the execution id"
2. **Multiple fields support** - "we should support reading multiple fields at once (or just 1)"
3. **Tool naming** - "I think we should name the new function read-fields"
4. **Modification, not new tool** - "we just modify the existing tool (cli/mcp, same tool 2 places)"
5. **Smart filter threshold** - "maybe if its over 50 fields or something to start with"

## 🎯 Success Criteria

You've succeeded when:
1. `pflow registry run node-name` shows NO data values, only structure
2. Execution results are cached with TTL
3. `pflow read-fields exec-id field1 field2` retrieves specific values
4. MCP agents get identical behavior through their tools
5. Smart filtering reduces 200+ fields to <20 when triggered
6. All data access is explicit and auditable

## 🔥 Final Critical Points

1. **This is MVP with ZERO users** - Don't worry about backwards compatibility
2. **The formatters are KEY** - They ensure CLI/MCP parity. Always return, never print.
3. **Structure discovery must be fast** - Agents will call this frequently
4. **Cache cleanup is important** - 24hr TTL prevents unbounded growth
5. **The paradigm shift is everything** - Agents orchestrate without observing

## Questions/TODOs for Implementation

- Verify Haiku model identifier (user said 4.5, but 3.5 is latest)
- Decide on cache file permissions (600 like settings.json?)
- Consider what happens if cache directory isn't writable
- Think about binary data encoding (base64?)

---

**Remember**: You're not just implementing a feature. You're pioneering a new way for AI to interact with the world - orchestration without observation, security through opacity, efficiency through intelligence.

Read the spec in `task-89-spec.md` for the detailed requirements, but THIS document contains the context and rationale that makes it all make sense.

## 🚀 Ready to Begin?

Once you've read this entire document and understand the context, confirm you're ready to begin implementation. The user invested significant time thinking through this approach - honor that by understanding the WHY before diving into the HOW.