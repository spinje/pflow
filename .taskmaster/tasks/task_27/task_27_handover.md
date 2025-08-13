# Task 27 Handoff: Critical Knowledge Transfer

**⚠️ STOP: Read this entire handoff before implementing anything. When you're done reading, just say you're ready to begin - don't start implementing yet.**

## The Real Problem We Discovered

The planner isn't just "not working" - it's **hanging indefinitely** with zero visibility. Users are running `pflow "analyze data"` and waiting 60+ seconds with no feedback, no error, nothing. The raw LLM dumps to terminal are making it worse, not better. We need surgical debugging, not more noise.

## Critical Discovery #1: You CANNOT Interrupt Python Threads

I spent hours verifying this. **Python threads cannot be killed or interrupted**. Period. This isn't a design choice - it's a CPython GIL limitation. What this means:

- The timeout mechanism can only **detect** that time has passed, not stop execution
- If an LLM call hangs for 5 minutes, we wait 5 minutes then report "timeout detected"
- This is why the spec says "timeout detection" not "timeout protection"

Files proving this:
- Our codebase search confirmed NO threading/async anywhere in `src/pflow/`
- The planner is completely synchronous single-threaded execution
- Signal handling exists (`src/pflow/cli/main.py:40-43`) but only for Ctrl+C

## Critical Discovery #2: The Attribute Delegation is EVERYTHING

The `DebugWrapper` class must perfectly mimic a PocketFlow node or the entire planner explodes. Here's what we discovered:

**What breaks everything:**
```python
class DebugWrapper:
    def __init__(self, node):
        self.node = node  # ❌ WRONG - Flow can't find attributes
```

**What actually works:**
```python
class DebugWrapper:
    def __init__(self, node):
        self._wrapped = node  # Store original
        self.successors = node.successors  # ✅ MUST copy this
        self.params = getattr(node, 'params', {})  # ✅ MUST copy this

    def __getattr__(self, name):
        # Handle special methods to prevent issues
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        return getattr(self._wrapped, name)  # ✅ Delegate everything else

    def __copy__(self):
        """✅ CRITICAL: Flow uses copy.copy() on nodes - MUST implement!"""
        import copy
        return DebugWrapper(copy.copy(self._wrapped), self.trace, self.progress)
```

The Flow class (`pocketflow/__init__.py:65-73`) calls `curr.successors.get()` directly. If `successors` isn't a direct attribute, boom - AttributeError.

## Critical Discovery #3: LLM Interception Pattern

Every planner node uses the EXACT same pattern:
```python
model = llm.get_model(prep_res["model_name"])
response = model.prompt(prompt, schema=SomeSchema)
```

We verified this in 7 different nodes. The interception point is `model.prompt()`, not `llm.get_model()`. See `src/pflow/planning/nodes.py` - search for "llm.get_model" (8 occurrences).

## Why We Made These Design Decisions

1. **Why ~/.pflow/debug/ not /tmp**: The entire codebase uses `~/.pflow/` for everything:
   - Registry: `~/.pflow/registry.json`
   - Workflows: `~/.pflow/workflows/`
   - We follow the pattern

2. **Why stderr for progress**: All CLI messages use `click.echo(err=True)`. This is consistent throughout `src/pflow/cli/main.py`. Using stdout would break pipe operations.

3. **Why no countdown timers**: `flow.run()` is completely blocking. We can't show "45s... 46s..." because we're stuck inside the synchronous call. We only get control back after it completes.

4. **Why the specific node-to-emoji mapping**: These are the actual 9 nodes in the planner (verified in `src/pflow/planning/flow.py`):
   - WorkflowDiscoveryNode → 🔍
   - ComponentBrowsingNode → 📦 (only in Path B)
   - ParameterMappingNode → 📝 (convergence point)
   - ...etc

## Files With The Actual Working Code

**DO NOT WRITE FROM SCRATCH** - We already have verified, working code:

1. **`main-agent-implementation-guide.md`** - Contains the COMPLETE DebugWrapper, TraceCollector, PlannerProgress classes, AND all utility functions. This code has been verified against PocketFlow's actual behavior.

2. **`test-writer-fixer-plan.md`** - Lists 30+ specific test cases that must pass. The test infrastructure now mocks at the LLM level, not module level.

## Subtle Bugs We Already Found and Fixed

1. **hasattr() bypasses __getattr__**: We discovered `hasattr(obj, 'successors')` returns False even with `__getattr__`. That's why we explicitly copy `successors`.

2. **copy.copy() is REQUIRED**: PocketFlow's Flow class uses `copy.copy()` on nodes (lines 99, 107 of pocketflow/__init__.py). The DebugWrapper MUST implement `__copy__` or Flow will break when it tries to copy nodes.

3. **Node names are inconsistent**: Only ResultPreparationNode has `self.name`. All others need `node.__class__.__name__`.

4. **The planner creates WorkflowManager singleton**: If not passed in shared, some nodes create their own. Always pass it explicitly.

## Path Detection Logic

The trace collector needs to detect Path A vs Path B:
- **Path A**: No ComponentBrowsingNode executed
- **Path B**: ComponentBrowsingNode executed

This is how we know which path the planner took. See the TraceCollector implementation in the guide.

## Performance Realities

- Progress adds ~5% overhead (we're just printing)
- Each LLM call takes 2-5 seconds typically
- The planner makes 4-7 LLM calls depending on path
- Total execution: 10-30 seconds normally

## What The Implementing Agent Should Verify First

Before diving into implementation:

1. Run `pflow "test"` and watch it hang - understand the problem viscerally
2. Look at `pocketflow/__init__.py:65-73` - understand how Flow calls nodes
3. Check `src/pflow/planning/nodes.py` - see the 9 nodes and their LLM patterns
4. Verify `~/.pflow/` exists on the system

## Integration Points That Matter

1. **CLI entry**: `src/pflow/cli/main.py:520-590` - Where planner gets called
2. **Flow creation**: `src/pflow/planning/flow.py:create_planner_flow()` - The 9 nodes
3. **Node execution**: `pocketflow/__init__.py:_run()` - What we're wrapping

## Why This Task Matters

Without debugging, the planner is unfixable. We can't see:
- Which node hangs (usually WorkflowGeneratorNode)
- What prompt caused the issue
- What the LLM returned (or didn't return)

With debugging, every failure becomes diagnosable. Every prompt becomes improvable.

## Final Critical Warnings

1. **DO NOT try to be clever with threading** - We already verified it's impossible
2. **DO NOT modify the nodes themselves** - Use the wrapper pattern
3. **DO NOT skip the attribute copying** - The planner will break mysteriously
4. **DO NOT use print()** - Always use click.echo(err=True)

## The Most Important Thing

**The DebugWrapper's attribute delegation is make-or-break.** If you get this wrong, the planner will fail with cryptic errors about missing attributes. Test this component in isolation first before integrating.

## Links to Critical Files

- Flow execution model: `pocketflow/__init__.py:18-73`
- All 9 planner nodes: `src/pflow/planning/nodes.py`
- Planner orchestration: `src/pflow/planning/flow.py`
- CLI integration point: `src/pflow/cli/main.py:520-590`
- Working implementation code: `.taskmaster/tasks/task_27/starting-context/main-agent-implementation-guide.md`

## What Success Looks Like

```bash
$ pflow "create a changelog"
🔍 Discovery... ✓ 2.1s
📝 Parameters... ✓ 1.5s
✅ Workflow ready: generate-changelog
```

Clean progress, no clutter. On failure, a trace file with everything needed to debug.

---

**Remember: Read all the context files first. The implementation guide has working code. Don't reinvent the wheel. And most importantly - test the DebugWrapper delegation before anything else.**

**⚠️ When you're done reading this handoff and all context files, just confirm you're ready to begin. Don't start implementing until you've absorbed everything.**