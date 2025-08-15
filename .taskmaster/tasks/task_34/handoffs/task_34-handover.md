# Task 34 Handoff: Critical Context for Prompt Accuracy Tracking

**IMPORTANT**: Do not begin implementing immediately after reading this. Read everything, understand the context, and explicitly state that you're ready to begin.

## Critical Discoveries You Need to Know

### 1. The Prompts Were Just Extracted
The user recently refactored all prompts from inline code in `nodes.py` to separate markdown files in `src/pflow/planning/prompts/`. This is fresh work - the prompts use `{{variable}}` placeholders (double braces, not single). The extraction is complete but there's no accuracy tracking yet.

### 2. Abandoned Template System
There's a file `src/pflow/planning/prompts/templates.py` that's completely orphaned - no code references it. This was likely an earlier attempt at prompt management that was abandoned. Don't be confused by it or try to integrate with it.

### 3. Existing Test Infrastructure Works
The tests in `tests/test_planning/llm/prompts/` already:
- Make real LLM API calls when `RUN_LLM_TESTS=1` is set
- Validate response structure and content
- Have clear patterns for testing each node

You don't need to reinvent testing - just add accuracy tracking on top.

### 4. The User's Real Need
The user wants to improve ONE prompt at a time to 100% accuracy. They want to:
1. Open a prompt file
2. See current accuracy (e.g., "85%")
3. Edit the prompt
4. Run tests
5. See if accuracy improved
6. Commit only improvements

This is about rapid iteration, not building a framework.

## Non-Obvious Implementation Details

### LLM Response Variance
The LLM responses aren't perfectly deterministic. In Task 27 debugging, we discovered `response.usage` is sometimes a method `usage()` and sometimes a property. The test accuracy might vary 2-3% between runs. Only update accuracy on significant improvements (>2-3%).

### Test Execution Pattern
The existing tests follow this pattern:
```python
node = WorkflowDiscoveryNode()
shared = {"user_input": "...", "workflow_manager": WorkflowManager()}
prep_res = node.prep(shared)
exec_res = node.exec(prep_res)  # Real LLM call happens here
```

You'll need to count passed/failed test cases from these exec_res validations.

### Prompt Loading
The current `loader.py` just reads the file and strips headers. It doesn't handle frontmatter. You'll need to:
1. Parse YAML frontmatter
2. Extract the prompt content after `---`
3. Make sure the existing loader still works

### Git Noise is Acceptable
We had a discussion about whether updating accuracy in source files would create git noise. The conclusion: it's worth it for developer experience. The user WANTS to see accuracy improvements in git history. Don't try to avoid commits - embrace them as progress markers.

## Task 27 Context That Might Help

We just built a comprehensive debugging system (Task 27) that captures all LLM calls during planner execution. While not directly related, it shows:
- How to intercept LLM calls (though you won't need this)
- The importance of developer visibility
- That progress indicators and immediate feedback matter

The trace files are saved to `~/.pflow/debug/` and contain all prompts and responses. This could be useful for understanding what prompts actually look like in practice.

## Files You Must Understand

1. **Prompt Files**: `src/pflow/planning/prompts/*.md`
   - Currently just markdown with `{{variables}}`
   - Need frontmatter added

2. **Test Files**: `tests/test_planning/llm/prompts/test_*.py`
   - Already test the prompts
   - Need to expose accuracy metrics

3. **Loader**: `src/pflow/planning/prompts/loader.py`
   - Simple file reading
   - Needs frontmatter parsing

## Anti-Patterns to Avoid

1. **Don't Build a Framework**: The user explicitly wants simplicity. A single Python script is better than a complex system.

2. **Don't Hide the Tool**: This is developer-only. Don't integrate with the main pflow CLI. Keep it as a standalone script.

3. **Don't Track Everything**: Just track accuracy. Not timing, not token usage, not cost. Accuracy only.

4. **Don't Fear Frontmatter**: Adding YAML frontmatter to markdown is standard practice. Don't overthink it.

## The Simplicity Principle

Throughout our discussion, the user pushed back on complexity multiple times:
- "I want to keep things simple"
- "Why is this better than just running the tests directly?"

They want the MINIMUM viable solution that shows accuracy in the file. If you're building abstractions or frameworks, you're overengineering.

## Test Execution Gotcha

The tests use pytest with a special environment variable gate:
```python
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"),
    reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)
```

Your test runner MUST set `RUN_LLM_TESTS=1` or the tests will skip silently.

## Final Critical Insight

The user's workflow is:
1. See accuracy is 85%
2. Think "I can beat that"
3. Edit prompt
4. Test
5. See 90%
6. Feel satisfaction
7. Commit "Improved discovery: 85% → 90%"

This emotional feedback loop is the core value. Don't break it with complexity.

## What Success Looks Like

When you're done, a developer should be able to:
```bash
cd src/pflow/planning/prompts
python test_runner.py discovery
# See: "Results: 18/20 = 90%"
python test_runner.py discovery --update
# See: "✅ Updated: 85% → 90%"
git diff discovery.md
# See: accuracy changed from 85.0 to 90.0
```

That's it. Nothing more complex.

---

**Remember**: Read all of this, understand the context, and then explicitly say you're ready to begin implementation. Don't jump straight into coding.