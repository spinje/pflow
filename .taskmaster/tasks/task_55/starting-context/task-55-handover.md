# Task 55 Implementation Handoff

## ⚠️ Critical Discovery: Infrastructure Already Exists

**The most important thing to know**: The system already has MORE infrastructure than the task description suggests. Don't reinvent what's already there:

1. **Depth tracking exists**: The `_pflow_depth` key in shared storage already tracks nesting level automatically. WorkflowExecutor increments it for nested workflows. You don't need to build depth tracking - just read `shared.get("_pflow_depth", 0)`.

2. **InstrumentedNodeWrapper, not WorkflowExecutor**: The task file originally said to add callbacks to WorkflowExecutor - that's wrong. Every node already goes through InstrumentedNodeWrapper (line 223-276 in `src/pflow/runtime/instrumented_wrapper.py`). That's your single integration point.

3. **Callback patterns exist**: The planner already uses a clean callback pattern through PlannerProgress (`src/pflow/planning/debug.py:589-612`). Copy its approach.

## 🎯 Core Implementation Path

### The Flow (what took me hours to figure out):
```
CLI main.py → _prepare_shared_storage() → adds __progress_callback__ to shared_storage
→ flow.run(shared_storage) → PocketFlow orchestration
→ InstrumentedNodeWrapper._run() sees callback in shared storage
→ Calls callback at start/complete → Output appears
```

### Exact Integration Points:

1. **Add -p flag** at line 1756-1770 in `src/pflow/cli/main.py`:
   ```python
   @click.option("-p", "--print", "print_flag", is_flag=True, help="Force non-interactive output")
   ```

2. **Modify _prepare_shared_storage()** at line 569-584 in main.py to accept OutputController and add callback to shared storage

3. **Hook into InstrumentedNodeWrapper._run()** at line 246 and 264:
   - Before `self.inner_node._run(shared)` - call node_start
   - After successful completion - call node_complete with duration_ms
   - Wrap in try/except so callback errors don't break execution

## 🚨 Hidden Gotchas

### TTY Detection Edge Cases
- **Both streams must be TTY**: Use `sys.stdin.isatty() AND sys.stdout.isatty()`
- **Partial pipes break interactivity**: If only stdin OR stdout is piped, treat as non-interactive
- **Windows GUI apps**: sys.stdin can be None - always check before calling isatty()
- **The -p flag is critical**: It's not just convenience - some CI systems have broken TTY detection

### Shared Storage Reserved Keys
The system uses `__` prefix for system keys. I found these in use:
- `__llm_calls__` - LLM usage tracking
- `__is_planner__` - Marks planner execution
- `__progress_callback__` - Your new key for callbacks
- `_pflow_depth`, `_pflow_stack` - Workflow nesting (note single underscore)

### Progress Output Rules
- **All progress to stderr**: Even in interactive mode, use `click.echo(msg, err=True)`
- **Results to stdout only**: Never mix progress with results
- **JSON mode implies non-interactive**: If --output-format json, suppress all progress

## 🔍 What I Researched (So You Don't Have To)

### How Nodes Actually Execute
The execution chain is: `Flow._orch()` (pocketflow/__init__.py:98-108) calls `node._run()` which goes through these wrapper layers:
1. InstrumentedNodeWrapper (metrics/tracing)
2. NamespacedNodeWrapper (storage isolation)
3. TemplateAwareNodeWrapper (variable resolution)
4. Actual node's prep/exec/post

### How the Planner Shows Progress
Study `src/pflow/planning/debug.py:589-612`. The PlannerProgress class has the exact format you need to match:
- Start: `click.echo(f"{name}...", err=True, nl=False)`
- Complete: `click.echo(f" ✓ {duration:.1f}s", err=True)`

### How Nested Workflows Work
WorkflowExecutor creates child storage with `_create_child_storage()` (line 283-327 in workflow_executor.py). It:
- Increments `_pflow_depth` automatically
- Maintains execution stack for circular dependency detection
- Has 4 storage isolation modes (mapped/isolated/scoped/shared)

## 📂 Files You'll Be Modifying

1. **`src/pflow/cli/main.py`** (1886 lines) - Add flag, create OutputController, modify _prepare_shared_storage
2. **`src/pflow/runtime/instrumented_wrapper.py`** (276 lines) - Add 3-4 lines for callback invocation
3. **`src/pflow/planning/debug.py`** - Make PlannerProgress respect is_interactive
4. **`src/pflow/core/output_controller.py`** (NEW) - Create OutputController class

## ⚡ Quick Wins

1. **Start with non-interactive fix first** - It's simpler and more critical. Just suppress output when not interactive.

2. **Test with this command**: `echo "test" | pflow "echo hello" | cat` - Should output ONLY "hello" with no progress

3. **Copy from PlannerProgress** - The exact progress format is already defined. Don't innovate here.

4. **Use existing test patterns** - Look at `tests/test_cli/test_workflow_output_handling.py` for how to test CLI output

## ❌ What NOT to Do

- **Don't modify PocketFlow core** - Use shared storage for callbacks
- **Don't create a new wrapper** - InstrumentedNodeWrapper is already there
- **Don't track depth manually** - _pflow_depth already exists
- **Don't add performance metrics** - The spec removed those arbitrary requirements for good reason
- **Don't worry about Ctrl+C** - That's a separate concern

## 🎭 Context the User Cares About

The user emphasized:
- "focus on whats important to get the features working" - Don't over-engineer
- They want Unix composability - pipes must work cleanly
- The solution should follow existing patterns in the codebase

## 🔗 Key Research Documents

- **Research findings**: `.taskmaster/tasks/task_55/starting-context/research-findings.md` - All my discoveries
- **Updated spec**: `.taskmaster/tasks/task_55/starting-context/task-55-spec.md` - Resolved ambiguities
- **Test patterns**: `tests/test_cli/CLAUDE.md:49` - Warning about CliRunner TTY limitations

## 💡 Final Insight

The codebase is more sophisticated than it appears. The infrastructure for this feature is 90% already there - you're just adding the UI layer on top. The hardest part was discovering what already existed, not figuring out what to build.

---

**IMPORTANT**: Do not begin implementing yet. Read this handoff, review the spec and research documents, then confirm you're ready to proceed with implementation.