# Real-time Test Result Display Specification

## Executive Summary

Implement real-time display of test results as they complete during prompt accuracy testing, showing meaningful failure information immediately rather than waiting for all tests to complete.

## Problem Statement

Currently when running `uv run python tools/test_prompt_accuracy.py discovery`:
- User waits ~10 seconds with no feedback
- Only sees aggregate results at the end (11/19 passed)
- No information about which specific tests failed or why
- Must dig into pytest output manually to understand failures

## Goals

1. **Real-time feedback**: Show test results as they complete
2. **Meaningful failures**: Display why each test failed
3. **Progress indication**: Show completion progress during execution
4. **Preserve functionality**: Maintain token tracking and parallel execution
5. **Clean output**: Organized, readable display

## Technical Analysis

### Current pytest Output Format

With pytest-xdist parallel execution (`-n 19`), output looks like:
```
[gw0] [ 5%] PASSED tests/.../test_discovery_scenario[exact_match]
[gw3] [10%] FAILED tests/.../test_discovery_scenario[no_match]
[gw1] [15%] PASSED tests/.../test_discovery_scenario[semantic_match]
...
```

Failure details appear later in the output:
```
=================================== FAILURES ===================================
____________ TestDiscoveryPrompt.test_discovery_scenario[no_match] _____________
[gw3] darwin -- Python 3.13.4 /Users/.../python
tests/.../test_discovery_prompt_parametrized.py:383: in test_discovery_scenario
    pytest.fail(f"Test failed: {'; '.join(errors)}")
E   Failed: Test failed: Confidence: expected 0.0-0.4, got 1.00
```

### Key Patterns to Parse

1. **Test result line**: `[gw\d+] \[\s*\d+%\] (PASSED|FAILED|SKIPPED) .+\[(.+)\]`
   - Worker ID: `gw0`, `gw1`, etc.
   - Progress: `5%`, `10%`, etc.
   - Status: `PASSED`, `FAILED`, `SKIPPED`
   - Test name: In brackets `[exact_match]`

2. **Failure reason**: `E   Failed: Test failed: (.+)`
   - Appears after test name in failure section
   - Contains the actual error message

3. **Summary line**: `=+ (\d+) failed, (\d+) passed.+`
   - Final summary at the end

## Proposed Architecture

### Approach: Streaming Parser with State Machine

```python
class TestResultParser:
    """Parse pytest output in real-time and extract results."""

    def __init__(self):
        self.results = []
        self.current_test = None
        self.parsing_failures = False
        self.failure_buffer = []

    def parse_line(self, line: str) -> Optional[TestResult]:
        """Parse a single line and return result if test completed."""

        # State 1: Test execution
        if match := self.TEST_RESULT_PATTERN.match(line):
            worker, progress, status, test_name = match.groups()
            if status in ['PASSED', 'FAILED']:
                return TestResult(
                    name=test_name,
                    status=status,
                    progress=progress,
                    worker=worker
                )

        # State 2: Failure details section
        elif "FAILURES" in line:
            self.parsing_failures = True

        # State 3: Capturing failure reason
        elif self.parsing_failures:
            if match := self.TEST_NAME_PATTERN.match(line):
                self.current_test = match.group(1)
            elif self.current_test and "Failed:" in line:
                reason = self.extract_failure_reason(line)
                self.attach_reason_to_test(self.current_test, reason)
```

### Display Strategy

#### Option A: Inline Results (Recommended)
```
🧪 Running 19 tests for discovery prompt...

✅ [5%] exact_match
❌ [10%] no_match → Confidence: expected 0.0-0.4, got 1.00
✅ [15%] semantic_match
❌ [20%] different_function → Decision: expected not_found, got found_existing
⏳ [25%] Running...
```

#### Option B: Table Format
```
┌─────────────────────┬────────┬──────────────────────────────────┐
│ Test Name           │ Status │ Failure Reason                   │
├─────────────────────┼────────┼──────────────────────────────────┤
│ exact_match         │ ✅     │                                  │
│ no_match            │ ❌     │ Confidence: expected 0.0-0.4... │
│ semantic_match      │ ✅     │                                  │
└─────────────────────┴────────┴──────────────────────────────────┘
```

#### Option C: Progress Bar with Details
```
[████████░░░░░░░░░░] 8/19 (42%)

Recent results:
  ✅ exact_match
  ❌ no_match - Confidence issue
  ✅ semantic_match
```

**Recommendation**: Option A - Clean, simple, shows progress naturally

### Implementation Plan

#### Phase 1: Subprocess Streaming

Replace current `subprocess.run()` with streaming approach:

```python
def run_tests_streaming(test_path, env, parallel_workers):
    cmd = ["pytest", test_path, "-v", "--tb=short", "-n", str(parallel_workers)]

    process = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # Combine streams
        text=True,
        bufsize=1,  # Line buffering
        universal_newlines=True
    )

    parser = TestResultParser()
    display = TestResultDisplay()

    for line in process.stdout:
        if result := parser.parse_line(line):
            display.show_result(result)

    process.wait()
    return parser.get_summary()
```

#### Phase 2: Failure Capture

Since failure details appear after the test result, we need a two-pass approach:

1. **First pass**: Capture immediate results (PASSED/FAILED status)
2. **Buffer failures**: Store failed test names
3. **Second pass**: When we see failure details, update the stored results
4. **Display updates**: Option to update display with failure reason

```python
class TestResult:
    def __init__(self, name, status, progress=None):
        self.name = name
        self.status = status
        self.progress = progress
        self.failure_reason = None

    def update_failure(self, reason):
        self.failure_reason = reason
```

#### Phase 3: Display Management

Handle terminal output cleanly:

```python
class TestResultDisplay:
    def __init__(self):
        self.test_count = 0
        self.passed = 0
        self.failed = 0

    def show_result(self, result: TestResult):
        """Display a single test result."""
        if result.status == 'PASSED':
            symbol = '✅'
            self.passed += 1
        else:
            symbol = '❌'
            self.failed += 1

        self.test_count += 1
        progress = f"[{self.test_count}/19]"

        print(f"{symbol} {progress} {result.name}")

        if result.failure_reason:
            # Indent failure reason
            print(f"     → {result.failure_reason[:60]}...")
```

### Integration Points

#### 1. Token Tracking
- Keep existing temp directory approach
- Aggregate tokens after process completes
- No changes needed to token tracking logic

#### 2. Result Counting
- Count from parser results instead of regex on full output
- More accurate than current approach
- Can track skipped tests separately

#### 3. Error Handling
- Timeout handling remains the same
- Process termination on Ctrl+C
- Cleanup in finally block

### Challenges & Solutions

#### Challenge 1: Buffered Output
**Problem**: Python/pytest may buffer output, delaying real-time display
**Solution**:
- Use `PYTHONUNBUFFERED=1` environment variable
- Add `-u` flag to pytest
- Use `bufsize=1` for line buffering

#### Challenge 2: Interleaved Worker Output
**Problem**: With parallel execution, output from different workers interleaves
**Solution**:
- Track by worker ID (`gw0`, `gw1`, etc.)
- Sort/group results for display
- Show completed tests immediately

#### Challenge 3: Failure Details Appear Later
**Problem**: Failure reasons appear in a separate section after all tests run
**Solution**:
- Two-phase parsing approach
- Option 1: Buffer all output and process twice
- Option 2: Update display when failure details arrive (might be confusing)
- Option 3: Run with `--tb=line` for inline failures (simpler!)

**Recommendation**: Use `--tb=line` for immediate failure info:
```
test_discovery_scenario[no_match] FAILED - Failed: Test failed: Confidence: expected 0.0-0.4, got 1.00
```

### Code Structure

```
tools/test_prompt_accuracy.py
├── run_tests()  # Current function - keep for backward compatibility
├── run_tests_streaming()  # New streaming version
├── TestResultParser  # Parse pytest output
├── TestResult  # Data class for results
└── TestResultDisplay  # Handle terminal display
```

### Testing Strategy

1. **Unit tests** for parser with sample pytest output
2. **Integration test** with small test subset
3. **Failure scenarios**:
   - Timeout handling
   - Ctrl+C interruption
   - Parse errors
   - Missing failure details

### Rollout Plan

1. **Phase 1**: Implement basic streaming (show PASSED/FAILED)
2. **Phase 2**: Add failure reason extraction
3. **Phase 3**: Polish display (colors, progress bar)
4. **Phase 4**: Add --verbose flag for detailed output

### Success Metrics

- Tests complete in same time (~10 seconds)
- All 19 test results displayed
- Failure reasons shown for failed tests
- Token tracking still accurate
- No regression in functionality

## Final Recommendation

Implement streaming parser with `--tb=line` for immediate failure information. This is the simplest approach that provides immediate feedback without complex buffering logic.

Key implementation points:
1. Use `subprocess.Popen` with line buffering
2. Parse output with regex patterns
3. Display results immediately as they arrive
4. Use `--tb=line` for inline failure reasons
5. Maintain backward compatibility

This will transform the user experience from:
```
[10 second wait]
📊 Test Results: 11/19 passed
```

To:
```
🧪 Running 19 tests for discovery prompt...

✅ [1/19] exact_match
❌ [2/19] no_match → Confidence: expected 0.0-0.4, got 1.00
✅ [3/19] semantic_match
[... real-time updates ...]

📊 Final Results: 11/19 passed (57.9%)
```