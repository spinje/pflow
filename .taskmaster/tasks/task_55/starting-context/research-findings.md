# Research Findings for Task 55: Fix Output Control for Interactive vs Non-Interactive Execution

## Executive Summary

The research reveals that pflow has partial TTY detection (for save prompts) but lacks unified output control. Progress messages always go to stderr regardless of execution context, breaking Unix composability. The solution requires: (1) unified TTY detection with `-p/--print` override flag, (2) progress callbacks through InstrumentedNodeWrapper, and (3) consistent separation of progress (stderr when interactive) and results (stdout always).

## 1. Current State Analysis

### 1.1 Output Mechanisms

**Current Implementation:**
- **Primary method**: `click.echo()` throughout the codebase
- **Routing pattern**:
  - Status/progress/errors: `click.echo(msg, err=True)` → **stderr**
  - Results: `click.echo(result)` → **stdout**
- **Location**: All output calls in `src/pflow/cli/main.py`

**Key Issues:**
- Progress messages **always** go to stderr, even when piped
- No mechanism to suppress progress for machine consumption
- JSON mode only affects result formatting, not progress suppression

### 1.2 Progress Display System

**Planner Progress** (`src/pflow/planning/debug.py:589-612`):
```python
# Format: "{display_name}... ✓ {duration:.1f}s"
click.echo(f"{display_name}...", err=True, nl=False)  # Start
click.echo(f" ✓ {duration:.1f}s", err=True)          # Complete
```

**Display Names:**
- workflow-discovery, component-browsing, parameter-discovery
- parameter-mapping, generator, ✅ Validation, 💾 Metadata

**Workflow Execution Progress**: **MISSING** - No progress during node execution

### 1.3 TTY Detection

**Existing Pattern** (`src/pflow/cli/main.py:1361`):
```python
if sys.stdin.isatty() and sys.stdout.isatty():
    # Interactive mode - show save prompts
```

**Current Usage:**
- Only used for save workflow prompts
- Not used for progress output control
- Already implements dual-TTY detection (both stdin and stdout)

## 2. Architecture Integration Points

### 2.1 Workflow Execution Flow

**Execution Chain:**
1. CLI (`main.py:811`): `result = flow.run(shared_storage)`
2. PocketFlow (`pocketflow/__init__.py:106`): Sequential node execution
3. Node Wrappers (outermost to innermost):
   - `InstrumentedNodeWrapper` → **BEST HOOK POINT**
   - `NamespacedNodeWrapper`
   - `TemplateAwareNodeWrapper`
   - Actual Node

### 2.2 InstrumentedNodeWrapper as Hook Point

**Why it's ideal:**
- Already wraps every node (planner and workflow)
- Has metrics/tracing infrastructure
- Minimal code changes required
- Supports nested workflows automatically

**Implementation Strategy:**
```python
# In InstrumentedNodeWrapper._run()
progress_callback = shared.get('__progress_callback__')
if progress_callback:
    progress_callback('node_start', self.node_id)

result = self.inner_node._run(shared)

if progress_callback:
    progress_callback('node_complete', self.node_id, duration_ms)
```

### 2.3 CLI Integration

**Flag Addition Location** (`src/pflow/cli/main.py:1756-1770`):
- Add after `--output-format` option
- Use `@click.option("-p", "--print", is_flag=True, help="...")`
- Pass through context object (`ctx.obj`)

**Interactive Detection Function:**
```python
def is_interactive(ctx) -> bool:
    """Determine if running in interactive mode."""
    # Explicit override via -p flag
    if ctx.obj.get('print_flag'):
        return False

    # JSON mode is never interactive
    if ctx.obj.get('output_format') == 'json':
        return False

    # Auto-detect TTY status
    return sys.stdin.isatty() and sys.stdout.isatty()
```

## 3. Testing Infrastructure

### 3.1 Testing Challenges

**CliRunner Limitation** (from `tests/test_cli/CLAUDE.md:49`):
- `CliRunner` always returns False for `isatty()`
- Cannot test interactive behavior directly
- Must use mocking for TTY testing

### 3.2 Testing Strategy

**Mock Pattern:**
```python
with patch("sys.stdin.isatty", return_value=True), \
     patch("sys.stdout.isatty", return_value=True):
    # Test interactive behavior

with patch("sys.stdin.isatty", return_value=False):
    # Test piped behavior
```

**Test Matrix:**
- TTY status: interactive, piped stdin, piped stdout, both piped
- Flags: with/without `-p`, with/without `--output-format json`
- Workflows: single node, multi-node, nested workflows
- Timing: fast nodes (<1s), slow nodes (mocked 15s)

## 4. Best Practices from Research

### 4.1 Unix Philosophy

**Stream Separation:**
- **stdout**: Program results (pipeable data)
- **stderr**: UI elements (progress, prompts, logs)
- **Principle**: Results must be pipeable without contamination

### 4.2 Industry Standards

**Common Patterns:**
- `curl`: Shows progress on stderr in TTY, silent when piped
- `git`: Auto-detects TTY, `--progress` flag for override
- `wget`: Different progress styles for TTY vs non-TTY

**Flag Conventions:**
- `-p/--print`: Common for "output only" mode
- `--progress/--no-progress`: Explicit progress control
- `-q/--quiet`: Suppress all non-essential output

### 4.3 Python TTY Detection

**Reliable Pattern:**
```python
import sys

# More reliable than stream.isatty()
interactive = sys.__stdin__.isatty() and sys.__stdout__.isatty()

# Handle edge cases
if sys.stdin is None or sys.stdout is None:
    interactive = False  # Windows GUI apps
```

## 5. Implementation Plan

### 5.1 Core Components

1. **Output Controller Class**:
   - Centralized TTY detection and flag handling
   - Methods for progress, status, and result output
   - Consistent routing based on mode

2. **Progress Callback System**:
   - Pass callback through shared storage
   - Hook into InstrumentedNodeWrapper
   - Format matching planner style

3. **CLI Flag Integration**:
   - Add `-p/--print` flag
   - Update all output calls to check mode
   - Suppress save prompts in non-interactive

### 5.2 Key Design Decisions

**Decision 1: Progress Callback Mechanism**
- **Choice**: Use shared storage with reserved key `__progress_callback__`
- **Rationale**: Non-invasive, works with existing wrappers, supports nesting

**Decision 2: TTY Detection Logic**
- **Choice**: Dual-TTY check (stdin AND stdout) with flag override
- **Rationale**: Prevents hanging on partial pipes, matches existing pattern

**Decision 3: Output Routing**
- **Interactive**: Progress to stderr, results to stdout
- **Non-interactive**: Only results to stdout
- **Rationale**: Unix composability, industry standard

### 5.3 Risk Mitigation

**Risks Identified:**
1. **Breaking existing scripts**: Mitigate with backwards-compatible defaults
2. **Windows TTY detection**: Provide `-p` flag as escape hatch
3. **Nested workflow progress**: Ensure callbacks propagate correctly
4. **Performance overhead**: Keep callback checks minimal

## 6. Critical Implementation Details

### 6.1 Files to Modify

**Primary Changes:**
1. `src/pflow/cli/main.py`: Add flag, output control logic
2. `src/pflow/runtime/instrumented_wrapper.py`: Add progress callbacks
3. `src/pflow/planning/debug.py`: Respect output mode

**New Files:**
1. `src/pflow/core/output_controller.py`: Centralized output control

### 6.2 Backwards Compatibility

**Preserved Behavior:**
- Default (no flags) remains interactive when in terminal
- Existing scripts using `--output-format json` continue working
- Error messages still go to stderr

**Breaking Changes:**
- None identified - all changes are additive or auto-detected

### 6.3 Edge Cases to Handle

1. **Partial TTY**: stdin TTY but stdout piped (or vice versa)
2. **Nested workflows**: Progress depth/indentation
3. **Fast nodes**: Don't show progress for <100ms operations
4. **Interrupted execution**: Clean progress state on Ctrl+C
5. **Empty workflows**: Handle gracefully

## 7. Success Criteria

**Functional Requirements Met:**
- ✅ Piped output contains only results
- ✅ Interactive mode shows execution progress
- ✅ `-p` flag forces non-interactive mode
- ✅ JSON mode outputs valid JSON only

**Quality Metrics:**
- Zero contamination in piped output
- Progress updates at least every 2 seconds
- No performance degradation (< 1% overhead)
- All tests passing including new TTY tests

## 8. Conclusion

The implementation is straightforward with minimal risk. The codebase already has the necessary infrastructure (TTY detection, output routing, node wrapping). The main work is:

1. Creating a unified output control system
2. Adding progress callbacks to existing instrumentation
3. Ensuring all output respects the interactive mode setting

The solution follows Unix philosophy, matches industry standards, and maintains backwards compatibility while fixing the critical issues that make pflow appear broken in different contexts.