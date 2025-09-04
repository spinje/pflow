# Feature: fix_output_control

## Objective

Fix output behavior for interactive versus non-interactive execution modes.

## Requirements

- Must detect TTY status using sys.stdin.isatty() and sys.stdout.isatty()
- Must add -p/--print CLI flag for explicit non-interactive mode
- Must add progress callbacks to InstrumentedNodeWrapper
- Must preserve existing planner progress format
- Must route progress to stderr when interactive
- Must suppress all progress when non-interactive

## Scope

- Does not change existing error routing
- Does not modify trace/metrics collection
- Does not alter JSON result structure
- Does not change existing planner progress symbols

## Inputs

- print_flag: bool - CLI flag -p/--print to force non-interactive
- output_format: str - Existing --output-format value (text/json)
- stdin_tty: bool - Result of sys.stdin.isatty()
- stdout_tty: bool - Result of sys.stdout.isatty()
- shared_storage: dict[str, Any] - Shared storage with optional __progress_callback__

## Outputs

Returns: Modified CLI behavior with mode-aware output

Side effects:
- Progress messages to stderr when interactive
- Only results to stdout when non-interactive
- Progress callbacks invoked during node execution

## Structured Formats

```python
class OutputController:
    """Central output control based on execution mode."""

    def __init__(self, print_flag: bool = False,
                 output_format: str = "text",
                 stdin_tty: bool = None,
                 stdout_tty: bool = None):
        self.print_flag = print_flag
        self.output_format = output_format
        self.stdin_tty = stdin_tty if stdin_tty is not None else sys.stdin.isatty()
        self.stdout_tty = stdout_tty if stdout_tty is not None else sys.stdout.isatty()

    def is_interactive(self) -> bool:
        """Determine if running in interactive mode."""
        if self.print_flag:
            return False
        if self.output_format == "json":
            return False
        return self.stdin_tty and self.stdout_tty

    def create_progress_callback(self) -> Optional[Callable]:
        """Create progress callback for workflow execution."""
        if not self.is_interactive():
            return None

        def progress_callback(node_id: str, event: str, duration_ms: Optional[float] = None, depth: int = 0):
            indent = "  " * depth
            if event == "node_start":
                click.echo(f"{indent}  {node_id}...", err=True, nl=False)
            elif event == "node_complete":
                click.echo(f" ✓ {duration_ms/1000:.1f}s", err=True)
            elif event == "workflow_start":
                click.echo(f"{indent}Executing workflow ({node_id} nodes):", err=True)

        return progress_callback

    def result(self, data: str):
        """Output result data to stdout."""
        click.echo(data)

# Callback integration in _prepare_shared_storage()
def _prepare_shared_storage(..., output_controller: Optional[OutputController] = None):
    shared_storage: dict[str, Any] = {}
    # ... existing code ...
    if output_controller:
        callback = output_controller.create_progress_callback()
        if callback:
            shared_storage["__progress_callback__"] = callback
    return shared_storage
```

## State/Flow Changes

- Terminal detected → interactive mode → show progress
- Pipes detected → non-interactive mode → suppress progress
- -p flag provided → non-interactive mode (override TTY)
- JSON format → non-interactive mode (override TTY)

## Constraints

- Progress timing format: "{duration:.1f}s"
- Progress callback key: "__progress_callback__"
- TTY detection: both stdin AND stdout must be TTY for interactive
- Flag precedence: -p > JSON mode > TTY detection

## Rules

1. If print_flag is True then is_interactive returns False
2. If output_format equals "json" then is_interactive returns False
3. If stdin_tty is False then is_interactive returns False
4. If stdout_tty is False then is_interactive returns False
5. If is_interactive is True then progress messages go to stderr
6. If is_interactive is False then suppress all progress messages
7. Result output always goes to stdout
8. Save workflow prompts appear only if is_interactive is True
9. OutputController.create_progress_callback returns callback if interactive else None
10. _prepare_shared_storage adds __progress_callback__ to shared storage if provided
11. InstrumentedNodeWrapper._run calls callback with node_id event and duration_ms
12. Callback extracts depth from shared storage _pflow_depth key
13. Progress format matches planner: "{name}... ✓ {duration:.1f}s"
14. Node execution shows header "Executing workflow ({count} nodes):"
15. Each executing node shows "  {node_id}..." with depth-based indentation

## Edge Cases

- stdin TTY but stdout piped → non-interactive
- stdout TTY but stdin piped → non-interactive
- Empty workflow (0 nodes) → no execution progress shown
- Nested workflows → use _pflow_depth from shared storage for indentation
- Node execution fails → callback continues without error
- __progress_callback__ is not callable → silently skip callbacks
- sys.stdin is None (Windows GUI) → treat as non-TTY
- Progress callback raises exception → catch and continue execution

## Error Handling

- Errors always go to stderr regardless of mode
- Progress callback exceptions → log to stderr but continue execution
- TTY detection fails → default to non-interactive
- Invalid output_format → use text mode

## Non-Functional Criteria

- Zero output contamination in non-interactive mode
- Backwards compatible with existing scripts

## Examples

```bash
# Interactive terminal - shows all progress
$ pflow "analyze data"
workflow-discovery... ✓ 2.1s
generator... ✓ 3.4s
Executing workflow (3 nodes):
  read_file... ✓ 0.1s
  llm... ✓ 8.7s
  write_file... ✓ 0.2s

# Piped output - only result
$ pflow "count files" | wc -l
42

# Force non-interactive in terminal
$ pflow -p "generate report"
Report content here

# JSON mode suppresses progress
$ pflow --output-format json "analyze" | jq .
{
  "result": "analysis"
}
```

## Test Criteria

1. print_flag=True, stdin_tty=True, stdout_tty=True → is_interactive=False
2. output_format="json", stdin_tty=True, stdout_tty=True → is_interactive=False
3. stdin_tty=False, stdout_tty=True → is_interactive=False
4. stdin_tty=True, stdout_tty=False → is_interactive=False
5. is_interactive=True, progress messages → appear in stderr
6. is_interactive=False, progress messages → no output
7. result("data") → "data" appears in stdout always
8. is_interactive=True → save prompt displayed
9. OutputController.create_progress_callback() → returns callback if interactive
10. _prepare_shared_storage with output_controller → adds __progress_callback__
11. InstrumentedNodeWrapper._run() → calls callback with correct parameters
12. shared["_pflow_depth"]=2 → callback uses depth for indentation
13. planner progress → "workflow-discovery... ✓ 2.1s" format preserved
14. execution header → "Executing workflow (3 nodes):" appears
15. node execution → shows "  {node_id}..." with proper indentation
16. stdin piped but stdout TTY → is_interactive=False
17. stdout piped but stdin TTY → is_interactive=False
18. empty workflow → no execution progress shown
19. nested workflow with _pflow_depth=1 → indented by 2 spaces
20. __progress_callback__ not callable → no exception raised
21. sys.stdin is None → is_interactive=False
22. progress callback raises exception → execution continues

## Notes (Why)

- Unix philosophy requires clean stdout for composability
- Users abort silent long-running operations thinking they crashed
- -p flag provides escape hatch for CI/CD environments with broken TTY detection
- Dual TTY check prevents hanging when only one stream is piped
- Progress to stderr allows monitoring while piping results
- Callback through shared storage avoids modifying PocketFlow core

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1                          |
| 2      | 2                          |
| 3      | 3                          |
| 4      | 4, 16, 17                  |
| 5      | 5                          |
| 6      | 6                          |
| 7      | 7                          |
| 8      | 8                          |
| 9      | 9                          |
| 10     | 10                         |
| 11     | 11                         |
| 12     | 12                         |
| 13     | 13                         |
| 14     | 14                         |
| 15     | 15                         |

| Edge Case                        | Covered By Test Criteria # |
| -------------------------------- | -------------------------- |
| stdin TTY but stdout piped      | 16                         |
| stdout TTY but stdin piped      | 17                         |
| Empty workflow                   | 18                         |
| Nested workflows                 | 19                         |
| Node execution fails             | N/A - removed              |
| __progress_callback__ not callable | 20                      |
| sys.stdin is None                | 21                         |
| Progress callback exception      | 22                         |

## Versioning & Evolution

- v1.0.0 - Initial output control implementation
- Future: Consider --quiet flag for suppressing stderr errors
- Future: Add --verbose-progress for detailed node state transitions

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes sys.stdin and sys.stdout are available (may be None in Windows GUI apps)
- Assumes click.echo handles broken pipe errors correctly
- Assumes _pflow_depth key is always present for nested workflows (research confirmed it is)

### Conflicts & Resolutions

- Existing save prompts use dual TTY check but progress doesn't → Resolution: Unify all output control through OutputController
- JSON mode affects result format but not progress → Resolution: JSON mode implies non-interactive
- Some progress to stderr, some to stdout → Resolution: All progress to stderr, all results to stdout

### Decision Log / Tradeoffs

- Chose shared storage callback over modifying PocketFlow core (less invasive, uses existing patterns)
- Chose stderr for progress over separate progress stream (Unix standard)
- Chose -p flag name over --quiet or --no-progress (matches Claude Code precedent)
- Use existing _pflow_depth key over custom depth tracking (infrastructure already exists)
- Hook into InstrumentedNodeWrapper over creating new wrapper (all nodes already use it)

### Ripple Effects / Impact Map

- All click.echo calls in main.py need output controller wrapping
- PlannerProgress class needs to check is_interactive
- InstrumentedNodeWrapper gains callback invocation logic (3 lines of code)
- _prepare_shared_storage gains output_controller parameter
- Tests need TTY mocking infrastructure using patch()
- Documentation needs piping examples

### Residual Risks & Confidence

- Risk: Windows TTY detection may behave unexpectedly; Mitigation: -p flag override; Confidence: High
- Risk: Third-party nodes may output directly; Mitigation: Cannot control; Confidence: Low impact
- Risk: Callback exceptions break execution; Mitigation: try/except wrapper; Confidence: High

### Epistemic Audit (Checklist Answers)

1. Assumptions: TTY detection reliable, click.echo handles pipes, _pflow_depth exists
2. Breakage if wrong: Windows GUI apps fail but -p flag mitigates
3. Robustness over elegance: Chose explicit TTY checks and existing infrastructure
4. Every rule has test: Yes, see compliance matrix
5. Ripple effects: Minimal - hooks into existing wrapper, uses existing depth tracking
6. Uncertainty: Windows behavior only; Confidence: High (research confirmed all implementation details)