#!/usr/bin/env python3
"""Convert pflow trace JSON files to organized markdown files for prompt analysis."""

import json
import re
import sys
from pathlib import Path


def estimate_tokens(text: str) -> int:
    """Estimate token count for text (rough approximation).

    For accurate counts, we'd need tiktoken, but this gives a reasonable estimate.
    Generally: 1 token ≈ 4 characters or 0.75 words
    """
    if not text:
        return 0

    # Simple estimation: characters / 4
    char_estimate = len(text) / 4

    # Word-based estimate: words * 1.3
    words = len(text.split())
    word_estimate = words * 1.3

    # Return average of both methods
    return int((char_estimate + word_estimate) / 2)


def format_prompt(prompt: str) -> str:
    """Format a prompt for markdown."""
    return prompt


def format_response(response: any) -> str:
    """Format an LLM response for markdown."""
    if isinstance(response, dict):
        # Check if it's a raw LLM response with 'content' field
        if "content" in response and isinstance(response["content"], list):
            # Extract the actual response from the content array
            for item in response["content"]:
                if isinstance(item, dict) and "input" in item:
                    # This is the actual response data
                    return json.dumps(item["input"], indent=2)
        return json.dumps(response, indent=2)
    elif isinstance(response, str):
        try:
            # Try to parse as JSON
            parsed = json.loads(response)
            return json.dumps(parsed, indent=2)
        except (json.JSONDecodeError, ValueError):
            return response
    else:
        return str(response)


def sanitize_filename(name: str) -> str:
    """Sanitize a string to be used as a filename."""
    # Remove or replace invalid characters
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    # Limit length
    if len(name) > 100:
        name = name[:100]
    return name


def create_node_markdown(node_num: int, call: dict, trace_id: str) -> tuple[str, dict]:
    """Create markdown content for a single node/LLM call.

    Returns:
        tuple: (markdown_content, metadata_dict)
    """
    node_name = call.get("node", "Unknown")
    duration = call.get("duration_ms", 0) / 1000

    # Get emoji for node type
    emoji_map = {
        "WorkflowDiscoveryNode": "🔍",
        "ComponentBrowsingNode": "📦",
        "ParameterDiscoveryNode": "🔎",
        "ParameterMappingNode": "📝",
        "WorkflowGeneratorNode": "🤖",
        "ValidatorNode": "✅",
        "MetadataGenerationNode": "💾",
        "ParameterPreparationNode": "📋",
        "ResultPreparationNode": "📤",
    }
    emoji = emoji_map.get(node_name, "📋")

    md = []

    # Header
    md.append(f"# {emoji} {node_name}\n")
    md.append(f"**Call #:** {node_num}  ")
    md.append(f"**Duration:** {duration:.2f}s  ")
    md.append(f"**Trace ID:** `{trace_id}`  \n")

    # Get prompt and response
    prompt = call.get("prompt", "")
    response = call.get("response")

    # Calculate or get token counts
    tokens = call.get("tokens", {})
    if tokens:
        prompt_tokens = tokens.get("input", 0)
        response_tokens = tokens.get("output", 0)
    else:
        # Estimate if not provided
        prompt_tokens = estimate_tokens(prompt)
        response_text = format_response(response) if response else ""
        response_tokens = estimate_tokens(response_text)

    # Token summary box
    md.append("## 📊 Token Usage\n")
    md.append("| Type | Count | Percentage |")
    md.append("|------|-------|------------|")
    total_tokens = prompt_tokens + response_tokens
    if total_tokens > 0:
        prompt_pct = (prompt_tokens / total_tokens) * 100
        response_pct = (response_tokens / total_tokens) * 100
        md.append(f"| **Prompt** | {prompt_tokens:,} | {prompt_pct:.1f}% |")
        md.append(f"| **Response** | {response_tokens:,} | {response_pct:.1f}% |")
        md.append(f"| **Total** | {total_tokens:,} | 100% |")
    else:
        md.append("| **Prompt** | 0 | - |")
        md.append("| **Response** | 0 | - |")
        md.append("| **Total** | 0 | - |")
    md.append("")

    # Cost estimation (optional - based on common model pricing)
    if total_tokens > 0:
        # Rough cost estimates (you can adjust these)
        input_cost_per_1k = 0.003  # $3 per 1M tokens
        output_cost_per_1k = 0.015  # $15 per 1M tokens
        prompt_cost = (prompt_tokens / 1000) * input_cost_per_1k
        response_cost = (response_tokens / 1000) * output_cost_per_1k
        total_cost = prompt_cost + response_cost

        md.append(f"\n**Estimated Cost:** ${total_cost:.6f} ")
        md.append(f"(Prompt: ${prompt_cost:.6f}, Response: ${response_cost:.6f})\n")

    # Prompt section
    if prompt:
        md.append("## 📝 Prompt\n")
        md.append(f"*Length: {len(prompt):,} characters, ~{len(prompt.split()):,} words*\n")
        md.append("```")
        md.append(format_prompt(prompt))
        md.append("```\n")

    # Response section
    if response:
        md.append("## 🤖 Response\n")
        response_text = format_response(response)
        md.append(f"*Length: {len(response_text):,} characters*\n")
        md.append("```json")
        md.append(response_text)
        md.append("```\n")

    # Analysis hints
    md.append("## 💭 Analysis Notes\n")
    md.append("*Add your observations here:*\n")
    md.append("- [ ] Prompt clarity")
    md.append("- [ ] Response accuracy")
    md.append("- [ ] Token efficiency")
    md.append("- [ ] Potential improvements\n")

    # Metadata for index
    metadata = {
        "node": node_name,
        "duration": duration,
        "prompt_tokens": prompt_tokens,
        "response_tokens": response_tokens,
        "total_tokens": total_tokens,
    }

    return "\n".join(md), metadata


def create_index_markdown(trace: dict, node_files: list) -> str:
    """Create an index markdown file that links to all node files."""
    md = []

    # Header
    md.append("# Planner Trace Analysis\n")
    md.append(f"**Trace ID:** `{trace.get('execution_id', 'unknown')}`  ")
    md.append(f"**Timestamp:** {trace.get('timestamp', 'unknown')}  ")
    md.append(f"**Status:** {trace.get('status', 'unknown')}  ")
    md.append(f"**Duration:** {trace.get('duration_ms', 0) / 1000:.1f}s  ")
    md.append(f"**Path:** {trace.get('path_taken', 'unknown')}  \n")

    # User input
    md.append("## 📥 User Request\n")
    md.append("```")
    md.append(trace.get("user_input", ""))
    md.append("```\n")

    # Summary statistics
    total_prompt_tokens = sum(f["metadata"]["prompt_tokens"] for f in node_files)
    total_response_tokens = sum(f["metadata"]["response_tokens"] for f in node_files)
    total_tokens = total_prompt_tokens + total_response_tokens
    total_duration = sum(f["metadata"]["duration"] for f in node_files)

    md.append("## 📊 Summary Statistics\n")
    md.append(f"- **Total LLM Calls:** {len(node_files)}")
    md.append(f"- **Total Duration:** {total_duration:.2f}s")
    md.append(f"- **Total Tokens:** {total_tokens:,}")
    md.append(f"  - Prompt Tokens: {total_prompt_tokens:,}")
    md.append(f"  - Response Tokens: {total_response_tokens:,}")

    if total_tokens > 0:
        # Cost estimation
        input_cost = (total_prompt_tokens / 1000) * 0.003
        output_cost = (total_response_tokens / 1000) * 0.015
        total_cost = input_cost + output_cost
        md.append(f"- **Estimated Total Cost:** ${total_cost:.4f}\n")

    # Node execution flow
    md.append("## 🔄 Execution Flow\n")
    md.append("| # | Node | Duration | Tokens | File |")
    md.append("|---|------|----------|--------|------|")

    for i, file_info in enumerate(node_files, 1):
        meta = file_info["metadata"]
        filename = file_info["filename"]
        node = meta["node"]
        duration = meta["duration"]
        tokens = meta["total_tokens"]

        # Shorten node name for table
        short_node = node.replace("Node", "")

        md.append(f"| {i} | {short_node} | {duration:.2f}s | {tokens:,} | [{filename}](./{filename}) |")

    # Error section if failed
    if trace.get("status") in ["error", "failed"]:
        error = trace.get("error")
        if error:
            md.append("\n## ❌ Error Details\n")
            md.append("```")
            if isinstance(error, dict):
                md.append(error.get("message", "Unknown error"))
            else:
                md.append(str(error))
            md.append("```\n")

    # Final workflow if generated
    final_store = trace.get("final_shared_store", {})
    if final_store.get("generated_workflow"):
        md.append("\n## ✅ Generated Workflow\n")
        md.append("```json")
        workflow_json = json.dumps(final_store["generated_workflow"], indent=2)
        if len(workflow_json) > 3000:
            md.append(workflow_json[:3000])
            md.append("\n... (truncated)")
        else:
            md.append(workflow_json)
        md.append("```\n")

    # Navigation
    md.append("\n## 🗂️ Files\n")
    for file_info in node_files:
        filename = file_info["filename"]
        meta = file_info["metadata"]
        md.append(f"- [{filename}](./{filename}) - {meta['node']} ({meta['total_tokens']:,} tokens)")

    return "\n".join(md)


def analyze_trace(trace_file: Path, output_dir: Path) -> None:
    """Convert a trace file to organized markdown files."""

    # Load trace
    with open(trace_file) as f:
        trace = json.load(f)

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get LLM calls
    llm_calls = trace.get("llm_calls", [])
    if not llm_calls:
        print("⚠️  No LLM calls found in trace")
        return

    # Process each LLM call
    node_files = []
    for i, call in enumerate(llm_calls, 1):
        node_name = call.get("node", "Unknown")

        # Create markdown for this node
        content, metadata = create_node_markdown(i, call, trace.get("execution_id", "unknown"))

        # Generate filename
        safe_node_name = sanitize_filename(node_name)
        filename = f"{i:02d}-{safe_node_name}.md"

        # Write file
        file_path = output_dir / filename
        file_path.write_text(content)

        # Track for index
        node_files.append({"filename": filename, "metadata": metadata})

        print(f"  ✅ Created: {filename}")

    # Create index file
    index_content = create_index_markdown(trace, node_files)
    index_path = output_dir / "README.md"
    index_path.write_text(index_content)
    print("  ✅ Created: README.md (index)")

    print(f"\n📁 Analysis saved to: {output_dir}")
    print(f"   Total files: {len(node_files) + 1}")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python analyze_trace_split.py <trace-file.json> [output-dir]")
        print("\nExample:")
        print("  python analyze_trace_split.py ~/.pflow/debug/pflow-trace-20250815-120310.json")
        print("  python analyze_trace_split.py trace.json my-analysis/")
        sys.exit(1)

    trace_file = Path(sys.argv[1])
    if not trace_file.exists():
        print(f"Error: Trace file not found: {trace_file}")
        sys.exit(1)

    # Determine output directory
    if len(sys.argv) > 2:
        output_dir = Path(sys.argv[2])
    else:
        # Default: scripts/analyze-trace/output/{trace-filename-without-extension}/
        base_name = trace_file.stem  # Remove .json extension
        output_dir = Path("scripts/analyze-trace/output") / base_name

    print(f"📋 Analyzing trace: {trace_file.name}")
    print(f"📁 Output directory: {output_dir}")

    try:
        analyze_trace(trace_file, output_dir)
    except Exception as e:
        print(f"❌ Error analyzing trace: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
