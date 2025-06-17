# CLI Planner Task Updates

## New Understanding

The user wants to:
1. **MVP**: Treat ALL input (natural language AND CLI pipe syntax) as natural language, send to LLM
2. **v2.0**: Add direct CLI parsing optimization later
3. Focus on simplicity for MVP

## Task Updates Needed

### 1. Update Task #19 - Workflow Generation Engine

Current: Only mentions natural language
Needed: Should handle BOTH natural language and CLI pipe syntax via LLM

**Updated details should include**:
- Accepts both natural language AND CLI pipe syntax as input
- For MVP, routes both through LLM for interpretation
- LLM understands pipe syntax as a "domain-specific language"
- Generates appropriate template variables for missing parameters

### 2. Add New Task #30 - Shell Pipe Integration

Looking at the task list, there's already task #12 mentioned in taskmaster but it doesn't exist in tasks.json!
We need to add it.

### 3. Add New v2.0 Task - Direct CLI Parsing (Deferred)

Add a new task that's explicitly marked as v2.0:
- Direct parsing of CLI pipe syntax without LLM
- Generate IR directly from parsed syntax
- Performance optimization over LLM approach

### 4. No Changes Needed to Task #4

Task #4 is about runtime CLI parameter resolution, not parsing. It's correctly scoped.

## Shell Integration Pattern

From Simon Willison's `llm`:
```python
# Good pattern for pipe detection
if not sys.stdin.isatty():
    stdin_data = sys.stdin.read()
    shared["stdin"] = stdin_data
```

This is already mentioned in our docs, good to keep.
