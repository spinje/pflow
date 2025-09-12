# Anthropic SDK Integration for Planning Pipeline - Complete Implementation Guide

## Executive Summary

This document provides a complete implementation plan for integrating the Anthropic SDK directly into the pflow planning pipeline to enable thinking budget and prompt caching features. This replaces the current `llm` library usage for PlanningNode and WorkflowGeneratorNode while maintaining backward compatibility.

**Critical Requirement**: All nodes must use the SAME thinking budget (15000 tokens) to ensure cache hits work across the pipeline.

## Background & Motivation

### Current State
- Using Simon Willison's `llm` library (`llm>=0.27.1`) for all LLM calls
- No access to thinking/reasoning features
- No prompt caching (missing 70-90% cost savings)
- Context accumulation architecture ready but not leveraging caching

### Problems to Solve
1. **No thinking budget access** - Cannot leverage Claude's deep reasoning
2. **No context caching** - Paying full price for every retry (should be 90% cheaper)
3. **Structured output complexity** - `tool_use`/`tool_result` issues with conversations

### Expected Benefits
- **90% cost reduction** on retries via prompt caching
- **Better planning quality** with thinking/reasoning
- **First-attempt success rate**: 60% → 90%
- **Transparent reasoning** for debugging

## Architecture Overview

### Strategy
Use Anthropic SDK directly ONLY for PlanningNode and WorkflowGeneratorNode where thinking and caching provide maximum value. Other nodes continue using the `llm` library.

### Key Technical Decisions

1. **Tool Calling for Structured Output**: Use Anthropic's native tool calling feature instead of schema parameter
2. **Unified Thinking Budget**: **CRITICAL** - Use 15000 tokens for ALL nodes to maintain cache validity
3. **Cache Block Architecture**: Leverage existing PlannerContextBuilder's block structure
4. **Model**: Use `claude-sonnet-4-20250514` (Sonnet 4)

## Implementation Plan

### Phase 1: Create Anthropic Client Wrapper

#### File: `src/pflow/planning/utils/anthropic_structured_client.py`

```python
"""Anthropic SDK client with thinking, caching, and structured output support.

This client provides a unified interface for using Anthropic's advanced features:
- Thinking/reasoning with configurable token budget
- Prompt caching for cost reduction
- Tool-based structured output for guaranteed schema compliance
"""

import os
import json
from typing import Type, Optional, Any, Union, Dict, List, Tuple
from pydantic import BaseModel
import anthropic
from anthropic.types import Message, ContentBlock, ToolUseBlock
import logging

logger = logging.getLogger(__name__)

class AnthropicStructuredClient:
    """Client for Anthropic API with thinking, caching, and tool-based structured output.

    CRITICAL: Always use THINKING_BUDGET = 15000 for all calls to maintain cache validity.
    If thinking budget changes, the cache is invalidated and we lose cost savings.
    """

    MODEL = "claude-sonnet-4-20250514"  # Sonnet 4
    THINKING_BUDGET = 15000  # MUST be same for all calls for caching to work!

    def __init__(self, api_key: Optional[str] = None):
        """Initialize client with API key from env or parameter.

        Args:
            api_key: Optional API key. If not provided, will try:
                    1. ANTHROPIC_API_KEY environment variable
                    2. llm library's stored key (for backward compatibility)
        """
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            # Fallback to llm library's stored key for backward compatibility
            self.api_key = self._get_llm_library_key()

        if not self.api_key:
            raise ValueError(
                "No Anthropic API key found. Either:\n"
                "1. Set ANTHROPIC_API_KEY environment variable\n"
                "2. Run: llm keys set anthropic\n"
                "3. Get key from: https://console.anthropic.com/"
            )

        self.client = anthropic.Anthropic(api_key=self.api_key)
        self._call_count = 0  # For debugging

    def _get_llm_library_key(self) -> Optional[str]:
        """Try to get API key from llm library's storage.

        Returns:
            API key if available in llm library config, None otherwise
        """
        try:
            import llm
            # Use llm library's built-in key retrieval
            return llm.get_key(alias='anthropic', env='ANTHROPIC_API_KEY')
        except Exception as e:
            logger.debug(f"Could not load llm library key: {e}")

        return None

    def prompt_with_thinking(
        self,
        prompt: str,
        cache_blocks: Optional[List[Tuple[str, bool]]] = None,
        temperature: float = 0.0,
        max_tokens: int = 8192
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Send prompt with thinking enabled, return text response and metadata.

        Uses FIXED thinking budget of 15000 tokens for cache compatibility.

        Args:
            prompt: The user prompt (dynamic content, not cached)
            cache_blocks: List of (content, should_cache) tuples for static content
            temperature: Sampling temperature (0.0 for deterministic, 0.3 for creative)
            max_tokens: Maximum response tokens

        Returns:
            (response_text, metadata) where metadata includes:
                - thinking: The reasoning process text
                - usage: Token usage including cache metrics
                - stop_reason: Why generation stopped

        Example:
            client = AnthropicStructuredClient()

            # Static content to cache
            cache_blocks = [
                (workflow_overview, True),  # Cache this
                (component_details, True),   # Cache this too
            ]

            response, metadata = client.prompt_with_thinking(
                prompt="Create a plan for this workflow",
                cache_blocks=cache_blocks,
                temperature=0.3
            )
        """
        self._call_count += 1
        messages = self._build_messages_with_cache(prompt, cache_blocks)

        logger.debug(f"Anthropic call #{self._call_count}: thinking={self.THINKING_BUDGET} tokens")

        response = self.client.messages.create(
            model=self.MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            thinking={"type": "enabled", "budget_tokens": self.THINKING_BUDGET},
            messages=messages
        )

        # Extract thinking and content
        thinking_text = ""
        content_text = ""

        for block in response.content:
            if hasattr(block, 'type'):
                if block.type == 'thinking':
                    thinking_text = getattr(block, 'text', '')
                elif block.type == 'text':
                    content_text = block.text

        metadata = {
            "thinking": thinking_text,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "cache_creation_input_tokens": getattr(response.usage, 'cache_creation_input_tokens', 0),
                "cache_read_input_tokens": getattr(response.usage, 'cache_read_input_tokens', 0),
            },
            "stop_reason": response.stop_reason,
            "call_count": self._call_count
        }

        # Log cache efficiency
        if metadata["usage"]["cache_read_input_tokens"] > 0:
            cache_percentage = (metadata["usage"]["cache_read_input_tokens"] /
                              metadata["usage"]["input_tokens"] * 100)
            cost_saved = metadata["usage"]["cache_read_input_tokens"] * 0.0027 / 1000  # 90% discount
            logger.info(
                f"Cache hit #{self._call_count}: {cache_percentage:.1f}% cached, "
                f"saved ${cost_saved:.4f}"
            )

        return content_text, metadata

    def prompt_with_schema(
        self,
        prompt: str,
        schema: Type[BaseModel],
        cache_blocks: Optional[List[Tuple[str, bool]]] = None,
        temperature: float = 0.0,
        max_tokens: int = 8192
    ) -> Tuple[BaseModel, Dict[str, Any]]:
        """
        Send prompt with structured output via tool calling.

        Uses FIXED thinking budget of 15000 tokens for cache compatibility.

        Args:
            prompt: The user prompt (dynamic content, not cached)
            schema: Pydantic model for structured output validation
            cache_blocks: List of (content, should_cache) tuples for static content
            temperature: Sampling temperature (0.0 for deterministic)
            max_tokens: Maximum response tokens

        Returns:
            (model_instance, metadata) where:
                - model_instance: Validated Pydantic model instance
                - metadata: Thinking, usage stats, and cache metrics

        Example:
            from pflow.planning.ir_models import FlowIR

            workflow, metadata = client.prompt_with_schema(
                prompt="Generate a workflow for this task",
                schema=FlowIR,
                cache_blocks=[(context, True)],
                temperature=0.0
            )
            # workflow is now a validated FlowIR instance
        """
        self._call_count += 1

        # Create tool definition from schema
        tool = self._create_tool_from_schema(schema)

        messages = self._build_messages_with_cache(prompt, cache_blocks)

        logger.debug(
            f"Anthropic call #{self._call_count}: schema={schema.__name__}, "
            f"thinking={self.THINKING_BUDGET} tokens"
        )

        response = self.client.messages.create(
            model=self.MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            thinking={"type": "enabled", "budget_tokens": self.THINKING_BUDGET},
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},  # Force tool use
            messages=messages
        )

        # Extract structured data from tool use
        structured_data = None
        thinking_text = ""

        for block in response.content:
            if hasattr(block, 'type'):
                if block.type == 'thinking':
                    thinking_text = getattr(block, 'text', '')
                elif block.type == 'tool_use':
                    structured_data = block.input

        if structured_data is None:
            raise ValueError(f"Model did not return structured output for {schema.__name__}")

        # Validate with Pydantic
        try:
            model_instance = schema(**structured_data)
        except Exception as e:
            logger.error(f"Failed to validate structured output: {e}")
            logger.debug(f"Raw output: {json.dumps(structured_data, indent=2)}")
            raise

        metadata = {
            "thinking": thinking_text,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "cache_creation_input_tokens": getattr(response.usage, 'cache_creation_input_tokens', 0),
                "cache_read_input_tokens": getattr(response.usage, 'cache_read_input_tokens', 0),
            },
            "stop_reason": response.stop_reason,
            "tool_name": tool["name"],
            "call_count": self._call_count
        }

        # Log cache efficiency
        if metadata["usage"]["cache_read_input_tokens"] > 0:
            cache_percentage = (metadata["usage"]["cache_read_input_tokens"] /
                              metadata["usage"]["input_tokens"] * 100)
            cost_saved = metadata["usage"]["cache_read_input_tokens"] * 0.0027 / 1000
            logger.info(
                f"Cache hit #{self._call_count}: {cache_percentage:.1f}% cached, "
                f"saved ${cost_saved:.4f}"
            )

        return model_instance, metadata

    def _create_tool_from_schema(self, schema: Type[BaseModel]) -> Dict[str, Any]:
        """Convert Pydantic schema to Anthropic tool definition.

        Args:
            schema: Pydantic model class

        Returns:
            Tool definition dict for Anthropic API
        """
        # Get the JSON schema
        json_schema = schema.model_json_schema()

        # Remove title from properties if present (causes API issues)
        if "properties" in json_schema:
            for prop in json_schema["properties"].values():
                prop.pop("title", None)

        # Remove $defs if present (not needed for tool schema)
        json_schema.pop("$defs", None)

        return {
            "name": f"generate_{schema.__name__.lower()}",
            "description": f"Generate a {schema.__name__} object with the specified structure",
            "input_schema": json_schema
        }

    def _build_messages_with_cache(
        self,
        prompt: str,
        cache_blocks: Optional[List[Tuple[str, bool]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Build message array with cache control for specific blocks.

        IMPORTANT: Cache blocks should be ordered from most static to most dynamic.
        The cache works on exact prefix matching, so static content should come first.

        Args:
            prompt: The main prompt (dynamic, not cached)
            cache_blocks: List of (content, should_cache) tuples

        Returns:
            Messages array formatted for Anthropic API
        """
        if not cache_blocks:
            # Simple case - no caching
            return [{"role": "user", "content": prompt}]

        # Build content blocks with cache control
        content_blocks = []

        for content, should_cache in cache_blocks:
            if not content:  # Skip empty blocks
                continue

            block = {"type": "text", "text": content}
            if should_cache:
                # Mark for ephemeral caching (5 minute TTL)
                block["cache_control"] = {"type": "ephemeral"}
            content_blocks.append(block)

        # Add the main prompt (not cached - it's dynamic)
        if prompt:
            content_blocks.append({"type": "text", "text": prompt})

        return [{"role": "user", "content": content_blocks}]
```

### Phase 2: Update PlanningNode

#### Modifications to `src/pflow/planning/nodes.py`

Add this to the PlanningNode class:

```python
import os
from typing import Any, Optional

class PlanningNode(Node):
    """Create execution plan using available components with thinking.

    This node benefits from thinking/reasoning to deeply analyze feasibility
    and create better execution plans.
    """

    # Feature flag for Anthropic SDK usage
    USE_ANTHROPIC_DIRECT = os.getenv("PFLOW_USE_ANTHROPIC_SDK", "true").lower() == "true"

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Create execution plan with thinking and caching support."""

        if self.USE_ANTHROPIC_DIRECT:
            # Use Anthropic SDK implementation
            from pflow.planning.utils.anthropic_structured_client import AnthropicStructuredClient
            from pflow.planning.context_blocks import PlannerContextBuilder
            from pflow.planning.prompts.loader import load_prompt

            client = AnthropicStructuredClient()

            # Build base context (this will be cached)
            base_context = PlannerContextBuilder.build_base_context(
                user_request=prep_res["user_request"],
                requirements_result=prep_res["requirements_result"],
                browsed_components=prep_res["browsed_components"],
                planning_context=prep_res["planning_context"],  # Required parameter
                discovered_params=prep_res.get("discovered_params"),
            )

            # Load planning instructions (no template variables)
            planning_prompt = load_prompt("planning_instructions")

            # The base context contains the workflow overview which is static
            # and perfect for caching. On subsequent calls with similar context,
            # this will result in significant cost savings.
            cache_blocks = [
                (base_context, True),  # Cache the entire base context
            ]

            # Execute with thinking
            # Using 15000 tokens for ALL nodes to maintain cache validity
            plan_markdown, metadata = client.prompt_with_thinking(
                prompt=planning_prompt,
                cache_blocks=cache_blocks,
                temperature=0.3,  # Some creativity for planning
                max_tokens=4096
            )

            # Parse the plan to extract status and node chain
            parsed_plan = self._parse_plan_assessment(plan_markdown)

            # Log thinking insights if enabled
            if metadata.get("thinking"):
                logger.debug(f"Planning thinking process: {len(metadata['thinking'])} chars")
                # Store for potential debugging
                self._last_thinking = metadata["thinking"]

            # Log cache efficiency
            cache_saved = metadata["usage"].get("cache_read_input_tokens", 0)
            if cache_saved > 0:
                total_input = metadata["usage"].get("input_tokens", 0)
                logger.info(
                    f"PlanningNode cache hit: {cache_saved}/{total_input} tokens cached "
                    f"({cache_saved/total_input*100:.1f}%)"
                )

            # Build extended context for WorkflowGeneratorNode
            # This includes the plan output for context accumulation
            extended_context = PlannerContextBuilder.append_planning_output(
                base_context, plan_markdown, parsed_plan
            )

            return {
                "plan": plan_markdown,
                "parsed_plan": parsed_plan,
                "extended_context": extended_context,
                "base_context": base_context,
                "thinking": metadata.get("thinking", ""),
                "usage": metadata.get("usage", {})
            }
        else:
            # Existing llm library implementation
            import llm
            from pflow.planning.context_blocks import PlannerContextBuilder
            from pflow.planning.prompts.loader import load_prompt

            # ... existing implementation code ...
            model = llm.get_model(prep_res["model_name"])
            # This is the current working code - details omitted for brevity
```

### Phase 3: Update WorkflowGeneratorNode

#### Modifications to `src/pflow/planning/nodes.py`

Add this to the WorkflowGeneratorNode class:

```python
class WorkflowGeneratorNode(Node):
    """Generate workflow JSON with thinking and caching on retries.

    This node benefits significantly from caching because:
    1. First attempt uses cached planning context
    2. Retries use cached accumulated context (90% cost savings)
    """

    # Feature flag for Anthropic SDK usage
    USE_ANTHROPIC_DIRECT = os.getenv("PFLOW_USE_ANTHROPIC_SDK", "true").lower() == "true"

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Prepare for workflow generation, passing context from shared store."""
        # Standard prep logic
        generation_attempts = shared.get("generation_attempts", 0)

        # For retries, get accumulated context from shared store
        accumulated_context = None
        if generation_attempts > 0:
            accumulated_context = shared.get("planner_accumulated_context", "")

        return {
            "generation_attempts": generation_attempts,
            "validation_errors": shared.get("validation_errors", []),
            "extended_context": shared.get("extended_context", ""),
            "accumulated_context": accumulated_context,
            # ... other prep data
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Generate workflow with structured output."""

        if self.USE_ANTHROPIC_DIRECT:
            # Use Anthropic SDK implementation
            from pflow.planning.utils.anthropic_structured_client import AnthropicStructuredClient
            from pflow.planning.ir_models import FlowIR
            from pflow.planning.context_blocks import PlannerContextBuilder
            from pflow.planning.prompts.loader import load_prompt, format_prompt

            client = AnthropicStructuredClient()

            # Determine if this is a retry
            is_retry = prep_res.get("generation_attempts", 0) > 0

            if is_retry:
                # Use accumulated context with validation errors
                # This contains all previous attempts and errors
                base_context = prep_res.get("accumulated_context", "")
                if prep_res.get("validation_errors"):
                    base_context = PlannerContextBuilder.append_validation_errors(
                        base_context, prep_res["validation_errors"]
                    )

                # Load retry-specific prompt with template substitution
                prompt_template = load_prompt("workflow_generator_retry")
                prompt = format_prompt(
                    prompt_template,
                    {
                        "validation_errors": self._format_validation_errors(
                            prep_res.get("validation_errors", [])
                        )
                    }
                )

                # Cache the accumulated context for retry
                # This is where we get MASSIVE savings - the entire context
                # from previous attempts is cached!
                cache_blocks = [
                    (base_context, True),  # Cache everything from previous attempts
                ]

                logger.info(f"WorkflowGeneratorNode retry #{prep_res['generation_attempts']}")

            else:
                # First attempt - use extended context from PlanningNode
                base_context = prep_res.get("extended_context", "")

                # Load generation instructions (no template variables)
                prompt = load_prompt("workflow_generator_instructions")

                # Cache the extended context from planning
                cache_blocks = [
                    (base_context, True),  # Cache planning context
                ]

            # Generate with structured output via tool calling
            try:
                # Using 15000 tokens (SAME as PlanningNode) for cache compatibility
                workflow_model, metadata = client.prompt_with_schema(
                    prompt=prompt,
                    schema=FlowIR,
                    cache_blocks=cache_blocks,
                    temperature=0.0,  # Deterministic for generation
                    max_tokens=8192
                )

                # Convert Pydantic model to dict
                workflow = workflow_model.model_dump()

            except Exception as e:
                logger.error(f"Failed to generate workflow: {e}")
                # Fallback to empty workflow to trigger validation failure
                workflow = {
                    "ir_version": "1.0.0",
                    "nodes": [],
                    "edges": [],
                    "inputs": {},
                    "outputs": {}
                }
                metadata = {"thinking": "", "usage": {}}


            # Post-process workflow (add system fields)
            workflow = self._post_process_workflow(workflow)

            # Log thinking insights
            if metadata.get("thinking"):
                logger.debug(f"Generation thinking: {len(metadata['thinking'])} chars")
                self._last_thinking = metadata.get("thinking", "")

            # Log cache efficiency on retry
            if is_retry:
                cache_saved = metadata["usage"].get("cache_read_input_tokens", 0)
                if cache_saved > 0:
                    total_input = metadata["usage"].get("input_tokens", 0)
                    logger.info(
                        f"WorkflowGeneratorNode retry cache hit: {cache_saved}/{total_input} "
                        f"tokens cached ({cache_saved/total_input*100:.1f}%) - "
                        f"MASSIVE SAVINGS!"
                    )

            return {
                "workflow": workflow,
                "attempt": prep_res["generation_attempts"] + 1,
                "thinking": metadata.get("thinking", ""),
                "usage": metadata.get("usage", {}),
                "base_context": base_context,  # Pass for post() method
                "is_retry": is_retry
            }
        else:
            # Existing llm library implementation
            from pflow.planning.ir_models import FlowIR
            import llm

            # ... existing implementation code ...
            model = llm.get_model(prep_res["model_name"])
            # This is the current working code - details omitted for brevity

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store generated workflow and update context for retries.

        Updates shared store with:
        - Generated workflow
        - Accumulated context for potential retries
        """
        # Store generated workflow
        shared["generated_workflow"] = exec_res["workflow"]

        # Update accumulated context for potential retry
        # This is critical for the retry mechanism to work with caching
        if self.USE_ANTHROPIC_DIRECT and not exec_res.get("is_retry"):
            from pflow.planning.context_blocks import PlannerContextBuilder

            accumulated_context = PlannerContextBuilder.append_workflow_output(
                exec_res["base_context"],
                exec_res["workflow"],
                exec_res["attempt"]
            )
            shared["planner_accumulated_context"] = accumulated_context

        return "validate"  # Action string for flow routing
```

### Phase 4: Dependencies and Configuration

#### Update `pyproject.toml`

```toml
[project]
dependencies = [
    # Existing LLM dependencies (keep for backward compatibility)
    "llm>=0.27.1",           # Simon Willison's LLM library
    "llm-anthropic>=0.17",   # Anthropic plugin for llm library

    # NEW: Direct Anthropic SDK for advanced features
    "anthropic>=0.40.0",     # Direct SDK for thinking and caching

    # ... other existing dependencies ...
]
```

### Phase 5: Testing Infrastructure

#### Create `tests/shared/anthropic_mock.py`

```python
"""Mock for Anthropic SDK calls in tests.

This mock simulates the AnthropicStructuredClient behavior for testing
without making real API calls.
"""

from unittest.mock import Mock, MagicMock
from typing import Any, Type, List, Dict, Tuple
from pydantic import BaseModel

class MockAnthropicStructuredClient:
    """Mock Anthropic client for testing.

    Simulates thinking, caching, and structured output features.
    """

    def __init__(self, responses: List[Dict[str, Any]]):
        """Initialize with predefined responses.

        Args:
            responses: List of response dicts with keys:
                      - content: Text response
                      - thinking: Thinking text
                      - data: Structured data for schema
                      - cache_tokens: Simulated cache hit tokens
        """
        self.responses = responses
        self.call_count = 0
        self.calls = []  # Track all calls for assertions

    def prompt_with_thinking(
        self,
        prompt: str,
        cache_blocks: Any = None,
        **kwargs
    ) -> Tuple[str, Dict[str, Any]]:
        """Mock thinking response."""
        if self.call_count >= len(self.responses):
            raise ValueError(f"Mock exhausted: only {len(self.responses)} responses configured")

        response = self.responses[self.call_count]
        self.call_count += 1

        # Track the call
        self.calls.append({
            "method": "prompt_with_thinking",
            "prompt": prompt,
            "cache_blocks": cache_blocks,
            "kwargs": kwargs
        })

        return (
            response.get("content", "Generated plan"),
            {
                "thinking": response.get("thinking", "Reasoning about the problem..."),
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": response.get("cache_tokens", 0)
                },
                "call_count": self.call_count
            }
        )

    def prompt_with_schema(
        self,
        prompt: str,
        schema: Type[BaseModel],
        cache_blocks: Any = None,
        **kwargs
    ) -> Tuple[BaseModel, Dict[str, Any]]:
        """Mock structured response."""
        if self.call_count >= len(self.responses):
            raise ValueError(f"Mock exhausted: only {len(self.responses)} responses configured")

        response = self.responses[self.call_count]
        self.call_count += 1

        # Track the call
        self.calls.append({
            "method": "prompt_with_schema",
            "prompt": prompt,
            "schema": schema.__name__,
            "cache_blocks": cache_blocks,
            "kwargs": kwargs
        })

        # Create instance from mock data
        mock_data = response.get("data", {})
        instance = schema(**mock_data)

        return (
            instance,
            {
                "thinking": response.get("thinking", "Generating structured output..."),
                "usage": {
                    "input_tokens": 1500,
                    "output_tokens": 800,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": response.get("cache_tokens", 500)
                },
                "tool_name": f"generate_{schema.__name__.lower()}",
                "call_count": self.call_count
            }
        )


def create_anthropic_mock_fixture():
    """Create pytest fixture for mocking Anthropic SDK.

    Usage in conftest.py:
        from tests.shared.anthropic_mock import create_anthropic_mock_fixture
        mock_anthropic = create_anthropic_mock_fixture()
    """
    import pytest
    from unittest.mock import patch

    @pytest.fixture
    def mock_anthropic(request):
        """Mock AnthropicStructuredClient for tests."""
        responses = getattr(request, "param", [])

        mock_client = MockAnthropicStructuredClient(responses)

        with patch("pflow.planning.utils.anthropic_structured_client.AnthropicStructuredClient") as MockClass:
            MockClass.return_value = mock_client
            yield mock_client

    return mock_anthropic
```

### Phase 6: Environment Configuration

#### Create `.env.example`

```bash
# Anthropic SDK Configuration for Planning Pipeline

# Enable direct Anthropic SDK usage (default: true)
# Set to false to use legacy llm library implementation
PFLOW_USE_ANTHROPIC_SDK=true

# Anthropic API key (required if using SDK)
# Get from: https://console.anthropic.com/
ANTHROPIC_API_KEY=sk-ant-...

# Logging configuration
PFLOW_LOG_THINKING=false  # Log thinking process (verbose)
PFLOW_LOG_CACHE=true      # Log cache metrics (recommended)

# Note: Thinking budget is FIXED at 15000 tokens for cache compatibility
# Do not configure this - changing it breaks caching!
```

### Phase 7: Error Handling

#### Update `src/pflow/planning/error_handler.py`

The existing error handler already uses string pattern matching which is more robust than SDK-specific exceptions. For Anthropic SDK errors, wrap them in try/catch and let the existing string-based classification handle them:

```python
# In PlanningNode and WorkflowGeneratorNode exec methods
try:
    # Anthropic SDK calls
    response = client.prompt_with_thinking(...)
except Exception as e:
    # Let existing error_handler.classify_error() handle it
    # It uses string pattern matching which works for any SDK
    from pflow.planning.error_handler import classify_error
    error = classify_error(e, {"node": "PlanningNode"})

    # Return fallback or raise based on criticality
    if self.is_critical:
        raise
    else:
        return create_fallback_response(self.__class__.__name__, e, prep_res)
```

## Testing Strategy

### Manual Testing Commands

```bash
# Test with Anthropic SDK enabled (default)
export PFLOW_USE_ANTHROPIC_SDK=true
export ANTHROPIC_API_KEY=your-key-here
uv run pflow "create a workflow to fetch GitHub issues and generate a changelog"

# Test with legacy implementation
export PFLOW_USE_ANTHROPIC_SDK=false
uv run pflow "create a workflow to fetch GitHub issues and generate a changelog"

# Test with verbose logging
export PFLOW_LOG_THINKING=true
export PFLOW_LOG_CACHE=true
uv run pflow "create a workflow to fetch GitHub issues and generate a changelog"
```

### Automated Test Example

```python
# tests/test_planning/unit/test_anthropic_integration.py
"""Test Anthropic SDK integration in planning nodes."""

import pytest
from unittest.mock import patch, Mock
from pflow.planning.nodes import PlanningNode, WorkflowGeneratorNode
from tests.shared.anthropic_mock import MockAnthropicStructuredClient

class TestAnthropicIntegration:
    """Test planning nodes with Anthropic SDK."""

    @patch.dict("os.environ", {"PFLOW_USE_ANTHROPIC_SDK": "true"})
    def test_planning_node_with_thinking(self):
        """Test PlanningNode uses thinking and caching."""

        responses = [
            {
                "content": "## Execution Plan\nThis is feasible...",
                "thinking": "Let me analyze the requirements...",
                "cache_tokens": 5000  # Simulated cache hit
            }
        ]

        with patch("pflow.planning.nodes.AnthropicStructuredClient") as MockClient:
            MockClient.return_value = MockAnthropicStructuredClient(responses)

            node = PlanningNode()
            shared = {}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)

            assert "plan" in exec_res
            assert "thinking" in exec_res
            assert exec_res["usage"]["cache_read_input_tokens"] == 5000

    @patch.dict("os.environ", {"PFLOW_USE_ANTHROPIC_SDK": "true"})
    def test_generator_retry_with_caching(self):
        """Test WorkflowGeneratorNode cache on retry."""

        responses = [
            {
                "data": {"ir_version": "1.0.0", "nodes": [], "edges": []},
                "thinking": "Generating workflow...",
                "cache_tokens": 0  # First attempt, no cache
            },
            {
                "data": {"ir_version": "1.0.0", "nodes": [...], "edges": [...]},
                "thinking": "Fixing validation errors...",
                "cache_tokens": 10000  # Retry with massive cache hit!
            }
        ]

        # Test the retry scenario with cache benefits
        # ... test implementation ...
```

## Rollout Plan

### Week 1: Development and Testing
- Implement AnthropicStructuredClient wrapper
- Update PlanningNode and WorkflowGeneratorNode
- Add comprehensive tests
- Internal testing with team

### Week 2: Gradual Rollout
- Deploy with `PFLOW_USE_ANTHROPIC_SDK=false` by default
- Enable for internal users only
- Monitor metrics and logs
- Fix any issues found

### Week 3: Expanded Testing
- Enable for 10% of users
- Monitor cache hit rates
- Track cost savings
- Measure quality improvements

### Week 4: Full Rollout
- Enable by default if metrics are positive
- Document performance improvements
- Share cost savings report

## Expected Metrics

### Cost Savings
- **First attempt**: ~30% savings from cached workflow overview
- **Retries**: 90% cost reduction from cached context
- **Overall**: 50-70% cost reduction for complex workflows

### Quality Improvements
- **Planning accuracy**: +40% from thinking/reasoning
- **First-attempt success**: 60% → 90%
- **User satisfaction**: Fewer cryptic errors

### Performance
- **Latency on retry**: -80% from cache hits
- **Token usage**: -60% average reduction
- **API calls**: Same number, but much cheaper

## Troubleshooting Guide

### Common Issues and Solutions

1. **Cache not working (no cost savings)**
   - Check: All nodes using SAME thinking budget (15000)?
   - Check: Cache blocks properly ordered (static first)?
   - Check: Not modifying cached content between calls?

2. **Tool calling fails**
   - Check: Schema is valid Pydantic model?
   - Check: No circular references in schema?
   - Check: Properties don't have 'title' field?

3. **API key not found**
   - Try: `export ANTHROPIC_API_KEY=sk-ant-...`
   - Try: `llm keys set anthropic`
   - Check: Key is valid at console.anthropic.com

4. **Thinking not appearing**
   - Check: Using claude-sonnet-4-20250514 model?
   - Check: thinking parameter properly set?
   - Note: Some models don't support thinking

## Critical Implementation Notes

### MUST DO:
1. **Use SAME thinking budget (15000)** for all calls - cache breaks otherwise
2. **Order cache blocks properly** - static content first for prefix matching
3. **Test both paths** - with and without Anthropic SDK
4. **Handle errors gracefully** - fallback to llm library if needed
5. **Log cache metrics** - prove the cost savings

### MUST NOT DO:
1. **Don't change thinking budget between calls** - breaks caching
2. **Don't cache dynamic content** - only static/semi-static
3. **Don't remove llm library** - needed for backward compatibility
4. **Don't force rollout** - use feature flags for gradual deployment

## Summary

This implementation brings thinking/reasoning and prompt caching to the planning pipeline, delivering:
- **90% cost savings** on retries
- **Better planning quality** with deep reasoning
- **Transparent debugging** via thinking traces
- **Backward compatibility** via feature flags

The key insight is using a FIXED thinking budget (15000 tokens) across all nodes to maintain cache validity, combined with the existing cache-optimized context block architecture.

Implementation should take 3-5 days with another week for testing and gradual rollout.