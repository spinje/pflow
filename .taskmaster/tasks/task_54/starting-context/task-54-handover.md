# Task 54 Handoff Memo - HTTP Node Implementation

**⚠️ TO THE IMPLEMENTING AGENT**: Read this entire memo before starting. At the end, confirm you understand and are ready to begin.

## 🎯 The Real Story Behind This Task

You're implementing an HTTP node, but here's what the documents won't tell you: this is pflow's first node that directly calls an external service using a Python library (requests). Every other external service node uses subprocess + CLI tools. This makes your implementation a potential template for future direct-API nodes.

The research revealed that 60% of HTTP operations are simple GET/POST with JSON, and 70% of auth is API keys. This drove every design decision. Don't second-guess the simplicity - it's intentional.

## 🚨 Critical Discovery: Two Error Handling Patterns Exist

During codebase analysis, I discovered pflow has TWO conflicting error handling patterns:

**Pattern A (File Nodes)**: Return error string from exec_fallback
```python
def exec_fallback(self, prep_res, exc) -> str:
    return f"Error: {exc}"  # String gets checked in post()
```

**Pattern B (GitHub/LLM Nodes)**: Raise ValueError from exec_fallback
```python
def exec_fallback(self, prep_res, exc) -> None:
    raise ValueError(f"Operation failed: {exc}")  # Exception propagates
```

**YOU MUST USE PATTERN B** - The GitHub/LLM pattern is newer and more correct. The file pattern exists for legacy reasons. This wasn't obvious and took deep analysis to determine.

## 💡 The HTTP Error vs Network Error Distinction

This is subtle but crucial:

- **HTTP errors (4xx, 5xx)**: These are VALID RESPONSES. The requests library returns a Response object with status_code set. These are handled in `post()` by checking status_code.
- **Network errors (timeout, connection refused)**: These are EXCEPTIONS. They bubble up through `exec()`, trigger retries, and eventually hit `exec_fallback()`.

The spec assumes `requests.request()` returns Response objects for all status codes without raising. This is TRUE by default, but only if you don't use `raise_for_status()`. Don't add it.

## 🔑 What I Added Despite No Codebase Precedent

1. **Query parameters as dict (`params`)**: No existing node has this. I added it based on external research showing it's cleaner than URL manipulation. The user didn't object when I flagged it.

2. **Separate auth parameters**: The task document wanted this, research validated it (70% API key, 20% Bearer), but no node has this exact pattern. MCP node has complex env var expansion but that's different.

3. **Multiple error actions were rejected**: The task suggested `success/client_error/server_error/timeout` actions. The codebase ONLY uses `default/error`. I changed this in the spec after verification.

## ⚠️ Gotchas That Almost Got Me

1. **Environment variable expansion**: The research findings document showed example code with `os.path.expandvars()` for auth tokens. This is WRONG. Only MCP node does this, and it's a special case. Don't implement it.

2. **NonRetriableError has a bug**: The tests revealed that NonRetriableError still triggers retries despite its name. This is a known issue. Don't try to fix it or work around it.

3. **The shell=False pattern**: Every GitHub node obsessively sets `shell=False` for security. This doesn't apply to HTTP but shows the security-first mindset you need.

4. **Test mocking level**: GitHub nodes mock at subprocess level, you'll mock at requests level. This is intentional - mock at the boundary of your node's responsibility.

## 📊 Research Insights That Matter

From analyzing n8n, Zapier, and other tools:
- 30-second timeout is universal (Power Automate, n8n all use it)
- JSON-first approach matches 60% of real usage
- Method auto-detection (POST with body, GET without) is standard
- Users think "fetch" → GET, "send" → POST, "update" → PUT

This isn't just interesting - it validates every design choice in the spec.

## 🔗 Critical Files to Reference

**For patterns to FOLLOW**:
- `/src/pflow/nodes/github/get_issue.py` - Best example of Pattern B error handling
- `/src/pflow/nodes/llm/llm.py` - Shows parameter fallback and Interface format
- `/src/pflow/nodes/github/CLAUDE.md` - Explains why they use CLI (context for why you're different)

**For patterns to AVOID**:
- `/src/pflow/nodes/file/copy_file.py` - Uses Pattern A (string errors) - DON'T COPY THIS
- `/src/pflow/nodes/mcp/node.py` - Has env var expansion - DON'T COPY THIS

**Your implementation guide**:
- `/Users/andfal/projects/pflow/.taskmaster/tasks/task_54/starting-context/http-node-implementation-guide.md` - Has complete implementation
- `/Users/andfal/projects/pflow/.taskmaster/tasks/task_54/starting-context/task-54-spec.md` - Formal spec with all rules

## 🎭 The Unspoken Architecture Decision

Why does pflow use GitHub CLI instead of PyGithub or requests? It's not laziness - it's architectural philosophy: "Stay close to the command line." Your HTTP node breaks this pattern by necessity (there's no universal HTTP CLI tool like `gh`), but be aware you're setting precedent. Future developers might point to your node as justification for more direct Python library usage.

## ⚡ Performance Expectations

The GitHub CLI nodes have 50-100ms overhead from subprocess. Your HTTP node with requests should be faster for simple calls but might be slower for complex ones due to Python overhead. Don't optimize prematurely - the retry mechanism is more important than raw speed.

## 🧪 Testing Subtlety

The test examples in the implementation guide are complete, but here's what's not obvious: the retry test MUST verify the mock is called multiple times. This proves the retry mechanism works. Without this, you might have broken retries and never know.

Also, mock `response.elapsed.total_seconds()` - I included this in examples but it's easy to miss. Without it, you'll get AttributeError in tests.

## 🤔 Unanswered Questions

I flagged these as unknowns in the Epistemic Appendix:
1. Should auth tokens/API keys expand environment variables like `${API_KEY}`? (Currently: NO)
2. What's the max response size before memory issues? (Currently: Undefined, handle normally)
3. Should we support custom SSL certificates? (Currently: NO, use requests defaults)

If these come up during implementation, make a conservative choice and document it.

## 🚀 Why This Implementation Matters

This HTTP node enables pflow to finally do "real" API integration without shell hackery. It's the foundation for webhook notifications, API monitoring, and data fetching. But more importantly, it proves pflow can elegantly integrate Python libraries when needed while maintaining its patterns.

The research showed users need this desperately - they're currently using `shell + curl` combinations that are fragile and hard to debug. Your implementation fixes a real pain point.

## 🎯 Final Critical Reminders

1. **NO try/except in exec()** - I cannot stress this enough. It breaks retries.
2. **Raise ValueError from exec_fallback()** - Don't return strings like file nodes
3. **Only "default" and "error" actions** - Ignore what the task document originally said
4. **Mock at requests level** - Not subprocess like GitHub nodes
5. **HTTP errors aren't exceptions** - 404 returns a valid Response with status_code=404

The implementation guide has a complete working example. Use it. But understand WHY each choice was made - that's what this memo provides.

---

**TO THE IMPLEMENTING AGENT**: You now have everything - the spec (rules), the implementation guide (how-to), and this memo (why). Together they form complete knowledge transfer. Please confirm you've read and understood this handoff, then you're ready to begin implementation of Task 54.