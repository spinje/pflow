#!/usr/bin/env python3
"""Compare two trace files to see what changed in prompts/responses."""

import difflib
import json
import sys
from pathlib import Path
from typing import Any


def load_trace(file_path: Path) -> dict:
    """Load a trace file."""
    with open(file_path) as f:
        return json.load(f)


def compare_prompts(trace1: dict, trace2: dict) -> None:
    """Compare prompts between two traces."""
    calls1 = trace1.get("llm_calls", [])
    calls2 = trace2.get("llm_calls", [])

    print("\n## 📝 Prompt Differences\n")

    # Build maps by node name
    prompts1 = {call["node"]: call.get("prompt", "") for call in calls1}
    prompts2 = {call["node"]: call.get("prompt", "") for call in calls2}

    all_nodes = set(prompts1.keys()) | set(prompts2.keys())

    for node in sorted(all_nodes):
        prompt1 = prompts1.get(node, "")
        prompt2 = prompts2.get(node, "")

        if prompt1 != prompt2:
            print(f"### {node}\n")

            if not prompt1:
                print("❌ Node missing in trace 1\n")
            elif not prompt2:
                print("❌ Node missing in trace 2\n")
            else:
                # Show diff
                lines1 = prompt1.splitlines()
                lines2 = prompt2.splitlines()

                diff = difflib.unified_diff(lines1, lines2, fromfile="Trace 1", tofile="Trace 2", lineterm="", n=3)

                diff_lines = list(diff)
                if len(diff_lines) > 50:
                    # Truncate very long diffs
                    print("```diff")
                    print("\n".join(diff_lines[:50]))
                    print(f"... ({len(diff_lines) - 50} more lines)")
                    print("```\n")
                else:
                    print("```diff")
                    print("\n".join(diff_lines))
                    print("```\n")


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


def _print_response_diff(node: str, resp1: Any, resp2: Any) -> None:
    """Print the difference between two responses."""
    print(f"### {node}\n")

    # Format responses for comparison
    str1 = json.dumps(resp1, indent=2) if resp1 else "Missing"
    str2 = json.dumps(resp2, indent=2) if resp2 else "Missing"

    if str1 == str2:
        return

    for trace_num, response_str in [(1, str1), (2, str2)]:
        print(f"**Trace {trace_num}:**")
        print("```json")
        if len(response_str) > 500:
            print(response_str[:500] + "\n... (truncated)")
        else:
            print(response_str)
        print("```\n")


def compare_responses(trace1: dict, trace2: dict) -> None:
    """Compare response patterns between two traces."""
    calls1 = trace1.get("llm_calls", [])
    calls2 = trace2.get("llm_calls", [])

    print("\n## 🤖 Response Differences\n")

    # Build maps by node name
    responses1 = dict(_extract_response_from_call(call) for call in calls1)
    responses2 = dict(_extract_response_from_call(call) for call in calls2)

    all_nodes = set(responses1.keys()) | set(responses2.keys())

    for node in sorted(all_nodes):
        resp1 = responses1.get(node)
        resp2 = responses2.get(node)

        if resp1 != resp2:
            _print_response_diff(node, resp1, resp2)


def compare_metrics(trace1: dict, trace2: dict) -> None:
    """Compare performance metrics between two traces."""
    print("\n## 📊 Metrics Comparison\n")

    # Status
    status1 = trace1.get("status", "unknown")
    status2 = trace2.get("status", "unknown")

    print(f"**Status:** {status1} → {status2}")

    # Duration
    duration1 = trace1.get("duration_ms", 0) / 1000
    duration2 = trace2.get("duration_ms", 0) / 1000
    diff = duration2 - duration1
    sign = "+" if diff > 0 else ""
    print(f"**Duration:** {duration1:.1f}s → {duration2:.1f}s ({sign}{diff:.1f}s)")

    # Token usage
    calls1 = trace1.get("llm_calls", [])
    calls2 = trace2.get("llm_calls", [])

    tokens1 = sum(call.get("tokens", {}).get("total", 0) for call in calls1)
    tokens2 = sum(call.get("tokens", {}).get("total", 0) for call in calls2)

    if tokens1 or tokens2:
        diff = tokens2 - tokens1
        sign = "+" if diff > 0 else ""
        print(f"**Total Tokens:** {tokens1:,} → {tokens2:,} ({sign}{diff:,})")

    # Path taken
    path1 = trace1.get("path_taken", "unknown")
    path2 = trace2.get("path_taken", "unknown")

    if path1 != path2:
        print(f"**Path:** {path1} → {path2}")
    else:
        print(f"**Path:** {path1} (unchanged)")

    print()


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: python compare_traces.py <trace1.json> <trace2.json>")
        print("\nExample:")
        print("  python compare_traces.py trace-old.json trace-new.json")
        sys.exit(1)

    file1 = Path(sys.argv[1])
    file2 = Path(sys.argv[2])

    if not file1.exists():
        print(f"Error: File not found: {file1}")
        sys.exit(1)

    if not file2.exists():
        print(f"Error: File not found: {file2}")
        sys.exit(1)

    print("# Trace Comparison\n")
    print(f"**Trace 1:** {file1.name}")
    print(f"**Trace 2:** {file2.name}")

    trace1 = load_trace(file1)
    trace2 = load_trace(file2)

    # Compare different aspects
    compare_metrics(trace1, trace2)
    compare_prompts(trace1, trace2)
    compare_responses(trace1, trace2)


if __name__ == "__main__":
    main()
