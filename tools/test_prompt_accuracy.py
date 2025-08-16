#!/usr/bin/env python3
"""Developer tool for testing and tracking prompt accuracy with version management."""

import hashlib
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml


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


def run_tests(test_path: str) -> tuple[int, int]:  # noqa: C901
    """Run pytest and extract pass/fail counts.

    Returns:
        Tuple of (passed_count, total_count)
    """
    # Set up environment with RUN_LLM_TESTS=1
    env = os.environ.copy()
    env["RUN_LLM_TESTS"] = "1"

    # Run pytest with verbose output to capture results
    cmd = ["pytest", test_path, "-v", "--tb=short"]

    try:
        result = subprocess.run(  # noqa: S603 - safe, we control the test_path
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout for LLM tests
        )

        # Parse output for test results
        output = result.stdout + result.stderr

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


def should_increment_version(prompt_content: str, metadata: dict) -> bool:
    """Check if prompt has changed significantly enough to increment version."""
    current_hash = get_prompt_hash(prompt_content)
    stored_hash = metadata.get("prompt_hash", "")

    if not stored_hash:
        # First time - store hash but don't increment
        metadata["prompt_hash"] = current_hash
        return False

    if current_hash != stored_hash:
        # Prompt has changed - ask user
        print(f"\n📝 Prompt content has changed (hash: {stored_hash} → {current_hash})")
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


def run_prompt_test(prompt_name: str, update: bool = False) -> None:  # noqa: C901
    """Run tests for a prompt and optionally update accuracy metrics."""

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

    # Check for version increment
    if should_increment_version(prompt_content, metadata):
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

    # Run tests
    print(f"\n🧪 Running tests for {prompt_name} prompt (v{metadata.get('version', '1.0')})...")
    print(f"   Test path: {test_path}")
    passed, total = run_tests(test_path)

    if total == 0:
        print("❌ No test results found. Check that tests exist and RUN_LLM_TESTS=1 is set.")
        return

    # Calculate new accuracy
    new_accuracy = round((passed / total * 100), 1) if total > 0 else 0.0

    # Update metrics
    old_latest = metadata.get("latest_accuracy", 0.0)
    old_average = metadata.get("average_accuracy", 0.0)
    old_test_runs = metadata.get("test_runs", [])

    # Calculate new metrics
    new_test_runs = update_test_runs(old_test_runs, new_accuracy)
    new_average = calculate_average(new_test_runs)

    # Display results
    print(f"\n📊 Test Results: {passed}/{total} passed")
    print(f"   Latest accuracy: {new_accuracy}%")
    print(f"   Average accuracy: {new_average}% (from {len(new_test_runs)} runs)")

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

        # Save updated frontmatter
        new_content = format_frontmatter(metadata, prompt_content)
        prompt_file.write_text(new_content)

        print(f"\n✅ Updated {prompt_name}.md:")
        print(f"   Latest: {old_latest}% → {new_accuracy}%")
        print(f"   Average: {old_average}% → {new_average}%")
        if metadata.get("test_count", 0) != total:
            print(f"   Test count: {metadata.get('test_count', 0)} → {total}")
    else:
        print("\n🔍 Dry run - no files updated")
        if new_average != old_average:
            print(f"   Would update average: {old_average}% → {new_average}%")
        if metadata.get("test_count", 0) != total:
            print(f"   Would update test count: {metadata.get('test_count', 0)} → {total}")


def main() -> None:
    """Main entry point for the test runner."""
    if len(sys.argv) < 2:
        print("Usage: uv run python tools/test_prompt_accuracy.py <prompt_name> [--dry-run]")
        print("\nBy default, test results are saved to the prompt file.")
        print("Use --dry-run (or --no-update) to test without updating files.")
        print("\nAvailable prompts:")
        print("  - discovery")
        print("  - component_browsing")
        print("  - parameter_discovery")
        print("  - parameter_mapping")
        print("  - workflow_generator")
        print("  - metadata_generation")
        sys.exit(1)

    prompt_name = sys.argv[1]
    # Default is to update, use --dry-run or --no-update to skip
    update = not ("--dry-run" in sys.argv or "--no-update" in sys.argv)

    run_prompt_test(prompt_name, update)


if __name__ == "__main__":
    main()
