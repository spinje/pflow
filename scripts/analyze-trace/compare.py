#!/usr/bin/env python3
"""Compare two trace files to see what changed in prompts/responses."""

import difflib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO


def load_trace(file_path: Path) -> dict:
    """Load a trace file."""
    with open(file_path) as f:
        return json.load(f)


def compare_prompts(trace1: dict, trace2: dict, output: TextIO) -> None:
    """Compare prompts between two traces."""
    calls1 = trace1.get("llm_calls", [])
    calls2 = trace2.get("llm_calls", [])

    print("\n## 📝 Prompt Differences\n", file=output)

    # Build maps by node name
    prompts1 = {call["node"]: call.get("prompt", "") for call in calls1}
    prompts2 = {call["node"]: call.get("prompt", "") for call in calls2}

    all_nodes = set(prompts1.keys()) | set(prompts2.keys())

    for node in sorted(all_nodes):
        prompt1 = prompts1.get(node, "")
        prompt2 = prompts2.get(node, "")

        if prompt1 != prompt2:
            print(f"### {node}\n", file=output)

            if not prompt1:
                print("❌ Node missing in trace 1\n", file=output)
            elif not prompt2:
                print("❌ Node missing in trace 2\n", file=output)
            else:
                # Show diff
                lines1 = prompt1.splitlines()
                lines2 = prompt2.splitlines()

                diff = difflib.unified_diff(lines1, lines2, fromfile="Trace 1", tofile="Trace 2", lineterm="", n=3)

                diff_lines = list(diff)
                if len(diff_lines) > 50:
                    # Truncate very long diffs
                    print("```diff", file=output)
                    print("\n".join(diff_lines[:50]), file=output)
                    print(f"... ({len(diff_lines) - 50} more lines)", file=output)
                    print("```\n", file=output)
                else:
                    print("```diff", file=output)
                    print("\n".join(diff_lines), file=output)
                    print("```\n", file=output)


def _extract_response_from_call(call: dict) -> tuple[str, Any]:
    """Extract node name and response from an LLM call."""
    node = call["node"]
    response = call.get("response", {})

    if isinstance(response, dict) and "content" in response:
        # Extract structured response
        for item in response.get("content", []):
            if isinstance(item, dict) and "input" in item:
                return node, item["input"]

    return node, response


def _print_response_diff(node: str, resp1: Any, resp2: Any, output: TextIO) -> None:
    """Print the difference between two responses."""
    print(f"### {node}\n", file=output)

    # Format responses for comparison
    str1 = json.dumps(resp1, indent=2) if resp1 else "Missing"
    str2 = json.dumps(resp2, indent=2) if resp2 else "Missing"

    if str1 == str2:
        return

    for trace_num, response_str in [(1, str1), (2, str2)]:
        print(f"**Trace {trace_num}:**", file=output)
        print("```json", file=output)
        if len(response_str) > 500:
            print(response_str[:500] + "\n... (truncated)", file=output)
        else:
            print(response_str, file=output)
        print("```\n", file=output)


def compare_responses(trace1: dict, trace2: dict, output: TextIO) -> None:
    """Compare response patterns between two traces."""
    calls1 = trace1.get("llm_calls", [])
    calls2 = trace2.get("llm_calls", [])

    print("\n## 🤖 Response Differences\n", file=output)

    # Build maps by node name
    responses1 = dict(_extract_response_from_call(call) for call in calls1)
    responses2 = dict(_extract_response_from_call(call) for call in calls2)

    all_nodes = set(responses1.keys()) | set(responses2.keys())

    for node in sorted(all_nodes):
        resp1 = responses1.get(node)
        resp2 = responses2.get(node)

        if resp1 != resp2:
            _print_response_diff(node, resp1, resp2, output)


def compare_metrics(trace1: dict, trace2: dict, output: TextIO) -> None:
    """Compare performance metrics between two traces."""
    print("\n## 📊 Metrics Comparison\n", file=output)

    # Status
    status1 = trace1.get("status", "unknown")
    status2 = trace2.get("status", "unknown")

    print(f"**Status:** {status1} → {status2}", file=output)

    # Duration
    duration1 = trace1.get("duration_ms", 0) / 1000
    duration2 = trace2.get("duration_ms", 0) / 1000
    diff = duration2 - duration1
    sign = "+" if diff > 0 else ""
    print(f"**Duration:** {duration1:.1f}s → {duration2:.1f}s ({sign}{diff:.1f}s)", file=output)

    # Token usage
    calls1 = trace1.get("llm_calls", [])
    calls2 = trace2.get("llm_calls", [])

    tokens1 = sum(call.get("tokens", {}).get("total", 0) for call in calls1)
    tokens2 = sum(call.get("tokens", {}).get("total", 0) for call in calls2)

    if tokens1 or tokens2:
        diff = tokens2 - tokens1
        sign = "+" if diff > 0 else ""
        print(f"**Total Tokens:** {tokens1:,} → {tokens2:,} ({sign}{diff:,})", file=output)

    # Path taken
    path1 = trace1.get("path_taken", "unknown")
    path2 = trace2.get("path_taken", "unknown")

    if path1 != path2:
        print(f"**Path:** {path1} → {path2}", file=output)
    else:
        print(f"**Path:** {path1} (unchanged)", file=output)

    print(file=output)


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: python compare_traces.py <trace1.json> <trace2.json> [output_dir]")
        print("\nExample:")
        print("  python compare_traces.py trace-old.json trace-new.json")
        print("  python compare_traces.py trace-old.json trace-new.json my-output/")
        sys.exit(1)

    file1 = Path(sys.argv[1])
    file2 = Path(sys.argv[2])

    if not file1.exists():
        print(f"Error: File not found: {file1}")
        sys.exit(1)

    if not file2.exists():
        print(f"Error: File not found: {file2}")
        sys.exit(1)

    # Determine output directory
    output_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(__file__).parent / "output"

    output_dir.mkdir(parents=True, exist_ok=True)

    # Extract timestamps from filenames
    # Expected format: planner-trace-YYYYMMDD-HHMMSS.json or workflow-trace-*-YYYYMMDD-HHMMSS.json
    import re

    # Updated pattern to match both planner and workflow traces
    pattern = r"(?:planner|workflow)-trace-(?:.*?-)?(\d{8}-\d{6})\.json"

    match1 = re.search(pattern, file1.name)
    match2 = re.search(pattern, file2.name)

    if match1 and match2:
        timestamp1 = match1.group(1)
        timestamp2 = match2.group(1)
        output_filename = f"comparison-{timestamp1}-vs-{timestamp2}.md"
    else:
        # Fallback to generic timestamp
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_filename = f"comparison-{timestamp}.md"

    output_path = output_dir / output_filename

    # Load traces
    trace1 = load_trace(file1)
    trace2 = load_trace(file2)

    # Write comparison to file
    with open(output_path, "w") as output:
        print("# Trace Comparison\n", file=output)
        print(f"**Trace 1:** {file1.name}", file=output)
        print(f"**Trace 2:** {file2.name}", file=output)

        # Compare different aspects
        compare_metrics(trace1, trace2, output)
        compare_prompts(trace1, trace2, output)
        compare_responses(trace1, trace2, output)

    # Print confirmation to console
    print(f"✅ Comparison saved to: {output_path}")
    print(f"\nFile size: {output_path.stat().st_size:,} bytes")

    # Try to open in editor if available
    import shutil
    import subprocess

    # Try cursor first, then code, then fallback to just showing path
    for editor in ["cursor", "code"]:
        if shutil.which(editor):
            try:
                subprocess.run([editor, str(output_path)], check=False)  # noqa: S603
                print(f"📝 Opened in {editor}")
            except (OSError, subprocess.SubprocessError):
                continue  # Try next editor
            break


if __name__ == "__main__":
    main()
