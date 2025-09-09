#!/usr/bin/env python3
"""Developer tool for testing and tracking prompt accuracy with version management and cost tracking."""

import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

# Try to import llm for token tracking
try:
    import llm

    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False


# Model pricing per million tokens (based on llm-prices.com)
MODEL_PRICING = {
    "anthropic/claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    "anthropic/claude-sonnet-4-0": {"input": 3.00, "output": 15.00},
    "gpt-5-nano": {"input": 0.05, "output": 0.20},  # Test model - ultra cheap
    "gpt-5-mini": {"input": 0.10, "output": 0.40},  # Test model - very cheap
    "gpt-5": {"input": 5.00, "output": 20.00},  # Test model - premium pricing
}


class TokenTracker:
    """Tracks token usage across LLM calls."""

    def __init__(self):
        self.total_input = 0
        self.total_output = 0
        self.model_name = None
        self.call_count = 0

    def add_usage(self, usage: Any, model_name: str) -> None:
        """Add token usage from a response."""
        if usage:
            # Handle Usage dataclass from llm library
            if hasattr(usage, "input") and hasattr(usage, "output"):
                self.total_input += usage.input or 0
                self.total_output += usage.output or 0
                self.model_name = model_name
                self.call_count += 1
            # Handle dict format (fallback)
            elif isinstance(usage, dict):
                self.total_input += usage.get("input", 0) or usage.get("input_tokens", 0)
                self.total_output += usage.get("output", 0) or usage.get("output_tokens", 0)
                self.model_name = model_name
                self.call_count += 1

    def calculate_cost(self) -> float:
        """Calculate total cost based on token usage and model."""
        if not self.model_name or (self.total_input == 0 and self.total_output == 0):
            return 0.0

        # Get pricing for the model, default to Sonnet if unknown
        pricing = MODEL_PRICING.get(self.model_name, MODEL_PRICING["anthropic/claude-sonnet-4-0"])

        # Pricing is per million tokens
        input_cost = (self.total_input / 1_000_000) * pricing["input"]
        output_cost = (self.total_output / 1_000_000) * pricing["output"]

        return round(input_cost + output_cost, 6)  # 6 decimal places for precision


@dataclass
class TestResult:
    """Represents a single test result."""

    name: str
    status: str  # PASSED, FAILED, SKIPPED
    worker: Optional[str] = None  # gw0, gw1, etc.
    progress: Optional[int] = None  # Percentage complete
    failure_reason: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.status == "PASSED"

    @property
    def failed(self) -> bool:
        return self.status == "FAILED"


class TestResultParser:
    """Parse pytest output in real-time and extract test results."""

    # Pattern for test result: [gw0] [ 33%] PASSED .../test_discovery_scenario[test_name]
    TEST_RESULT_PATTERN = re.compile(r"\[gw(\d+)\]\s+\[\s*(\d+)%\]\s+(PASSED|FAILED|SKIPPED)\s+.+\[(.+?)\]")

    # Pattern for inline failure reason output by our test
    # Format: FAIL_REASON|test_name|reason
    # This can appear in print output or logging output (INFO level)
    INLINE_FAILURE_PATTERN = re.compile(r"FAIL_REASON\|([^|]+)\|(.+)")

    # Pattern for failure section header with test name (--tb=short format)
    # Example: ________ TestDiscoveryPrompt.test_discovery_scenario[no_match] _________
    FAILURE_HEADER_PATTERN = re.compile(r"_+ .+test_discovery_scenario\[(.+?)\] _+")

    # Pattern for failure detail with --tb=short format
    # Example: E   AssertionError: [test_name] reason
    FAILURE_DETAIL_PATTERN = re.compile(r"^E\s+AssertionError: \[(.+?)\] (.+)")

    def __init__(self):
        self.results: Dict[str, TestResult] = {}
        self.current_failure_test = None  # Track which test's failure we're parsing
        self.in_failure_section = False
        self.total_tests = 0
        self.completed_tests = 0

    def parse_line(self, line: str) -> Optional[TestResult]:
        """Parse a single line and return result if test completed.

        Returns TestResult if a test just completed, None otherwise.
        """
        # First check for inline failure reason (can appear before or after test result)
        inline_match = self.INLINE_FAILURE_PATTERN.search(line)
        if inline_match:
            test_name, failure_reason = inline_match.groups()
            # Store the failure reason
            if test_name in self.results:
                # Test result already seen, update it
                self.results[test_name].failure_reason = failure_reason
            # Return a special marker to indicate we have a failure reason
            return TestResult(name=test_name, status="FAILURE_INFO", failure_reason=failure_reason)

        # Check for test result
        match = self.TEST_RESULT_PATTERN.search(line)
        if match:
            worker, progress, status, test_name = match.groups()
            result = TestResult(name=test_name, status=status, worker=f"gw{worker}", progress=int(progress))
            self.results[test_name] = result
            self.completed_tests += 1

            # Update total tests estimate from progress
            if self.completed_tests == 1 and result.progress:
                # First test gives us total count estimate
                self.total_tests = int(100 / result.progress)

            return result

        # Check for failure details section
        if "FAILURES" in line and "=" in line:
            self.in_failure_section = True
            return None

        # Parse failure details from FAILURES section (--tb=short format)
        if self.in_failure_section:
            # Check for failure header with test name
            header_match = self.FAILURE_HEADER_PATTERN.search(line)
            if header_match:
                # Extract test name from the failure header
                self.current_failure_test = header_match.group(1)
                return None

            # Check for failure reason with our custom format
            failure_match = self.FAILURE_DETAIL_PATTERN.search(line)
            if failure_match:
                test_name, reason = failure_match.groups()
                # Associate the failure reason with the correct test
                if test_name in self.results:
                    self.results[test_name].failure_reason = reason
                    # Return a marker that we found a failure reason
                    return TestResult(name=test_name, status="FAILURE_UPDATE", failure_reason=reason)

        return None

    def get_summary(self) -> tuple[int, int]:
        """Get test summary (passed, total)."""
        passed = sum(1 for r in self.results.values() if r.passed)
        total = len(self.results)
        return passed, total


class TestResultDisplay:
    """Handle real-time display of test results."""

    def __init__(self, total_tests: Optional[int] = None):
        self.total_tests = total_tests
        self.completed = 0
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def show_header(self, prompt_name: str, version: str):
        """Display test run header."""
        print(f"\n🧪 Running tests for {prompt_name} prompt (v{version})...")
        if self.total_tests:
            print(f"   {self.total_tests} tests with parallel execution")
        print()  # Empty line for cleaner output

    def show_result(self, result: TestResult):
        """Display a single test result as it completes."""
        self.completed += 1

        # Update counters
        if result.passed:
            symbol = "✅"
            self.passed += 1
        elif result.failed:
            symbol = "❌"
            self.failed += 1
        else:  # SKIPPED
            symbol = "⏭️"
            self.skipped += 1

        # Format progress indicator
        if self.total_tests:
            progress = f"[{self.completed}/{self.total_tests}]"
        elif result.progress:
            progress = f"[{result.progress}%]"
        else:
            progress = f"[{self.completed}]"

        # Display result
        print(f"{symbol} {progress:<8} {result.name}")

        # Display failure reason if available (indented)
        if result.failure_reason:
            # Show full error message without truncation
            reason = result.failure_reason
            print(f"         → {reason}")

    def show_summary(self, passed: int, total: int, duration: float = None):
        """Display final summary."""
        percentage = (passed / total * 100) if total > 0 else 0

        print(f"\n{'=' * 60}")
        print(f"📊 Final Results: {passed}/{total} passed ({percentage:.1f}%)")

        if self.failed > 0:
            print(f"   ✅ Passed: {self.passed}")
            print(f"   ❌ Failed: {self.failed}")
            if self.skipped > 0:
                print(f"   ⏭️ Skipped: {self.skipped}")

        if duration:
            print(f"   ⏱️ Duration: {duration:.1f}s")
        print(f"{'=' * 60}")


def install_llm_interceptor(tracker: TokenTracker, override_model: Optional[str] = None) -> Optional[Any]:
    """Install monkey-patch to intercept LLM calls and capture token usage.

    Args:
        tracker: TokenTracker to record usage
        override_model: Optional model to use instead of requested model

    Returns:
        Original get_model function to restore later, or None if LLM not available
    """
    if not LLM_AVAILABLE:
        return None

    original_get_model = llm.get_model

    def wrapped_get_model(model_name: str):
        """Wrapped get_model that captures token usage and optionally redirects model."""
        # Redirect to override model if specified
        actual_model = override_model if override_model else model_name
        model = original_get_model(actual_model)
        original_prompt = model.prompt

        def wrapped_prompt(*args, **kwargs):
            """Wrapped prompt method that captures response usage."""
            response = original_prompt(*args, **kwargs)

            # Wrap response methods to capture usage on access
            if response:
                original_json = response.json if hasattr(response, "json") else None
                original_text = response.text if hasattr(response, "text") else None
                captured = [False]  # Use list for mutability in closure

                def capture_usage():
                    """Capture token usage from response."""
                    if not captured[0] and hasattr(response, "usage") and callable(response.usage):
                        try:
                            usage = response.usage()
                            tracker.add_usage(usage, actual_model)  # Track the actual model used
                            captured[0] = True
                        except Exception:
                            pass  # Ignore errors in usage capture

                def wrapped_json():
                    """Wrapped json method."""
                    result = original_json() if original_json else {}
                    capture_usage()
                    return result

                def wrapped_text():
                    """Wrapped text method."""
                    result = original_text() if original_text else ""
                    capture_usage()
                    return result

                if original_json:
                    response.json = wrapped_json
                if original_text:
                    response.text = wrapped_text

            return response

        model.prompt = wrapped_prompt
        return model

    llm.get_model = wrapped_get_model
    return original_get_model


def restore_llm(original_get_model: Optional[Any]) -> None:
    """Restore original LLM get_model function."""
    if LLM_AVAILABLE and original_get_model:
        llm.get_model = original_get_model


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content.

    Returns:
        Tuple of (metadata dict, prompt content without frontmatter)
    """
    if content.startswith("---\n"):
        try:
            # Split on the closing --- delimiter
            parts = content.split("\n---\n", 1)
            if len(parts) == 2:
                metadata = yaml.safe_load(parts[0][4:])  # Skip opening ---
                prompt_content = parts[1]
                return metadata or {}, prompt_content
        except yaml.YAMLError:
            pass

    # No frontmatter or parse error - return empty metadata
    return {}, content


def format_frontmatter(metadata: dict, prompt_content: str) -> str:
    """Format metadata and prompt content back into markdown with frontmatter."""
    # Use standard yaml.dump
    yaml_str = yaml.dump(metadata, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # Manually fix test_runs formatting to be on one line
    lines = yaml_str.split("\n")
    new_lines = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("test_runs:"):
            # Check if it's followed by a list
            if i + 1 < len(lines) and lines[i + 1].startswith("- "):
                # Collect all list items
                test_runs = []
                j = i + 1
                while j < len(lines) and lines[j].startswith("- "):
                    test_runs.append(lines[j][2:].strip())
                    j += 1
                # Format as single line
                new_lines.append(f"test_runs: [{', '.join(test_runs)}]")
                i = j
            else:
                new_lines.append(lines[i])
                i += 1
        else:
            new_lines.append(lines[i])
            i += 1

    yaml_str = "\n".join(new_lines)
    return f"---\n{yaml_str}---\n{prompt_content}"


def get_prompt_hash(content: str) -> str:
    """Get hash of prompt content (excluding frontmatter) for version detection."""
    # Remove whitespace variations for consistent hashing
    normalized = "\n".join(line.strip() for line in content.split("\n") if line.strip())
    return hashlib.md5(normalized.encode(), usedforsecurity=False).hexdigest()[:8]


def run_tests(
    test_path: str,
    model: Optional[str] = None,
    tracker: Optional[TokenTracker] = None,
    parallel_workers: Optional[int] = None,
    show_live: bool = True,
    prompt_name: Optional[str] = None,
    version: Optional[str] = None,
) -> tuple[int, int]:
    """Run pytest and extract pass/fail counts.

    Args:
        test_path: Path to the test file
        model: Optional model name to use for testing
        tracker: Optional TokenTracker for capturing usage
        parallel_workers: Number of parallel workers (None = auto-detect based on test count)
        show_live: Whether to show real-time test results
        prompt_name: Name of the prompt being tested (for display)
        version: Version of the prompt (for display)

    Returns:
        Tuple of (passed_count, total_count)
    """
    # Set up environment with RUN_LLM_TESTS=1
    env = os.environ.copy()
    env["RUN_LLM_TESTS"] = "1"

    # Add model override if specified
    if model:
        env["PFLOW_TEST_MODEL"] = model

    # Ensure parallel_workers has a value (will be auto-detected from metadata if None)
    if parallel_workers is None:
        parallel_workers = 10  # Default fallback - will be overridden in run_prompt_test

    # Set parallel workers environment variable
    env["PARALLEL_WORKERS"] = str(parallel_workers)

    # Set up token tracking via temp file if tracker provided
    # For parallel execution, we need a directory to collect all worker files
    tracker_dir = None
    tracker_file = None
    if tracker:
        import tempfile

        # Create a temp directory for token tracking files
        tracker_dir = tempfile.mkdtemp(prefix="token_tracker_")
        # Use a base filename - workers will append their worker id
        tracker_file = os.path.join(tracker_dir, "tokens.json")
        env["PFLOW_TOKEN_TRACKER_FILE"] = tracker_file

    # Enable unbuffered output for real-time display
    env["PYTHONUNBUFFERED"] = "1"

    # Create a temp file for failure reporting (bypasses pytest output capture)
    failure_file = None
    failure_file_handle = None
    if show_live:
        import tempfile

        fd, failure_file = tempfile.mkstemp(suffix=".jsonl", prefix="test_failures_")
        os.close(fd)  # Close the file descriptor
        env["PFLOW_TEST_FAILURE_FILE"] = failure_file
        # Open for reading
        failure_file_handle = open(failure_file)

    # Run pytest with verbose output to capture results
    # Use --tb=short for better failure matching with test names
    # Use --log-cli-level=INFO to get logging output even with pytest-xdist
    cmd = ["pytest", test_path, "-v", "--tb=short", "--log-cli-level=INFO"]

    # Add parallel execution if requested (requires pytest-xdist)
    if parallel_workers and parallel_workers > 1:
        # Check if pytest-xdist is available
        try:
            import xdist  # noqa: F401

            cmd.extend(["-n", str(parallel_workers)])
            if not show_live:
                print(f"   Running with {parallel_workers} parallel workers (pytest-xdist)")
        except ImportError:
            # Parallel execution is required for LLM tests to avoid timeouts
            print(f"\n❌ ERROR: pytest-xdist is required for parallel execution")
            print(f"   The test suite would take 2+ minutes without parallelization.")
            print(f"   Install it with: uv pip install pytest-xdist")
            print(f"\n   Or add to pyproject.toml:")
            print(f"   [dependency-groups]")
            print(f"   dev = [")
            print(f"       ...,")
            print(f"       \"pytest-xdist>=3.0.0\",")
            print(f"   ]")
            raise SystemExit(1)

    # Initialize parser and display if showing live results
    parser = TestResultParser() if show_live else None
    # Try to get total tests from parallel workers (approximate)
    estimated_tests = parallel_workers if parallel_workers and parallel_workers <= 30 else None
    display = TestResultDisplay(total_tests=estimated_tests) if show_live else None
    output_buffer = []

    try:
        # Use different approaches for live vs non-live display
        if show_live:
            # Show header
            if display and prompt_name:
                display.show_header(prompt_name, version or "1.0")

            # Use Popen for streaming output
            import time

            start_time = time.time()

            process = subprocess.Popen(  # noqa: S603 - safe, we control the test_path
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # Line buffered
                universal_newlines=True,
            )

            # Read output line by line
            pending_failures = {}  # Store failure reasons that arrive before test results
            displayed_failures = set()  # Track which failures we've shown
            last_progress_time = time.time()  # Track when we last saw progress
            warned_about_slow = False  # Only warn once about slow execution

            # Function to check for new failures in the file
            def check_failure_file():
                if failure_file_handle:
                    while True:
                        line = failure_file_handle.readline()
                        if not line:
                            break
                        try:
                            import json

                            failure_data = json.loads(line.strip())
                            test_name = failure_data.get("test")
                            failure_reason = failure_data.get("reason")
                            if test_name and failure_reason and test_name not in displayed_failures:
                                pending_failures[test_name] = failure_reason
                        except:
                            pass

            for line in process.stdout:
                output_buffer.append(line)

                # Check for new failures in the file
                check_failure_file()

                # Check for timeout - warn if no progress for 30 seconds
                current_time = time.time()
                if not warned_about_slow and (current_time - last_progress_time) > 30:
                    if parser and len(parser.results) == 0:
                        print(f"\n⚠️  WARNING: No test results after 30 seconds!")
                        print(f"   This usually means pytest-xdist isn't working properly.")
                        print(f"   Tests might be running serially (2+ minutes) instead of parallel (10-20 seconds).")
                        print(f"   Consider stopping with Ctrl+C and checking pytest-xdist installation.")
                        warned_about_slow = True

                # Parse and display results in real-time
                if parser:
                    result = parser.parse_line(line)
                    if result:
                        last_progress_time = current_time  # Reset timeout on progress
                        if result.status == "FAILURE_INFO":
                            # We got a failure reason from stdout/logging (backup)
                            test_name = result.name
                            failure_reason = result.failure_reason

                            if test_name not in displayed_failures:
                                pending_failures[test_name] = failure_reason

                        elif result.status == "FAILURE_UPDATE":
                            # Failure reason from FAILURES section (backup)
                            if result.name not in pending_failures and result.name not in displayed_failures:
                                pending_failures[result.name] = result.failure_reason

                        elif display:
                            # Normal test result - display it
                            display.show_result(result)

                            # If this test has a pending failure reason, show it immediately
                            if result.name in pending_failures:
                                reason = pending_failures[result.name]
                                print(f"         └─ {reason}")
                                displayed_failures.add(result.name)
                                del pending_failures[result.name]

            # Wait for process to complete
            process.wait()
            duration = time.time() - start_time

            # Final check for any remaining failures in the file
            check_failure_file()

            # Display any remaining failures that didn't get matched to test results
            # This can happen if failures are written after the test result is displayed
            if pending_failures and parser:
                for test_name, reason in pending_failures.items():
                    if test_name in parser.results and parser.results[test_name].failed:
                        if test_name not in displayed_failures:
                            # Show as a separate line since the test result is already displayed
                            print(f"         └─ {test_name}: {reason}")
                            displayed_failures.add(test_name)

            # Show summary if live display
            if display and parser:
                passed, total = parser.get_summary()
                display.show_summary(passed, total, duration)

                # Warn if execution was suspiciously slow
                if total > 5 and duration > 60:
                    print(f"\n⚠️  Tests took {duration:.1f} seconds - this is unusually slow!")
                    print(f"   Expected: 10-20 seconds with parallel execution")
                    print(f"   This suggests pytest-xdist may not be working correctly.")

            # Create result object for compatibility
            class Result:
                def __init__(self, stdout, stderr, returncode):
                    self.stdout = stdout
                    self.stderr = stderr
                    self.returncode = returncode

            result = Result("".join(output_buffer), "", process.returncode)

        else:
            # Use original subprocess.run for non-live mode
            result = subprocess.run(  # noqa: S603 - safe, we control the test_path
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout for LLM tests
            )

        # Read back token tracking data if available
        if tracker and tracker_dir:
            try:
                import glob
                import json

                # Look for all token files from parallel workers
                token_files = glob.glob(os.path.join(tracker_dir, "tokens*.json"))

                for token_file in token_files:
                    try:
                        with open(token_file) as f:
                            tracker_data = json.load(f)
                            tracker.total_input += tracker_data.get("total_input", 0)
                            tracker.total_output += tracker_data.get("total_output", 0)
                            tracker.call_count += tracker_data.get("call_count", 0)
                            if not tracker.model_name:
                                tracker.model_name = tracker_data.get("model_name")
                    except:
                        pass  # Ignore errors reading individual files

                # Also check for single file (non-parallel execution)
                if os.path.exists(tracker_file):
                    try:
                        with open(tracker_file) as f:
                            tracker_data = json.load(f)
                            tracker.total_input += tracker_data.get("total_input", 0)
                            tracker.total_output += tracker_data.get("total_output", 0)
                            tracker.call_count += tracker_data.get("call_count", 0)
                            if not tracker.model_name:
                                tracker.model_name = tracker_data.get("model_name")
                    except:
                        pass
            except:
                pass  # Ignore errors reading tracker data

        # Parse output for test results
        output = result.stdout + result.stderr

        # If we used live display, get results from parser
        if show_live and parser:
            passed, total = parser.get_summary()
            if total > 0:
                return passed, total

        # Otherwise, parse from output as before
        # First try to parse the summary line which is most reliable
        # Look for patterns like "2 failed, 1 passed" or "3 passed" or "5 passed, 1 skipped"
        summary_match = re.search(
            r"=+.*?(\d+)\s+(failed|passed|skipped)(?:,\s*(\d+)\s+(failed|passed|skipped))?(?:,\s*(\d+)\s+(failed|passed|skipped))?",
            output,
        )

        if summary_match:
            # Parse the summary line
            passed = 0
            failed = 0
            skipped = 0

            groups = summary_match.groups()
            for i in range(0, len(groups), 2):
                if groups[i] and groups[i + 1]:
                    count = int(groups[i])
                    status = groups[i + 1]
                    if status == "passed":
                        passed = count
                    elif status == "failed":
                        failed = count
                    elif status == "skipped":
                        skipped = count

            # If all tests were skipped, RUN_LLM_TESTS is not working
            if skipped > 0 and passed == 0 and failed == 0:
                print(f"⚠️  All {skipped} tests were SKIPPED - check RUN_LLM_TESTS environment variable")
                return 0, 0

            total = passed + failed
            return passed, total

        # Fallback: count individual test results (avoiding duplicates in summary section)
        # Only count lines that start with test names to avoid the summary section
        passed = len(re.findall(r"^tests/.*test_\w+.*\sPASSED", output, re.MULTILINE))
        failed = len(re.findall(r"^tests/.*test_\w+.*\sFAILED", output, re.MULTILINE))
        skipped = len(re.findall(r"^tests/.*test_\w+.*\sSKIPPED", output, re.MULTILINE))

        if skipped > 0 and passed == 0 and failed == 0:
            print(f"⚠️  All {skipped} tests were SKIPPED - check RUN_LLM_TESTS environment variable")
            return 0, 0

        total = passed + failed
        return passed, total

    except subprocess.TimeoutExpired:
        print("❌ Tests timed out after 5 minutes")
        return 0, 0
    except Exception as e:
        print(f"❌ Error running tests: {e}")
        return 0, 0
    finally:
        # Clean up tracker directory
        if tracker_dir and os.path.exists(tracker_dir):
            import shutil

            try:
                shutil.rmtree(tracker_dir)
            except:
                pass  # Ignore errors cleaning up

        # Clean up failure file
        if failure_file_handle:
            try:
                failure_file_handle.close()
            except:
                pass
        if failure_file and os.path.exists(failure_file):
            try:
                os.remove(failure_file)
            except:
                pass


def update_test_runs(test_runs: list, new_accuracy: float, max_runs: int = 10) -> list:
    """Update test runs array with new accuracy, keeping max_runs entries."""
    test_runs = test_runs.copy() if test_runs else []
    test_runs.append(round(new_accuracy, 1))

    # Keep only the last max_runs entries
    if len(test_runs) > max_runs:
        test_runs = test_runs[-max_runs:]

    return test_runs


def calculate_average(test_runs: list) -> float:
    """Calculate average accuracy from test runs."""
    if not test_runs:
        return 0.0
    return float(round(sum(test_runs) / len(test_runs), 1))


def should_increment_version(prompt_content: str, metadata: dict, dry_run: bool = False) -> bool:
    """Check if prompt has changed significantly enough to increment version.

    Args:
        prompt_content: The current prompt content
        metadata: The metadata dictionary
        dry_run: If True, don't ask user - just return False
    """
    current_hash = get_prompt_hash(prompt_content)
    stored_hash = metadata.get("prompt_hash", "")

    if not stored_hash:
        # First time - store hash but don't increment
        metadata["prompt_hash"] = current_hash
        return False

    if current_hash != stored_hash:
        # Prompt has changed
        print(f"\n📝 Prompt content has changed (hash: {stored_hash} → {current_hash})")

        if dry_run:
            # In dry-run mode, don't increment version or reset tracking
            print("   (Skipping version increment in dry-run mode)")
            return False

        # Ask user only if not in dry-run
        response = input("Increment version and reset accuracy tracking? [y/N]: ").strip().lower()
        return response == "y"

    return False


def handle_version_increment(metadata: dict, prompt_content: str) -> dict:
    """Handle version increment when prompt changes significantly."""
    # Store current average as previous version's accuracy
    current_avg = metadata.get("average_accuracy", 0.0)
    if current_avg > 0:
        metadata["previous_version_accuracy"] = current_avg

    # Increment version
    current_version = metadata.get("version", "1.0")
    try:
        major, minor = map(int, current_version.split("."))
        metadata["version"] = f"{major}.{minor + 1}"
    except (ValueError, AttributeError):
        metadata["version"] = "1.1"

    # Reset test runs for new version
    metadata["test_runs"] = []
    metadata["average_accuracy"] = 0.0
    metadata["latest_accuracy"] = 0.0

    # Update hash
    metadata["prompt_hash"] = get_prompt_hash(prompt_content)

    print(f"✨ Version incremented to {metadata['version']}")
    return metadata


def run_prompt_test(
    prompt_name: str, update: bool = False, model: Optional[str] = None, parallel_workers: Optional[int] = None
) -> None:
    """Run tests for a prompt and optionally update accuracy metrics.

    Args:
        prompt_name: Name of the prompt to test
        update: Whether to update the frontmatter with results (False for dry-run)
        model: Optional model name to use for testing
        parallel_workers: Optional number of parallel workers for tests that support it
    """

    # Load prompt file from src/pflow/planning/prompts/
    prompt_file = Path(__file__).parent.parent / "src" / "pflow" / "planning" / "prompts" / f"{prompt_name}.md"
    if not prompt_file.exists():
        print(f"❌ Prompt file not found: {prompt_file}")
        sys.exit(1)

    content = prompt_file.read_text()
    metadata, prompt_content = parse_frontmatter(content)

    # Initialize metadata if missing
    if not metadata:
        print(f"⚠️  No frontmatter found in {prompt_name}.md - initializing...")
        test_path = f"tests/test_planning/llm/prompts/test_{prompt_name}_prompt.py"
        metadata = {
            "name": prompt_name,
            "test_path": test_path,
            "test_command": f"uv run python tools/test_prompt_accuracy.py {prompt_name}",
            "version": "1.0",
            "latest_accuracy": 0.0,
            "test_runs": [],
            "average_accuracy": 0.0,
            "test_count": 0,
            "previous_version_accuracy": 0.0,
            "last_tested": str(date.today()),
            "prompt_hash": get_prompt_hash(prompt_content),
        }

    # Add test_command if missing (for backward compatibility)
    if "test_command" not in metadata:
        metadata["test_command"] = f"uv run python tools/test_prompt_accuracy.py {prompt_name}"

    # Add test_count if missing (for backward compatibility)
    if "test_count" not in metadata:
        metadata["test_count"] = 0

    # Check for version increment (pass dry_run flag which is the inverse of update)
    dry_run = not update
    if should_increment_version(prompt_content, metadata, dry_run=dry_run):
        metadata = handle_version_increment(metadata, prompt_content)
        if update:
            # Save version increment immediately
            new_content = format_frontmatter(metadata, prompt_content)
            prompt_file.write_text(new_content)
            print(f"✅ Version increment saved to {prompt_name}.md")

    # Get test path
    test_path = metadata.get("test_path", "")
    if not test_path:
        print(f"❌ No test_path defined in frontmatter for {prompt_name}.md")
        sys.exit(1)

    # Set up token tracking
    tracker = TokenTracker() if LLM_AVAILABLE else None

    # Auto-detect optimal parallel workers if not specified
    if parallel_workers is None:
        test_count = metadata.get("test_count", 0)
        if test_count > 0:
            # Use as many workers as tests, capped at 20 for rate limiting
            parallel_workers = min(test_count, 20)
        else:
            # Fallback: try to count tests dynamically
            try:
                result = subprocess.run(
                    ["pytest", test_path, "--collect-only", "-q"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                match = re.search(r"(\d+) (?:tests?|items?) collected", result.stdout) or re.search(
                    r"collected (\d+) items?", result.stdout
                )
                if match:
                    parallel_workers = min(int(match.group(1)), 20)
                else:
                    parallel_workers = 10  # Default fallback
            except Exception:
                parallel_workers = 10  # Default fallback

    # Run tests with live display
    passed, total = run_tests(
        test_path,
        model=model,
        tracker=tracker,
        parallel_workers=parallel_workers,
        show_live=True,
        prompt_name=prompt_name,
        version=metadata.get("version", "1.0"),
    )

    if total == 0:
        print("❌ No test results found. Check that tests exist and RUN_LLM_TESTS=1 is set.")
        return

    # Calculate new accuracy
    new_accuracy = round((passed / total * 100), 1) if total > 0 else 0.0

    # Calculate cost if tracking available
    test_cost = 0.0
    if tracker and tracker.call_count > 0:
        test_cost = tracker.calculate_cost()

    # Update metrics
    old_latest = metadata.get("latest_accuracy", 0.0)
    old_average = metadata.get("average_accuracy", 0.0)
    old_test_runs = metadata.get("test_runs", [])
    old_cost = metadata.get("last_test_cost", 0.0)

    # Calculate new metrics
    new_test_runs = update_test_runs(old_test_runs, new_accuracy)
    new_average = calculate_average(new_test_runs)

    # Display results
    print(f"\n📊 Test Results: {passed}/{total} passed")
    print(f"   Latest accuracy: {new_accuracy}%")
    print(f"   Average accuracy: {new_average}% (from {len(new_test_runs)} runs)")

    # Display cost information if available
    if tracker and tracker.call_count > 0:
        print(f"   💰 Cost: ${test_cost:.4f} ({tracker.total_input:,} input + {tracker.total_output:,} output tokens)")
        if tracker.model_name:
            print(f"   Model used: {tracker.model_name}")
    elif test_cost == 0.0 and LLM_AVAILABLE:
        print("   💰 Cost: $0.0000 (no LLM calls captured)")

    # Compare to previous version
    prev_version_acc = metadata.get("previous_version_accuracy", 0.0)
    if prev_version_acc > 0:
        diff = new_average - prev_version_acc
        if diff > 0:
            print(f"   📈 Current version is {diff:.1f}% better than previous!")
        elif diff < 0:
            print(f"   📉 Current version is {abs(diff):.1f}% worse than previous")
        else:
            print("   ➡️  Same as previous version")

    # Update and save unless --dry-run
    if update:
        metadata["latest_accuracy"] = new_accuracy
        metadata["test_runs"] = new_test_runs
        metadata["average_accuracy"] = new_average
        metadata["test_count"] = total  # Always update test count
        metadata["last_tested"] = str(date.today())

        # Add cost information
        if test_cost > 0:
            metadata["last_test_cost"] = test_cost

        # Track which model was used if specified
        if model:
            metadata["test_model"] = model
        elif "test_model" in metadata and not model:
            # Clear test_model if no specific model was used
            del metadata["test_model"]

        # Save updated frontmatter
        new_content = format_frontmatter(metadata, prompt_content)
        prompt_file.write_text(new_content)

        print(f"\n✅ Updated {prompt_name}.md:")
        print(f"   Latest: {old_latest}% → {new_accuracy}%")
        print(f"   Average: {old_average}% → {new_average}%")
        if old_cost != test_cost and test_cost > 0:
            print(f"   Cost: ${old_cost:.4f} → ${test_cost:.4f}")
        elif test_cost > 0:
            print(f"   Cost: ${test_cost:.4f}")
        if metadata.get("test_count", 0) != total:
            print(f"   Test count: {metadata.get('test_count', 0)} → {total}")
    else:
        print("\n🔍 Dry run - no files updated")
        if new_average != old_average:
            print(f"   Would update average: {old_average}% → {new_average}%")
        if old_cost != test_cost and test_cost > 0:
            print(f"   Would update cost: ${old_cost:.4f} → ${test_cost:.4f}")
        elif test_cost > 0 and old_cost == 0:
            print(f"   Would add cost: ${test_cost:.4f}")
        if metadata.get("test_count", 0) != total:
            print(f"   Would update test count: {metadata.get('test_count', 0)} → {total}")


def main() -> None:
    """Main entry point for the test runner."""
    if len(sys.argv) < 2 or sys.argv[1] in ["--help", "-h"]:
        print(
            "Usage: uv run python tools/test_prompt_accuracy.py <prompt_name> [--dry-run] [--model MODEL] [--parallel N]"
        )
        print("\nBy default, test results are saved to the prompt file.")
        print("\nOptions:")
        print("  --dry-run, --no-update  Test without updating files")
        print("  --model MODEL           Use specific model for testing")
        print("                          e.g., --model gpt-5-nano (ultra-cheap)")
        print("  --parallel N            Number of parallel workers (default: auto-detect)")
        print("                          Auto-detects from test count (max 20)")
        print("                          Tests run ~10x faster with parallelization")
        print("\nAvailable prompts:")
        print("  - discovery")
        print("  - component_browsing")
        print("  - parameter_discovery")
        print("  - parameter_mapping")
        print("  - workflow_generator")
        print("  - metadata_generation")
        print("\nExamples:")
        print("  # Test with default model and parallelization (fastest)")
        print("  uv run python tools/test_prompt_accuracy.py discovery")
        print("\n  # Test with ultra-cheap model for minimum cost")
        print("  uv run python tools/test_prompt_accuracy.py discovery --model gpt-5-nano")
        print("\n  # Test with more parallel workers for even faster execution")
        print("  uv run python tools/test_prompt_accuracy.py discovery --parallel 20")
        print("\n  # Dry run without saving")
        print("  uv run python tools/test_prompt_accuracy.py discovery --dry-run")
        sys.exit(1 if len(sys.argv) < 2 else 0)

    prompt_name = sys.argv[1]

    # Parse arguments
    update = not ("--dry-run" in sys.argv or "--no-update" in sys.argv)

    # Parse model argument
    model = None
    if "--model" in sys.argv:
        model_idx = sys.argv.index("--model")
        if model_idx + 1 < len(sys.argv):
            model = sys.argv[model_idx + 1]
        else:
            print("❌ --model requires a model name")
            sys.exit(1)

    # Parse parallel workers argument
    parallel_workers = None  # Auto-detect by default
    if "--parallel" in sys.argv:
        parallel_idx = sys.argv.index("--parallel")
        if parallel_idx + 1 < len(sys.argv):
            try:
                parallel_workers = int(sys.argv[parallel_idx + 1])
                if parallel_workers < 1:
                    print("❌ --parallel requires a positive number")
                    sys.exit(1)
                if parallel_workers > 20:
                    print("⚠️  Limiting parallel workers to 20 (maximum)")
                    parallel_workers = 20
            except ValueError:
                print("❌ --parallel requires a number")
                sys.exit(1)
        else:
            print("❌ --parallel requires a number")
            sys.exit(1)

    run_prompt_test(prompt_name, update, model, parallel_workers)


if __name__ == "__main__":
    main()
