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


def format_response(response: any) -> tuple[str, bool]:
    """Format an LLM response for markdown.

    Returns:
        tuple: (formatted_response, is_json)
    """
    if isinstance(response, dict):
        # Check if it's an Anthropic message format with text content
        if "content" in response and isinstance(response["content"], list):
            # Look for text field (used by PlanningNode and other text responses)
            for item in response["content"]:
                if isinstance(item, dict):
                    if "text" in item:
                        # This is a text response (e.g., from PlanningNode)
                        return item["text"], False
                    elif "input" in item:
                        # This is structured data
                        return json.dumps(item["input"], indent=2), True
        # Regular structured response
        return json.dumps(response, indent=2), True
    elif isinstance(response, str):
        try:
            # Try to parse as JSON
            parsed = json.loads(response)
            return json.dumps(parsed, indent=2), True
        except (json.JSONDecodeError, ValueError):
            return response, False
    else:
        return str(response), False


def sanitize_filename(name: str) -> str:
    """Sanitize a string to be used as a filename."""
    # Remove or replace invalid characters
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    # Limit length
    if len(name) > 100:
        name = name[:100]
    return name


def _get_node_emoji(node_name: str) -> str:
    """Get emoji for node type."""
    emoji_map = {
        "WorkflowDiscoveryNode": "🔍",
        "ComponentBrowsingNode": "📦",
        "ParameterDiscoveryNode": "🔎",
        "RequirementsAnalysisNode": "📐",
        "PlanningNode": "🗺️",
        "ParameterMappingNode": "📝",
        "WorkflowGeneratorNode": "🤖",
        "ValidatorNode": "✅",
        "MetadataGenerationNode": "💾",
        "ParameterPreparationNode": "📋",
        "ResultPreparationNode": "📤",
    }
    return emoji_map.get(node_name, "📋")


def _calculate_token_counts(call: dict) -> tuple[int, int, int, int, int, int, int]:
    """Calculate or extract token counts from call.

    Returns:
        tuple: (prompt_tokens, response_tokens, cache_creation, cache_read, thinking_tokens, thinking_budget, total_tokens)
    """
    tokens = call.get("tokens", {})

    # Get cache tokens if available
    cache_creation = tokens.get("cache_creation", 0)
    cache_read = tokens.get("cache_read", 0)

    # Get thinking tokens if available
    thinking_tokens = tokens.get("thinking", 0)
    thinking_budget = tokens.get("thinking_budget", 0)

    if tokens:
        prompt_tokens = tokens.get("input", 0)
        response_tokens = tokens.get("output", 0)
    else:
        # Estimate if not provided
        prompt = call.get("prompt", "")
        prompt_tokens = estimate_tokens(prompt)
        response = call.get("response")
        response_text, _ = format_response(response) if response else ("", False)
        response_tokens = estimate_tokens(response_text)

    # Total should include ALL tokens processed by the API including thinking
    total_tokens = tokens.get("total", prompt_tokens + cache_creation + cache_read + response_tokens + thinking_tokens)

    return prompt_tokens, response_tokens, cache_creation, cache_read, thinking_tokens, thinking_budget, total_tokens


def _format_token_usage_table(
    prompt_tokens: int,
    response_tokens: int,
    cache_creation: int,
    cache_read: int,
    thinking_tokens: int,
    thinking_budget: int,
    total_tokens: int,
) -> list[str]:
    """Format token usage as a markdown table."""
    md = []
    md.append("## 📊 Token Usage\n")
    md.append("| Type | Count | Cost Factor | Notes |")
    md.append("|------|-------|-------------|-------|")

    # Display token breakdown
    if cache_creation > 0:
        md.append(f"| **Cache Creation** | {cache_creation:,} | +100% | New cache blocks created (2x cost) |")
    if cache_read > 0:
        md.append(f"| **Cache Read** | {cache_read:,} | -90% | Reused from cache |")
    if thinking_budget > 0 or thinking_tokens > 0:
        efficiency = f" ({thinking_tokens:,}/{thinking_budget:,} used)" if thinking_budget > 0 else ""
        md.append(f"| **Thinking** | {thinking_tokens:,} | 100% | Reasoning tokens{efficiency} |")
    md.append(f"| **Input (non-cached)** | {prompt_tokens:,} | 100% | Regular input tokens |")
    md.append(f"| **Output** | {response_tokens:,} | 100% | Generated tokens |")
    md.append(f"| **Total** | {total_tokens:,} | - | All tokens processed |")
    md.append("")

    # Cache efficiency if applicable
    if cache_read > 0:
        total_input = prompt_tokens + cache_creation + cache_read
        cache_efficiency = (cache_read / total_input * 100) if total_input > 0 else 0
        md.append(f"**Cache Efficiency:** {cache_efficiency:.1f}% of input was reused from cache\n")

    # Thinking efficiency if applicable
    if thinking_budget > 0 and thinking_tokens > 0:
        thinking_efficiency = thinking_tokens / thinking_budget * 100
        md.append(f"**Thinking Utilization:** {thinking_efficiency:.1f}% of allocated thinking budget used\n")

    return md


def _format_cost_from_trace(call: dict) -> list[str]:
    """Format pre-calculated cost information from trace data."""
    md = []

    # Get pre-calculated cost from trace
    if "cost" not in call:
        md.append("\n**💰 Cost:** Not available (old trace format)\n")
        return md

    cost_data = call["cost"]
    total_cost = cost_data.get("total_cost_usd", 0)

    md.append(f"\n**💰 Cost:** ${total_cost:.6f}\n")

    # Calculate cache savings if cache was used
    cache_read_cost = cost_data.get("cache_read_cost", 0)
    cache_creation_cost = cost_data.get("cache_creation_cost", 0)

    if cache_read_cost > 0:
        # Cache reads save 90% compared to regular input
        # So actual cost is 10% of what it would have been
        full_price = cache_read_cost / 0.1  # What it would have cost at full price
        savings = full_price - cache_read_cost

        # Calculate savings percentage of total cost without savings
        total_without_savings = total_cost + savings
        savings_percentage = (savings / total_without_savings * 100) if total_without_savings > 0 else 0

        md.append(f"**💚 Cache Savings:** ${savings:.6f} ({savings_percentage:.1f}% cost reduction)\n")

    # Show cost breakdown if we have detailed costs
    has_special_costs = any([cache_creation_cost > 0, cache_read_cost > 0, cost_data.get("thinking_cost", 0) > 0])

    if has_special_costs:
        md.append("*Cost breakdown:*\n")
        if cache_creation_cost > 0:
            md.append(f"- Cache Creation: ${cache_creation_cost:.6f} (+100% premium)\n")
        if cache_read_cost > 0:
            md.append(f"- Cache Read: ${cache_read_cost:.6f} (-90% discount)\n")
        if cost_data.get("thinking_cost", 0) > 0:
            md.append(f"- Thinking: ${cost_data['thinking_cost']:.6f}\n")
        md.append(f"- Regular Input: ${cost_data.get('input_cost', 0):.6f}\n")
        md.append(f"- Output: ${cost_data.get('output_cost', 0):.6f}\n")
    else:
        # Simple breakdown
        input_cost = cost_data.get("input_cost", 0)
        output_cost = cost_data.get("output_cost", 0)
        md.append(f"(Input: ${input_cost:.6f}, Output: ${output_cost:.6f})\n")

    # Add pricing model info
    if "pricing_model" in cost_data:
        md.append(f"*Pricing: {cost_data['pricing_model']}*\n")

    return md


def _format_cache_blocks(call: dict) -> list[str]:
    """Format cache blocks section."""
    md = []
    prompt_kwargs = call.get("prompt_kwargs", {})
    cache_blocks = prompt_kwargs.get("cache_blocks", [])

    if not cache_blocks:
        return md

    md.append("## 🔒 Cache Blocks (System Context)\n")
    md.append("*These blocks are sent FIRST to the LLM as system context, enabling efficient caching*\n")

    for i, block in enumerate(cache_blocks, 1):
        block_text = block.get("text", "")
        cache_control = block.get("cache_control", {})
        block_tokens = estimate_tokens(block_text)

        md.append(f"### Cache Block {i}")

        # Show cache control type
        if cache_control:
            cache_type = cache_control.get("type", "none")
            md.append(f"**Cache Type:** `{cache_type}` | **Estimated Tokens:** {block_tokens:,}\n")
        else:
            md.append(f"**Cache Type:** `none` (not cached) | **Estimated Tokens:** {block_tokens:,}\n")

        # Show full content in expandable section (removed unused preview variable)
        md.append("<details>")
        md.append("<summary>Preview (click to expand)</summary>\n")
        md.append("```")
        md.append(block_text)
        md.append("```")
        md.append("</details>\n")

    return md


def _format_prompt_and_response(call: dict, prompt_tokens: int, response_tokens: int) -> list[str]:
    """Format prompt and response sections."""
    md = []

    # Prompt section
    prompt = call.get("prompt", "")
    if prompt:
        md.append("## 📝 User Prompt\n")
        md.append("*This is sent AFTER the cache blocks as the user message*\n")
        md.append(f"*{prompt_tokens:,} tokens (non-cached)*\n")
        md.append("```")
        md.append(format_prompt(prompt))
        md.append("```\n")

    # Response section
    response = call.get("response")
    if response:
        md.append("## 🤖 Response\n")
        response_text, is_json = format_response(response)
        md.append(f"*{response_tokens:,} tokens*\n")
        if is_json:
            md.append("```json")
        else:
            md.append("```markdown")
        md.append(response_text)
        md.append("```\n")

    return md


def create_node_markdown(node_num: int, call: dict, trace_id: str) -> tuple[str, dict]:
    """Create markdown content for a single node/LLM call.

    Returns:
        tuple: (markdown_content, metadata_dict)
    """
    node_name = call.get("node", "Unknown")
    duration = call.get("duration_ms", 0) / 1000
    emoji = _get_node_emoji(node_name)

    md = []

    # Header
    md.append(f"# {emoji} {node_name}\n")
    md.append(f"**Call #:** {node_num}  ")
    md.append(f"**Duration:** {duration:.2f}s  ")

    # Add model information if available
    model = call.get("model", "")
    if model and model != "unknown":
        md.append(f"**Model:** `{model}`  ")

    md.append(f"**Trace ID:** `{trace_id}`  \n")

    # Calculate token counts
    prompt_tokens, response_tokens, cache_creation, cache_read, thinking_tokens, thinking_budget, total_tokens = (
        _calculate_token_counts(call)
    )

    # Add token usage table
    md.extend(
        _format_token_usage_table(
            prompt_tokens, response_tokens, cache_creation, cache_read, thinking_tokens, thinking_budget, total_tokens
        )
    )

    # Add cost information from trace
    md.extend(_format_cost_from_trace(call))

    # Add cache blocks section
    md.extend(_format_cache_blocks(call))

    # Add prompt and response sections
    md.extend(_format_prompt_and_response(call, prompt_tokens, response_tokens))

    # Analysis hints
    md.append("## 💭 Analysis Notes\n")
    md.append("*Add your observations here:*\n")
    md.append("- [ ] Prompt clarity")
    md.append("- [ ] Response accuracy")
    md.append("- [ ] Token efficiency")
    md.append("- [ ] Potential improvements\n")

    # Metadata for index (include cache and thinking information)
    metadata = {
        "node": node_name,
        "duration": duration,
        "prompt_tokens": prompt_tokens,
        "response_tokens": response_tokens,
        "total_tokens": total_tokens,
        "cache_creation": cache_creation,
        "cache_read": cache_read,
        "thinking_tokens": thinking_tokens,
        "thinking_budget": thinking_budget,
    }

    # Add cost data if available
    if "cost" in call:
        metadata["cost"] = call["cost"]

    return "\n".join(md), metadata


def _get_trace_title(trace: dict) -> str:
    """Get the appropriate title for the trace based on its type."""
    if "llm_calls" in trace:
        return "# Planner Trace Analysis\n"
    elif "workflow_name" in trace:
        return f"# Workflow Trace Analysis: {trace.get('workflow_name', 'Unknown')}\n"
    else:
        return "# Trace Analysis\n"


def _add_header_metadata(md: list, trace: dict, trace_file: Path) -> None:
    """Add header metadata to the markdown."""
    md.append(f"**Source File:** `{trace_file.name}`  ")
    md.append(f"**Trace ID:** `{trace.get('execution_id', 'unknown')}`  ")

    # Handle timestamp differences
    timestamp = trace.get("timestamp") or trace.get("start_time", "unknown")
    md.append(f"**Timestamp:** {timestamp}  ")

    # Handle status field differences (planner uses 'status', workflow uses 'final_status')
    status = trace.get("status") or trace.get("final_status", "unknown")
    md.append(f"**Status:** {status}  ")

    md.append(f"**Duration:** {trace.get('duration_ms', 0) / 1000:.1f}s  ")

    # Path taken is only in planner traces
    if "path_taken" in trace:
        md.append(f"**Path:** {trace.get('path_taken', 'unknown')}  ")
    md.append("\n")


def _get_user_input(trace: dict) -> str:
    """Extract user input from the trace, handling different formats."""
    user_input = trace.get("user_input", "")  # Planner trace format
    if not user_input and "nodes" in trace:
        # For workflow traces, we might not have the original user input
        user_input = "N/A (Workflow execution trace)"
    return user_input


def _calculate_token_totals(node_files: list) -> dict:
    """Calculate all token totals from node files."""
    return {
        "prompt": sum(f["metadata"]["prompt_tokens"] for f in node_files),
        "response": sum(f["metadata"]["response_tokens"] for f in node_files),
        "cache_creation": sum(f["metadata"].get("cache_creation", 0) for f in node_files),
        "cache_read": sum(f["metadata"].get("cache_read", 0) for f in node_files),
        "thinking": sum(f["metadata"].get("thinking_tokens", 0) for f in node_files),
        "thinking_budget": sum(f["metadata"].get("thinking_budget", 0) for f in node_files),
        "total": sum(f["metadata"]["total_tokens"] for f in node_files),
        "duration": sum(f["metadata"]["duration"] for f in node_files),
    }


def _add_cache_performance_metrics(md: list, node_files: list, totals: dict) -> None:
    """Add cache performance metrics to the summary."""
    if totals["cache_creation"] == 0 and totals["cache_read"] == 0:
        return

    md.append("\n### 🔒 Cache Performance")

    # Nodes using cache
    nodes_with_cache_creation = sum(1 for f in node_files if f["metadata"].get("cache_creation", 0) > 0)
    nodes_with_cache_read = sum(1 for f in node_files if f["metadata"].get("cache_read", 0) > 0)

    md.append(f"- **Nodes Creating Cache:** {nodes_with_cache_creation}/{len(node_files)}")
    md.append(f"- **Nodes Reading Cache:** {nodes_with_cache_read}/{len(node_files)}")

    # Overall cache efficiency
    total_input = totals["prompt"] + totals["cache_creation"] + totals["cache_read"]
    if total_input > 0:
        cache_efficiency = totals["cache_read"] / total_input * 100
        md.append(f"- **Overall Cache Efficiency:** {cache_efficiency:.1f}% of input reused from cache")


def _add_thinking_performance_metrics(md: list, node_files: list, totals: dict) -> None:
    """Add thinking performance metrics to the summary."""
    if totals["thinking_budget"] == 0:
        return

    md.append("\n### 🧠 Thinking Performance")

    # Nodes using thinking
    nodes_with_thinking = sum(1 for f in node_files if f["metadata"].get("thinking_tokens", 0) > 0)

    md.append(f"- **Nodes Using Thinking:** {nodes_with_thinking}/{len(node_files)}")
    md.append(f"- **Total Budget Allocated:** {totals['thinking_budget']:,} tokens")
    md.append(f"- **Total Thinking Used:** {totals['thinking']:,} tokens")

    if totals["thinking"] > 0:
        utilization = totals["thinking"] / totals["thinking_budget"] * 100
        md.append(f"- **Budget Utilization:** {utilization:.1f}%")


def _add_cost_analysis(md: list, totals: dict, node_files: list) -> None:
    """Add cost analysis to the summary using pre-calculated costs from trace."""
    if totals["total"] == 0:
        return

    # Sum up pre-calculated costs from trace
    total_cost = 0.0
    total_cache_savings = 0.0
    has_cost_data = False
    cost_breakdown = {
        "input": 0.0,
        "output": 0.0,
        "cache_creation": 0.0,
        "cache_read": 0.0,
        "thinking": 0.0,
    }

    for file_info in node_files:
        metadata = file_info.get("metadata", {})
        if "cost" in metadata:
            has_cost_data = True
            cost_data = metadata["cost"]
            total_cost += cost_data.get("total_cost_usd", 0)

            # Accumulate breakdown
            cost_breakdown["input"] += cost_data.get("input_cost", 0)
            cost_breakdown["output"] += cost_data.get("output_cost", 0)
            cost_breakdown["cache_creation"] += cost_data.get("cache_creation_cost", 0)
            cost_breakdown["cache_read"] += cost_data.get("cache_read_cost", 0)
            cost_breakdown["thinking"] += cost_data.get("thinking_cost", 0)

            # Calculate savings from cache reads
            if cost_data.get("cache_read_cost", 0) > 0:
                # Cache reads are 10% of regular price, so savings = 90% of what it would have been
                full_price = cost_data["cache_read_cost"] / 0.1
                total_cache_savings += full_price - cost_data["cache_read_cost"]

    # Only show cost analysis if we have cost data
    if not has_cost_data:
        md.append("\n### 💰 Cost Analysis")
        md.append("*Cost data not available (trace generated before cost tracking was added)*")
        return

    md.append("\n### 💰 Cost Analysis")
    md.append(f"- **Total Cost:** ${total_cost:.4f}")

    # Show cache savings if applicable
    if total_cache_savings > 0:
        without_cache_cost = total_cost + total_cache_savings
        savings_percentage = (total_cache_savings / without_cache_cost * 100) if without_cache_cost > 0 else 0

        md.append(f"- **Cost Without Cache:** ${without_cache_cost:.4f}")
        md.append(f"- **💚 Cache Savings:** ${total_cache_savings:.4f} ({savings_percentage:.1f}% reduction)")

    # Cost breakdown
    md.append("\n*Cost Breakdown:*")
    if cost_breakdown["cache_creation"] > 0:
        md.append(f"  - Cache Creation: ${cost_breakdown['cache_creation']:.4f} (+100% premium)")
    if cost_breakdown["cache_read"] > 0:
        md.append(f"  - Cache Read: ${cost_breakdown['cache_read']:.4f} (-90% discount)")
    if cost_breakdown["thinking"] > 0:
        utilization = (totals["thinking"] / totals["thinking_budget"] * 100) if totals["thinking_budget"] > 0 else 0
        md.append(f"  - Thinking: ${cost_breakdown['thinking']:.4f} ({utilization:.1f}% of budget used)")
    md.append(f"  - Regular Input: ${cost_breakdown['input']:.4f}")
    md.append(f"  - Output: ${cost_breakdown['output']:.4f}\n")


def _add_summary_statistics(md: list, node_files: list) -> tuple[int, int, float]:
    """Add summary statistics to the markdown.

    Returns:
        tuple: (total_prompt_tokens, total_response_tokens, total_duration)
    """
    # Calculate all totals
    totals = _calculate_token_totals(node_files)

    # Add basic statistics
    md.append("## 📊 Summary Statistics\n")
    md.append(f"- **Total LLM Calls:** {len(node_files)}")
    md.append(f"- **Total Duration:** {totals['duration']:.2f}s")
    md.append(f"- **Total Tokens:** {totals['total']:,}")
    md.append(f"  - Prompt Tokens: {totals['prompt']:,}")
    md.append(f"  - Response Tokens: {totals['response']:,}")
    md.append(f"  - Cache Creation Tokens: {totals['cache_creation']:,}")
    md.append(f"  - Cache Read Tokens: {totals['cache_read']:,}")
    if totals["thinking"] > 0:
        md.append(f"  - Thinking Tokens: {totals['thinking']:,} / {totals['thinking_budget']:,} budget")

    # Add performance metrics sections
    _add_cache_performance_metrics(md, node_files, totals)
    _add_thinking_performance_metrics(md, node_files, totals)
    _add_cost_analysis(md, totals, node_files)

    return totals["prompt"], totals["response"], totals["duration"]


def _add_execution_flow_table(md: list, node_files: list) -> None:
    """Add the execution flow table to the markdown."""
    md.append("## 🔄 Execution Flow\n")
    md.append("| # | Node | Duration | Tokens | Cache | File |")
    md.append("|---|------|----------|--------|-------|------|")

    for i, file_info in enumerate(node_files, 1):
        meta = file_info["metadata"]
        filename = file_info["filename"]
        node = meta["node"]
        duration = meta["duration"]
        tokens = meta["total_tokens"]

        # Show cache usage
        cache_creation = meta.get("cache_creation", 0)
        cache_read = meta.get("cache_read", 0)
        cache_indicator = ""
        if cache_creation > 0:
            cache_indicator = f"📝 {cache_creation:,}"
        if cache_read > 0:
            if cache_indicator:
                cache_indicator += f" / 📖 {cache_read:,}"
            else:
                cache_indicator = f"📖 {cache_read:,}"
        if not cache_indicator:
            cache_indicator = "-"

        # Shorten node name for table
        short_node = node.replace("Node", "")

        md.append(
            f"| {i} | {short_node} | {duration:.2f}s | {tokens:,} | {cache_indicator} | [{filename}](./{filename}) |"
        )


def _add_error_section(md: list, trace: dict) -> None:
    """Add error section if the trace contains errors."""
    status = trace.get("status") or trace.get("final_status", "")
    if status not in ["error", "failed"]:
        return

    error = trace.get("error")

    # For workflow traces, check if any nodes failed
    if not error and "nodes" in trace:
        failed_nodes = [n for n in trace.get("nodes", []) if not n.get("success", True)]
        if failed_nodes:
            error = f"Failed nodes: {', '.join(n.get('node_id', 'Unknown') for n in failed_nodes)}"

    if error:
        md.append("\n## ❌ Error Details\n")
        md.append("```")
        if isinstance(error, dict):
            md.append(error.get("message", "Unknown error"))
        else:
            md.append(str(error))
        md.append("```\n")


def _add_generated_workflow(md: list, trace: dict) -> None:
    """Add generated workflow section if present."""
    final_store = trace.get("final_shared_store", {})
    if not final_store.get("generated_workflow"):
        return

    md.append("\n## ✅ Generated Workflow\n")
    md.append("```json")
    workflow_json = json.dumps(final_store["generated_workflow"], indent=2)
    if len(workflow_json) > 3000:
        md.append(workflow_json[:3000])
        md.append("\n... (truncated)")
    else:
        md.append(workflow_json)
    md.append("```\n")


def _add_file_navigation(md: list, node_files: list) -> None:
    """Add file navigation section to the markdown."""
    md.append("\n## 🗂️ Files\n")
    for file_info in node_files:
        filename = file_info["filename"]
        meta = file_info["metadata"]
        md.append(f"- [{filename}](./{filename}) - {meta['node']} ({meta['total_tokens']:,} tokens)")


def create_index_markdown(trace: dict, node_files: list, trace_file: Path) -> str:
    """Create an index markdown file that links to all node files."""
    md = []

    # Add header with title
    md.append(_get_trace_title(trace))

    # Add header metadata
    _add_header_metadata(md, trace, trace_file)

    # Add user input section
    user_input = _get_user_input(trace)
    md.append("## 📥 User Request\n")
    md.append("```")
    md.append(user_input)
    md.append("```\n")

    # Add summary statistics
    _add_summary_statistics(md, node_files)

    # Add execution flow table
    _add_execution_flow_table(md, node_files)

    # Add error section if applicable
    _add_error_section(md, trace)

    # Add generated workflow if present
    _add_generated_workflow(md, trace)

    # Add file navigation
    _add_file_navigation(md, node_files)

    return "\n".join(md)


def analyze_trace(trace_file: Path, output_dir: Path) -> None:
    """Convert a trace file to organized markdown files."""

    # Load trace
    with open(trace_file) as f:
        trace = json.load(f)

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get LLM calls - handle both planner and workflow trace formats
    llm_calls = []

    # Check for planner trace format (llm_calls at root level)
    if "llm_calls" in trace:
        llm_calls = trace.get("llm_calls", [])

    # Check for workflow trace format (llm data embedded in nodes)
    elif "nodes" in trace:
        # Extract LLM calls from node events
        for node in trace.get("nodes", []):
            # Handle regular node LLM calls
            if node.get("llm_call"):
                # Convert workflow trace format to match planner format
                # Now we can extract the prompt from the trace!
                # Model is already in llm_call dict
                llm_call = {
                    "node": node.get("node_id", "Unknown"),
                    "duration_ms": node.get("duration_ms", 0),
                    "prompt": node.get("llm_prompt", node.get("llm_prompt_truncated", "")),
                    "response": node.get("llm_response", node.get("llm_response_truncated", "")),
                    "tokens": {
                        "input": node["llm_call"].get("input_tokens", 0),
                        "output": node["llm_call"].get("output_tokens", 0),
                    },
                    "model": node["llm_call"].get("model", "unknown"),
                }

                # Include cost data if available in llm_call
                if "cost" in node.get("llm_call", {}):
                    llm_call["cost"] = node["llm_call"]["cost"]

                llm_calls.append(llm_call)

            # Handle repair LLM calls (stored as special event types)
            elif node.get("type") == "repair_llm_call":
                # Extract repair LLM call data
                llm_call = {
                    "node": "repair_service",
                    "duration_ms": 0,  # repair events don't track duration
                    "prompt": node.get("llm_prompt", node.get("llm_prompt_truncated", "")),
                    "response": node.get("llm_response", node.get("llm_response_truncated", "")),
                    "tokens": {"input": 0, "output": 0},  # repair events don't track tokens yet
                    "model": "claude-sonnet-4-0",  # repair uses Sonnet
                    "is_repair": True,  # flag to identify repair calls
                }
                llm_calls.append(llm_call)

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
    index_content = create_index_markdown(trace, node_files, trace_file)
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
        print("  python analyze_trace_split.py ~/.pflow/debug/planner-trace-20250815-120310.json")
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
